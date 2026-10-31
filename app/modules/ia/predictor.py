"""Pipeline de entrenamiento, validación anti-leakage, serialización Joblib e inferencia LightGBM (M03/M04).

Cumple con:
- Entregable E-04 y E-05: 1,000 citas históricas acreditadas, split estratificado 70% (700) / 15% (150) / 15% (150).
- RF-041 a RF-056: Comparación Baseline (LogisticRegression) vs. Modelo Principal (LightGBM),
  umbrales operativos (0.450 ALTO, 0.300 MEDIO), meta F1-Score >= 82% en Test, y explicabilidad local TreeSHAP.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dominio import (
    CANALES_ORIGEN,
    DIAS_SEMANA,
    ESPECIALIDADES,
    FRANJAS_CITA,
    TIPOS_PACIENTE,
)
from app.modules.citas.synthetic import generar_citas

VERSION_MODELO = "LightGBM_v1.0.0"
VERSION_DATASET = "DS_SINTETICO_CRP_v1.0"
SEMILLA_OFICIAL = 42
UMBRAL_ALTO = 0.450
UMBRAL_MEDIO = 0.300

RUTA_ARTEFACTO = Path(__file__).resolve().parent / "artifacts" / "modelo_predicitas_v1.joblib"

# Columnas crudas pre-cita estrictamente autorizadas (RF-032 / RF-040)
FEATURES_CATEGORICAS = [
    "especialidad",
    "tipo_paciente",
    "canal_origen",
    "franja_horaria",
    "dia_semana",
]
FEATURES_NUMERICAS_BASE = [
    "antelacion_dias",
    "inasistencias_previas",
    "asistencias_previas",
    "reprogramaciones_prev",
]
FEATURES_NUMERICAS_DERIVADAS = [
    "tasa_no_show_previa",
    "es_reserva_lejana",
]
FEATURES_NUMERICAS = FEATURES_NUMERICAS_BASE + FEATURES_NUMERICAS_DERIVADAS
FEATURES_ENTRADA_MODELO = FEATURES_NUMERICAS + FEATURES_CATEGORICAS

# Lista negra explícita de columnas prohibidas en X (Control Anti-Data Leakage — RF-048 / RNF-023)
COLUMNAS_PROHIBIDAS_LEAKAGE = {
    "id_cita",
    "id_cita_externa",
    "paciente_anon_id",
    "estado_actual",
    "target_no_show",
    "fecha_hora_cita",
    "fecha_registro_cita",
    "medico",
}

_CACHE_MODELO: dict[str, Any] | None = None


def _derivar_features_fila(fila: dict[str, Any]) -> dict[str, Any]:
    """Calcula variables pre-cita derivadas usando únicamente datos conocidos al momento de agendar."""
    antelacion = int(fila["antelacion_dias"])
    inasistencias = int(fila.get("inasistencias_previas", 0) or 0)
    asistencias = int(fila.get("asistencias_previas", 0) or 0)
    reprogramaciones = int(fila.get("reprogramaciones_prev", 0) or 0)
    tipo = str(fila["tipo_paciente"]).upper()
    canal = str(fila["canal_origen"]).upper()

    tasa_previa = inasistencias / (asistencias + inasistencias + 1.0)
    es_lejana = 1 if antelacion >= 15 else 0

    return {
        "antelacion_dias": antelacion,
        "inasistencias_previas": inasistencias,
        "asistencias_previas": asistencias,
        "reprogramaciones_prev": reprogramaciones,
        "tasa_no_show_previa": round(tasa_previa, 4),
        "es_reserva_lejana": es_lejana,
        "especialidad": str(fila["especialidad"]).upper(),
        "tipo_paciente": tipo,
        "canal_origen": canal,
        "franja_horaria": str(fila["franja_horaria"]).upper(),
        "dia_semana": str(fila["dia_semana"]).upper(),
    }


def _construir_matriz(registros: list[dict[str, Any]]) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Convierte una lista de citas en matriz 2D de objetos para el ColumnTransformer."""
    filas_enriquecidas = [_derivar_features_fila(r) for r in registros]
    matriz = np.array(
        [[f[col] for col in FEATURES_ENTRADA_MODELO] for f in filas_enriquecidas],
        dtype=object,
    )
    return matriz, filas_enriquecidas


def _crear_preprocesador() -> ColumnTransformer:
    idx_num = list(range(len(FEATURES_NUMERICAS)))
    idx_cat = list(range(len(FEATURES_NUMERICAS), len(FEATURES_ENTRADA_MODELO)))

    rama_numerica = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ])
    rama_categorica = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        (
            "ohe",
            OneHotEncoder(
                categories=[
                    list(ESPECIALIDADES),
                    list(TIPOS_PACIENTE),
                    list(CANALES_ORIGEN),
                    list(FRANJAS_CITA),
                    list(DIAS_SEMANA),
                ],
                handle_unknown="ignore",
                sparse_output=False,
            ),
        ),
    ])
    return ColumnTransformer(
        transformers=[
            ("num", rama_numerica, idx_num),
            ("cat", rama_categorica, idx_cat),
        ],
        remainder="drop",
    )


def verificar_sin_data_leakage(
    registros_historicos: list[dict[str, Any]],
    idx_train: np.ndarray,
    idx_val: np.ndarray,
    idx_test: np.ndarray,
) -> dict[str, Any]:
    """Ejecuta las verificaciones formales de ausencia de fuga de datos (RF-048 / RNF-023)."""
    interseccion_prohibida = set(FEATURES_ENTRADA_MODELO) & COLUMNAS_PROHIBIDAS_LEAKAGE
    if interseccion_prohibida:
        raise ValueError(f"Data leakage detectado: columnas prohibidas en X: {interseccion_prohibida}")

    ids_train = {registros_historicos[i]["id_cita_externa"] for i in idx_train}
    ids_val = {registros_historicos[i]["id_cita_externa"] for i in idx_val}
    ids_test = {registros_historicos[i]["id_cita_externa"] for i in idx_test}
    if (ids_train & ids_val) or (ids_train & ids_test) or (ids_val & ids_test):
        raise ValueError("Data leakage detectado: contaminación de registros entre Train, Val y Test.")

    violaciones_temporales = 0
    violaciones_nuevo = 0
    for r in registros_historicos:
        if int(r["antelacion_dias"]) < 0:
            violaciones_temporales += 1
        if r["tipo_paciente"] == "NUEVO" and (r["inasistencias_previas"] > 0 or r["asistencias_previas"] > 0):
            violaciones_nuevo += 1

    if violaciones_temporales > 0 or violaciones_nuevo > 0:
        raise ValueError(
            f"Inconsistencia temporal/clínica: antelacion<0={violaciones_temporales}, nuevo_con_historial={violaciones_nuevo}"
        )

    return {
        "aprobado": True,
        "columnas_prohibidas_excluidas": sorted(COLUMNAS_PROHIBIDAS_LEAKAGE),
        "interseccion_particiones": 0,
        "violaciones_temporales": 0,
        "invariante_paciente_nuevo_ok": True,
    }


def _calcular_metricas(y_true: np.ndarray, probs: np.ndarray, umbral: float) -> dict[str, Any]:
    y_pred = (probs >= umbral).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "umbral": round(float(umbral), 3),
        "f1_score": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, probs)), 4),
        "pr_auc": round(float(average_precision_score(y_true, probs)), 4),
        "matriz_confusion": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp),
        },
    }


def _auditar_equidad_subgrupos(
    registros_test: list[dict[str, Any]],
    y_test: np.ndarray,
    probs_test: np.ndarray,
    umbral: float,
) -> dict[str, Any]:
    """Calcula métricas desagregadas por especialidad, tipo_paciente y franja_horaria (RF-049 / RNF-024)."""
    dimensiones = ("especialidad", "tipo_paciente", "franja_horaria")
    resultado: dict[str, Any] = {}
    for dim in dimensiones:
        grupos: dict[str, dict[str, Any]] = {}
        valores = sorted({str(r[dim]) for r in registros_test})
        for val in valores:
            mask = np.array([str(r[dim]) == val for r in registros_test])
            if mask.sum() == 0 or len(np.unique(y_test[mask])) < 2:
                continue
            y_sub = y_test[mask]
            p_sub = probs_test[mask]
            pred_sub = (p_sub >= umbral).astype(int)
            grupos[val] = {
                "n": int(mask.sum()),
                "tasa_positiva_real": round(float(y_sub.mean()), 4),
                "f1_score": round(float(f1_score(y_sub, pred_sub, zero_division=0)), 4),
                "recall": round(float(recall_score(y_sub, pred_sub, zero_division=0)), 4),
                "precision": round(float(precision_score(y_sub, pred_sub, zero_division=0)), 4),
            }
        resultado[dim] = grupos
    return resultado


def clasificar_nivel_riesgo(probabilidad: float) -> str:
    """Categoriza la probabilidad continua en BAJO (<0.300), MEDIO (0.300-0.450) o ALTO (>0.450)."""
    if probabilidad > UMBRAL_ALTO:
        return "ALTO"
    if probabilidad >= UMBRAL_MEDIO:
        return "MEDIO"
    return "BAJO"


def explicar_prediccion(
    pipeline_lgbm: Pipeline,
    fila_cruda: dict[str, Any],
    probabilidad: float,
) -> str:
    """Extrae los 3 factores locales de mayor impacto mediante TreeSHAP nativo de LightGBM (pred_contrib=True)."""
    X_mat, filas_enriq = _construir_matriz([fila_cruda])
    f = filas_enriq[0]

    prep: ColumnTransformer = pipeline_lgbm.named_steps["prep"]
    clf: LGBMClassifier = pipeline_lgbm.named_steps["clf"]

    X_trans = prep.transform(X_mat)
    contrib = clf.booster_.predict(X_trans, pred_contrib=True)[0]

    # Mapear contribuciones de las 22 columnas transformadas a los atributos clínicos legibles
    impacto_inasistencias = float(contrib[1] + contrib[4])
    impacto_antelacion = float(contrib[0] + contrib[5])
    impacto_reprogramaciones = float(contrib[3])
    impacto_asistencias = float(contrib[2])

    offset = len(FEATURES_NUMERICAS)
    n_esp = len(ESPECIALIDADES)
    n_tipo = len(TIPOS_PACIENTE)
    n_canal = len(CANALES_ORIGEN)
    n_franja = len(FRANJAS_CITA)

    impacto_esp = float(np.sum(contrib[offset : offset + n_esp]))
    offset += n_esp
    impacto_tipo = float(np.sum(contrib[offset : offset + n_tipo]))
    offset += n_tipo
    impacto_canal = float(np.sum(contrib[offset : offset + n_canal]))
    offset += n_canal
    impacto_franja = float(np.sum(contrib[offset : offset + n_franja]))
    offset += n_franja
    impacto_dia = float(np.sum(contrib[offset : offset + len(DIAS_SEMANA)]))

    candidatos = [
        (impacto_inasistencias, f"Inasistencias previas: {f['inasistencias_previas']}"),
        (impacto_antelacion, f"Antelación: {f['antelacion_dias']} días"),
        (impacto_reprogramaciones, f"Reprogramaciones: {f['reprogramaciones_prev']}"),
        (impacto_tipo, f"Paciente {f['tipo_paciente']}"),
        (impacto_canal, f"Canal {f['canal_origen']}"),
        (impacto_franja, f"Turno {f['franja_horaria']}"),
        (impacto_esp, f"Especialidad {f['especialidad']}"),
        (impacto_asistencias, f"Asistencias previas: {f['asistencias_previas']}"),
        (impacto_dia, f"Día {f['dia_semana']}"),
    ]

    if probabilidad >= UMBRAL_MEDIO:
        # Priorizar los factores que empujan hacia mayor riesgo de inasistencia
        ordenados = sorted(candidatos, key=lambda x: x[0], reverse=True)
    else:
        # Para citas de riesgo BAJO, mostrar los principales factores protectores (más negativos)
        ordenados = sorted(candidatos, key=lambda x: x[0])

    top_3 = [
        f"{idx}) {etiqueta} ({valor:+.2f})"
        for idx, (valor, etiqueta) in enumerate(ordenados[:3], start=1)
    ]
    resumen = f"Factores clave: {' | '.join(top_3)} [Simulado]"
    return resumen[:255]


def cargar_citas_historicas(db: Session | None = None) -> list[dict[str, Any]]:
    """Lee las 1,000 citas históricas con desenlace desde la tabla `citas` o desde el generador oficial."""
    if db is not None:
        from app.modules.citas.models import Cita

        filas_bd = list(
            db.scalars(
                select(Cita)
                .where(Cita.target_no_show.is_not(None))
                .order_by(Cita.id_cita_externa.asc())
            )
        )
        if len(filas_bd) >= 1000:
            return [
                {
                    "id_cita_externa": c.id_cita_externa,
                    "paciente_anon_id": c.paciente_anon_id,
                    "sede": c.sede,
                    "especialidad": c.especialidad,
                    "medico": c.medico,
                    "fecha_hora_cita": c.fecha_hora_cita.isoformat(),
                    "fecha_registro_cita": c.fecha_registro_cita.isoformat(),
                    "antelacion_dias": c.antelacion_dias,
                    "tipo_paciente": c.tipo_paciente,
                    "canal_origen": c.canal_origen,
                    "franja_horaria": c.franja_horaria,
                    "dia_semana": c.dia_semana,
                    "inasistencias_previas": c.inasistencias_previas,
                    "reprogramaciones_prev": c.reprogramaciones_prev,
                    "asistencias_previas": c.asistencias_previas,
                    "estado_actual": c.estado_actual,
                    "target_no_show": int(c.target_no_show),
                }
                for c in filas_bd[:1000]
            ]

    generadas = generar_citas(
        historicas=1000,
        proximas=0,
        semilla=SEMILLA_OFICIAL,
        con_invalidas=False,
    )
    return [r for r in generadas if r.get("target_no_show") is not None]


def entrenar_y_serializar_modelo(
    db: Session | None = None,
    ruta_salida: Path = RUTA_ARTEFACTO,
) -> dict[str, Any]:
    """Entrena Baseline (LogisticRegression) y LightGBM sobre las 1,000 citas históricas (70/15/15) y guarda .joblib."""
    registros = cargar_citas_historicas(db)
    if len(registros) < 1000:
        raise ValueError(f"Se requieren al menos 1,000 citas históricas acreditadas; se encontraron {len(registros)}.")

    X_all, _ = _construir_matriz(registros)
    y_all = np.array([int(r["target_no_show"]) for r in registros], dtype=int)
    indices = np.arange(len(registros))

    # Partición estratificada 70% Train (700) / 30% Temp (300) -> 15% Val (150) y 15% Test (150)
    idx_train, idx_temp, y_train, y_temp = train_test_split(
        indices,
        y_all,
        test_size=0.30,
        stratify=y_all,
        random_state=SEMILLA_OFICIAL,
    )
    idx_val, idx_test, y_val, y_test = train_test_split(
        idx_temp,
        y_temp,
        test_size=0.50,
        stratify=y_temp,
        random_state=SEMILLA_OFICIAL,
    )

    X_train, X_val, X_test = X_all[idx_train], X_all[idx_val], X_all[idx_test]
    registros_test = [registros[i] for i in idx_test]

    # 1. Prueba verificable de ausencia de Data Leakage (RF-048)
    reporte_leakage = verificar_sin_data_leakage(registros, idx_train, idx_val, idx_test)

    # 2. Entrenamiento del Modelo Baseline (LogisticRegression — RF-041)
    pipeline_baseline = Pipeline([
        ("prep", _crear_preprocesador()),
        (
            "clf",
            LogisticRegression(
                C=0.05,
                max_iter=1000,
                random_state=SEMILLA_OFICIAL,
            ),
        ),
    ])
    pipeline_baseline.fit(X_train, y_train)

    # 3. Entrenamiento del Modelo Principal (LightGBM — RF-042)
    pipeline_lgbm = Pipeline([
        ("prep", _crear_preprocesador()),
        (
            "clf",
            LGBMClassifier(
                objective="binary",
                n_estimators=220,
                learning_rate=0.045,
                num_leaves=23,
                max_depth=5,
                min_child_samples=12,
                subsample=0.85,
                colsample_bytree=0.85,
                class_weight="balanced",
                random_state=SEMILLA_OFICIAL,
                verbose=-1,
            ),
        ),
    ])
    pipeline_lgbm.fit(X_train, y_train)

    # 4. Evaluación en Validación (150 filas) y Prueba Reservada (150 filas) con umbral 0.450
    probs_val_lgbm = pipeline_lgbm.predict_proba(X_val)[:, 1]
    probs_test_lgbm = pipeline_lgbm.predict_proba(X_test)[:, 1]
    probs_test_base = pipeline_baseline.predict_proba(X_test)[:, 1]

    metricas_val = _calcular_metricas(y_val, probs_val_lgbm, UMBRAL_ALTO)
    metricas_test = _calcular_metricas(y_test, probs_test_lgbm, UMBRAL_ALTO)
    metricas_baseline_test = _calcular_metricas(y_test, probs_test_base, UMBRAL_ALTO)

    if metricas_test["f1_score"] < 0.82:
        raise RuntimeError(
            f"El modelo LightGBM no alcanzó la meta F1-Score >= 0.82 en Test (obtenido: {metricas_test['f1_score']:.4f})."
        )

    # 5. Auditoría de Equidad y Sesgo por Subgrupos (RF-049 / RNF-024)
    equidad = _auditar_equidad_subgrupos(registros_test, y_test, probs_test_lgbm, UMBRAL_ALTO)

    # 6. Importancia global de variables
    clf_lgbm: LGBMClassifier = pipeline_lgbm.named_steps["clf"]
    importancias_raw = clf_lgbm.feature_importances_
    importancia_agrupada = [
        {"variable": "inasistencias_previas / tasa_previa", "importancia": int(importancias_raw[1] + importancias_raw[4])},
        {"variable": "antelacion_dias", "importancia": int(importancias_raw[0] + importancias_raw[5])},
        {"variable": "reprogramaciones_prev", "importancia": int(importancias_raw[3])},
        {"variable": "asistencias_previas", "importancia": int(importancias_raw[2])},
        {"variable": "tipo_paciente", "importancia": int(np.sum(importancias_raw[9:11]))},
        {"variable": "canal_origen", "importancia": int(np.sum(importancias_raw[11:14]))},
        {"variable": "franja_horaria", "importancia": int(np.sum(importancias_raw[14:16]))},
        {"variable": "especialidad", "importancia": int(np.sum(importancias_raw[6:9]))},
        {"variable": "dia_semana", "importancia": int(np.sum(importancias_raw[16:22]))},
    ]
    importancia_agrupada.sort(key=lambda x: x["importancia"], reverse=True)

    artefacto = {
        "version_modelo": VERSION_MODELO,
        "algoritmo": "LGBMClassifier",
        "semilla": SEMILLA_OFICIAL,
        "fecha_entrenamiento": datetime.now(timezone.utc).isoformat(),
        "es_simulacion": True,
        "rotulo_etico": "Resultado simulado — Dataset sintético acreditado (RF-056 / RN16)",
        "umbral_alto": UMBRAL_ALTO,
        "umbral_medio": UMBRAL_MEDIO,
        "features_entrada": FEATURES_ENTRADA_MODELO,
        "pipeline": pipeline_lgbm,
        "pipeline_baseline": pipeline_baseline,
        "dataset_info": {
            "version_dataset": VERSION_DATASET,
            "semilla": SEMILLA_OFICIAL,
            "total_historicas": len(registros),
            "train_size": int(len(idx_train)),
            "val_size": int(len(idx_val)),
            "test_size": int(len(idx_test)),
            "tasa_no_show_global": round(float(y_all.mean()), 4),
            "tasa_no_show_train": round(float(y_train.mean()), 4),
            "tasa_no_show_val": round(float(y_val.mean()), 4),
            "tasa_no_show_test": round(float(y_test.mean()), 4),
            "control_leakage": reporte_leakage,
        },
        "metricas_val": metricas_val,
        "metricas_test": metricas_test,
        "metricas_baseline_test": metricas_baseline_test,
        "auditoria_equidad": equidad,
        "importancia_global_variables": importancia_agrupada,
    }

    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artefacto, ruta_salida)

    global _CACHE_MODELO
    _CACHE_MODELO = artefacto
    return artefacto


def obtener_artefacto_modelo() -> dict[str, Any]:
    """Carga en memoria el artefacto .joblib (o lo entrena y serializa si aún no existe en disco)."""
    global _CACHE_MODELO
    if _CACHE_MODELO is not None:
        return _CACHE_MODELO
    if not RUTA_ARTEFACTO.exists():
        return entrenar_y_serializar_modelo()
    _CACHE_MODELO = joblib.load(RUTA_ARTEFACTO)
    return _CACHE_MODELO


def predecir_cita_dict(fila_cita: dict[str, Any]) -> dict[str, Any]:
    """Ejecuta la inferencia sobre los datos pre-cita y devuelve score, nivel, snapshot y explicabilidad."""
    artefacto = obtener_artefacto_modelo()
    pipeline_lgbm: Pipeline = artefacto["pipeline"]

    X_mat, filas_enriq = _construir_matriz([fila_cita])
    prob_raw = float(pipeline_lgbm.predict_proba(X_mat)[0, 1])
    prob_redondeada = round(max(0.0, min(1.0, prob_raw)), 3)
    nivel = clasificar_nivel_riesgo(prob_redondeada)
    resumen = explicar_prediccion(pipeline_lgbm, fila_cita, prob_redondeada)

    return {
        "version_modelo": artefacto["version_modelo"],
        "probabilidad_no_show": Decimal(f"{prob_redondeada:.3f}"),
        "nivel_riesgo": nivel,
        "umbral_aplicado": Decimal(f"{artefacto['umbral_alto']:.3f}"),
        "features_snapshot": filas_enriq[0],
        "explicabilidad_resumen": resumen,
    }


if __name__ == "__main__":
    resultado = entrenar_y_serializar_modelo()
    ds = resultado["dataset_info"]
    m_test = resultado["metricas_test"]
    m_base = resultado["metricas_baseline_test"]
    print("=" * 72)
    print(f"ENTRENAMIENTO Y SERIALIZACIÓN COMPLETADOS — {resultado['version_modelo']}")
    print("=" * 72)
    print(f"Artefacto guardado en : {RUTA_ARTEFACTO}")
    print(
        f"Dataset ({ds['version_dataset']}) : {ds['total_historicas']} históricas "
        f"(Train={ds['train_size']}, Val={ds['val_size']}, Test={ds['test_size']})"
    )
    print(f"Tasa No-Show Global   : {ds['tasa_no_show_global'] * 100:.2f}% (rango objetivo 18%–22%)")
    print(f"Control Anti-Leakage  : APROBADO ({ds['control_leakage']['aprobado']})")
    print("-" * 72)
    print("MÉTRICAS EN CONJUNTO DE PRUEBA RESERVADO (TEST = 150 CITAS, UMBRAL = 0.450):")
    print(
        f"  LightGBM (Principal): F1={m_test['f1_score'] * 100:.2f}% | "
        f"Precision={m_test['precision'] * 100:.2f}% | Recall={m_test['recall'] * 100:.2f}% | "
        f"ROC-AUC={m_test['roc_auc']:.4f} | PR-AUC={m_test['pr_auc']:.4f}"
    )
    print(
        f"  Baseline (LogReg)   : F1={m_base['f1_score'] * 100:.2f}% | "
        f"Precision={m_base['precision'] * 100:.2f}% | Recall={m_base['recall'] * 100:.2f}% | "
        f"ROC-AUC={m_base['roc_auc']:.4f} | PR-AUC={m_base['pr_auc']:.4f}"
    )
    print(f"  Matriz Confusión LGBM: {m_test['matriz_confusion']}")
    print("=" * 72)
