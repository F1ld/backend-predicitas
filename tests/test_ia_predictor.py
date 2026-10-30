from decimal import Decimal

from app.modules.citas.synthetic import generar_citas
from app.modules.ia.predictor import (
    RUTA_ARTEFACTO,
    entrenar_y_serializar_modelo,
    obtener_artefacto_modelo,
    predecir_cita_dict,
)


def test_generador_1000_historicas_y_80_proximas_coherentes():
    citas = generar_citas(historicas=1000, proximas=80, semilla=42, con_invalidas=False)
    assert len(citas) == 1080

    historicas = [c for c in citas if c["target_no_show"] is not None]
    proximas = [c for c in citas if c["target_no_show"] is None]
    assert len(historicas) == 1000
    assert len(proximas) == 80

    # Tasa basal de no-show entre 18% y 22%
    tasa_no_show = sum(c["target_no_show"] for c in historicas) / len(historicas)
    assert 0.18 <= tasa_no_show <= 0.22

    # Coherencia clínica de variables basales
    for c in citas:
        assert c["sede"] == "SAN_ISIDRO"
        assert c["especialidad"] in ("CARDIOLOGIA", "TRAUMATOLOGIA", "PEDIATRIA")
        assert 0 <= c["antelacion_dias"] <= 60
        assert c["id_cita_externa"].startswith("CIT-SIM-")
        assert c["paciente_anon_id"].startswith("PAC-SIM-")
        if c["tipo_paciente"] == "NUEVO":
            assert c["inasistencias_previas"] == 0 and c["asistencias_previas"] == 0

    for p in proximas:
        assert p["estado_actual"] == "RECIBIDA"
        assert p["target_no_show"] is None


def test_entrenamiento_lightgbm_cumple_meta_f1_y_explicabilidad():
    artefacto = obtener_artefacto_modelo() if RUTA_ARTEFACTO.exists() else entrenar_y_serializar_modelo()
    assert RUTA_ARTEFACTO.exists()

    ds = artefacto["dataset_info"]
    assert (ds["total_historicas"], ds["train_size"], ds["val_size"], ds["test_size"]) == (1000, 700, 150, 150)
    assert ds["control_leakage"]["aprobado"] is True

    m_test = artefacto["metricas_test"]
    m_base = artefacto["metricas_baseline_test"]
    assert m_test["f1_score"] >= 0.82
    assert m_test["f1_score"] > m_base["f1_score"]

    # Prueba de inferencia individual y explicabilidad con 3 factores
    cita_alto_riesgo = {
        "especialidad": "TRAUMATOLOGIA",
        "tipo_paciente": "CONTINUADOR",
        "canal_origen": "CALL_CENTER",
        "franja_horaria": "TARDE",
        "dia_semana": "VIERNES",
        "antelacion_dias": 32,
        "inasistencias_previas": 3,
        "asistencias_previas": 1,
        "reprogramaciones_prev": 2,
    }
    pred = predecir_cita_dict(cita_alto_riesgo)
    assert Decimal("0.000") <= pred["probabilidad_no_show"] <= Decimal("1.000")
    assert pred["nivel_riesgo"] == "ALTO"
    assert pred["umbral_aplicado"] == Decimal("0.450")
    assert "1)" in pred["explicabilidad_resumen"] and "2)" in pred["explicabilidad_resumen"] and "3)" in pred["explicabilidad_resumen"]
    assert len(pred["explicabilidad_resumen"]) <= 255

