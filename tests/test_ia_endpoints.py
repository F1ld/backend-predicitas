from sqlalchemy import select

from app.modules.auditoria.models import AuditoriaEvento
from app.modules.citas.importer import importar_citas
from app.modules.citas.models import Cita
from app.modules.ia.models import PrediccionIA
from tests.conftest import cabecera

CITAS_PRUEBA_IA = [
    {
        "id_cita_externa": "CIT-IA-ALTO-001",
        "paciente_anon_id": "PAC-IA-0001",
        "sede": "SAN_ISIDRO",
        "especialidad": "TRAUMATOLOGIA",
        "medico": "Dr. Salcedo",
        "fecha_hora_cita": "2026-11-06T16:30:00-05:00",
        "fecha_registro_cita": "2026-10-05T10:00:00-05:00",
        "tipo_paciente": "CONTINUADOR",
        "canal_origen": "CALL_CENTER",
        "inasistencias_previas": 3,
        "reprogramaciones_prev": 2,
        "asistencias_previas": 1,
        "estado_actual": "RECIBIDA",
    },
    {
        "id_cita_externa": "CIT-IA-BAJO-002",
        "paciente_anon_id": "PAC-IA-0002",
        "sede": "SAN_ISIDRO",
        "especialidad": "CARDIOLOGIA",
        "medico": "Dr. Ramírez",
        "fecha_hora_cita": "2026-11-02T09:00:00-05:00",
        "fecha_registro_cita": "2026-10-30T11:00:00-05:00",
        "tipo_paciente": "CONTINUADOR",
        "canal_origen": "PRESENCIAL",
        "inasistencias_previas": 0,
        "reprogramaciones_prev": 0,
        "asistencias_previas": 6,
        "estado_actual": "RECIBIDA",
    },
]


def test_predecir_cita_individual_persiste_y_audita(client, usuarios, db):
    importar_citas(db, CITAS_PRUEBA_IA, id_usuario=usuarios["ADMINISTRADOR"].id_usuario, ip="127.0.0.1", origen="test_ia")
    cita = db.scalar(select(Cita).where(Cita.id_cita_externa == "CIT-IA-ALTO-001"))
    h = cabecera(client, usuarios["RECEPCION"])

    r = client.post(f"/ia/predecir/{cita.id_cita}", headers=h)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["id_cita"] == cita.id_cita
    assert cuerpo["version_modelo"] == "LightGBM_v1.0.0"
    assert float(cuerpo["probabilidad_no_show"]) > 0.450
    assert cuerpo["nivel_riesgo"] == "ALTO"
    assert float(cuerpo["umbral_aplicado"]) == 0.450
    assert "1)" in cuerpo["explicabilidad_resumen"] and "2)" in cuerpo["explicabilidad_resumen"] and "3)" in cuerpo["explicabilidad_resumen"]

    # Verificar persistencia en predicciones_ia y auditoria_eventos
    pred_bd = db.scalar(select(PrediccionIA).where(PrediccionIA.id_cita == cita.id_cita))
    assert pred_bd is not None and pred_bd.nivel_riesgo == "ALTO"

    ev = db.scalar(
        select(AuditoriaEvento).where(
            AuditoriaEvento.modulo == "IA",
            AuditoriaEvento.accion == "PREDICT",
            AuditoriaEvento.id_entidad == pred_bd.id_prediccion,
        )
    )
    assert ev is not None


def test_predecir_lote_evalua_citas_pendientes(client, usuarios, db):
    importar_citas(db, CITAS_PRUEBA_IA, id_usuario=usuarios["ADMINISTRADOR"].id_usuario, ip="127.0.0.1", origen="test_lote")
    h = cabecera(client, usuarios["TECNICO_IA"])

    r = client.post("/ia/predecir-lote?forzar=true", headers=h)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["evaluadas"] >= 2
    assert (cuerpo["riesgo_alto"] + cuerpo["riesgo_medio"] + cuerpo["riesgo_bajo"]) == cuerpo["evaluadas"]


def test_metricas_y_dataset_resumen_cumplen_entregables_e04_e05(client, usuarios):
    h = cabecera(client, usuarios["TECNICO_IA"])

    r_met = client.get("/ia/metricas", headers=h)
    assert r_met.status_code == 200, r_met.text
    met = r_met.json()
    assert met["cumple_meta_f1_82"] is True
    assert met["metricas_test"]["f1_score"] >= 0.82
    assert met["metricas_test"]["f1_score"] > met["metricas_baseline_test"]["f1_score"]

    r_ds = client.get("/ia/dataset-resumen", headers=h)
    assert r_ds.status_code == 200, r_ds.text
    ds = r_ds.json()
    assert ds["total_historicas"] == 1000
    assert (ds["train_size"], ds["val_size"], ds["test_size"]) == (700, 150, 150)
    assert 0.18 <= ds["tasa_no_show_global"] <= 0.22
    assert ds["control_leakage"]["aprobado"] is True

