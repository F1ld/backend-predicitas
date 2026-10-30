from sqlalchemy.orm import Session

from app.core.errores import Conflicto, NoEncontrado
from app.modules.auditoria.service import registrar_evento
from app.modules.auth.models import Usuario
from app.modules.citas.models import Cita
from app.modules.ia import repository
from app.modules.ia.predictor import (
    FEATURES_ENTRADA_MODELO,
    obtener_artefacto_modelo,
    predecir_cita_dict,
)
from app.modules.ia.schemas import (
    DatasetResumenOut,
    MetricasModeloOut,
    PrediccionIAOut,
    ResultadoPrediccionLoteOut,
)

ESTADOS_ELEGIBLES_PREDICCION = {"RECIBIDA", "CONFIRMADA", "REPROGRAMADA"}


def _cita_a_dict_features(cita: Cita) -> dict:
    return {
        "especialidad": cita.especialidad,
        "tipo_paciente": cita.tipo_paciente,
        "canal_origen": cita.canal_origen,
        "franja_horaria": cita.franja_horaria,
        "dia_semana": cita.dia_semana,
        "antelacion_dias": cita.antelacion_dias,
        "inasistencias_previas": cita.inasistencias_previas,
        "asistencias_previas": cita.asistencias_previas,
        "reprogramaciones_prev": cita.reprogramaciones_prev,
    }


def predecir_cita(
    db: Session,
    id_cita: int,
    *,
    usuario: Usuario,
    ip: str,
) -> PrediccionIAOut:
    cita = db.get(Cita, id_cita)
    if cita is None:
        raise NoEncontrado(f"No existe la cita {id_cita}")
    if cita.estado_actual not in ESTADOS_ELEGIBLES_PREDICCION:
        raise Conflicto(
            f"La cita {id_cita} se encuentra en estado final '{cita.estado_actual}' y no admite inferencia operativa"
        )

    resultado_ia = predecir_cita_dict(_cita_a_dict_features(cita))
    prediccion, antes = repository.guardar_o_actualizar_prediccion(
        db,
        id_cita=cita.id_cita,
        version_modelo=resultado_ia["version_modelo"],
        probabilidad_no_show=resultado_ia["probabilidad_no_show"],
        nivel_riesgo=resultado_ia["nivel_riesgo"],
        umbral_aplicado=resultado_ia["umbral_aplicado"],
        features_snapshot=resultado_ia["features_snapshot"],
        explicabilidad_resumen=resultado_ia["explicabilidad_resumen"],
    )

    registrar_evento(
        db,
        modulo="IA",
        accion="PREDICT",
        entidad_afectada="predicciones_ia",
        direccion_ip=ip,
        id_usuario=usuario.id_usuario,
        id_entidad=prediccion.id_prediccion,
        datos_before=antes,
        datos_after={
            "id_cita": cita.id_cita,
            "version_modelo": prediccion.version_modelo,
            "probabilidad_no_show": float(prediccion.probabilidad_no_show),
            "nivel_riesgo": prediccion.nivel_riesgo,
            "umbral_aplicado": float(prediccion.umbral_aplicado),
            "explicabilidad_resumen": prediccion.explicabilidad_resumen,
        },
    )
    db.commit()
    db.refresh(prediccion)
    return PrediccionIAOut.model_validate(prediccion)


def predecir_lote(
    db: Session,
    *,
    forzar: bool = False,
    usuario: Usuario,
    ip: str,
) -> ResultadoPrediccionLoteOut:
    artefacto = obtener_artefacto_modelo()
    version_modelo = artefacto["version_modelo"]
    citas = repository.citas_operativas_sin_prediccion(db, version_modelo, forzar=forzar)

    predicciones_out: list[PrediccionIAOut] = []
    conteo = {"ALTO": 0, "MEDIO": 0, "BAJO": 0}

    for cita in citas:
        resultado_ia = predecir_cita_dict(_cita_a_dict_features(cita))
        pred, _ = repository.guardar_o_actualizar_prediccion(
            db,
            id_cita=cita.id_cita,
            version_modelo=version_modelo,
            probabilidad_no_show=resultado_ia["probabilidad_no_show"],
            nivel_riesgo=resultado_ia["nivel_riesgo"],
            umbral_aplicado=resultado_ia["umbral_aplicado"],
            features_snapshot=resultado_ia["features_snapshot"],
            explicabilidad_resumen=resultado_ia["explicabilidad_resumen"],
        )
        conteo[pred.nivel_riesgo] = conteo.get(pred.nivel_riesgo, 0) + 1
        predicciones_out.append(PrediccionIAOut.model_validate(pred))

    registrar_evento(
        db,
        modulo="IA",
        accion="PREDICT",
        entidad_afectada="predicciones_ia",
        direccion_ip=ip,
        id_usuario=usuario.id_usuario,
        datos_after={
            "operacion": "PREDICT_LOTE",
            "version_modelo": version_modelo,
            "evaluadas": len(predicciones_out),
            "riesgo_alto": conteo["ALTO"],
            "riesgo_medio": conteo["MEDIO"],
            "riesgo_bajo": conteo["BAJO"],
        },
    )
    db.commit()
    return ResultadoPrediccionLoteOut(
        version_modelo=version_modelo,
        evaluadas=len(predicciones_out),
        riesgo_alto=conteo["ALTO"],
        riesgo_medio=conteo["MEDIO"],
        riesgo_bajo=conteo["BAJO"],
        predicciones=predicciones_out,
    )


def obtener_metricas_modelo() -> MetricasModeloOut:
    artefacto = obtener_artefacto_modelo()
    m_test = artefacto["metricas_test"]
    return MetricasModeloOut(
        version_modelo=artefacto["version_modelo"],
        algoritmo=artefacto["algoritmo"],
        semilla=artefacto["semilla"],
        fecha_entrenamiento=artefacto["fecha_entrenamiento"],
        es_simulacion=artefacto["es_simulacion"],
        rotulo_etico=artefacto["rotulo_etico"],
        umbral_alto=artefacto["umbral_alto"],
        umbral_medio=artefacto["umbral_medio"],
        cumple_meta_f1_82=bool(m_test["f1_score"] >= 0.82),
        metricas_test=m_test,
        metricas_val=artefacto["metricas_val"],
        metricas_baseline_test=artefacto["metricas_baseline_test"],
        auditoria_equidad=artefacto["auditoria_equidad"],
        importancia_global_variables=artefacto["importancia_global_variables"],
    )


def obtener_dataset_resumen(db: Session) -> DatasetResumenOut:
    artefacto = obtener_artefacto_modelo()
    ds = artefacto["dataset_info"]
    conteos_bd = repository.conteos_dataset_bd(db)

    total_hist = ds["total_historicas"]
    no_show_est = round(total_hist * ds["tasa_no_show_global"])
    atendidas_est = total_hist - no_show_est

    return DatasetResumenOut(
        version_dataset=ds["version_dataset"],
        semilla=ds["semilla"],
        total_historicas=total_hist,
        atendidas_historicas=conteos_bd["atendidas_bd"] or atendidas_est,
        no_show_historicas=conteos_bd["no_show_bd"] or no_show_est,
        proximas_operativas_bd=conteos_bd["proximas_bd"],
        train_size=ds["train_size"],
        val_size=ds["val_size"],
        test_size=ds["test_size"],
        tasa_no_show_global=ds["tasa_no_show_global"],
        tasa_no_show_train=ds["tasa_no_show_train"],
        tasa_no_show_val=ds["tasa_no_show_val"],
        tasa_no_show_test=ds["tasa_no_show_test"],
        features_autorizadas=list(FEATURES_ENTRADA_MODELO),
        control_leakage=ds["control_leakage"],
        rotulo_etico=artefacto["rotulo_etico"],
    )

