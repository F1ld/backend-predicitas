"""Endpoints M09-E01 a M09-E04 (contratos/modulo-09.json · F-08 · CP-M09-01 a -05 y -07)."""
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.main import app
from app.modules.auditoria.models import AuditoriaEvento
from app.modules.citas.models import Cita
from app.modules.ia import service
from app.modules.ia.models import PrediccionIA
from app.modules.ia.router import reloj_ia
from tests.citas.conftest import HOY, crear_cita, crear_prediccion
from tests.conftest import cabecera

VARIABLES_AUTORIZADAS = {"especialidad", "tipo_paciente", "antelacion_dias", "canal_origen", "franja_horaria",
                         "dia_semana", "inasistencias_previas", "reprogramaciones_prev", "asistencias_previas",
                         "confirmada"}


def _codigo(r):
    return r.json()["error"]["codigo"]


def _predicciones(db, cita):
    return db.scalar(select(func.count()).select_from(PrediccionIA).where(PrediccionIA.id_cita == cita.id_cita))


def _eventos_predict(db):
    return list(db.scalars(select(AuditoriaEvento).where(AuditoriaEvento.accion == "PREDICT")
                           .order_by(AuditoriaEvento.id_log)))


def _foto_cita(cita: Cita) -> dict:
    return {c.name: getattr(cita, c.name) for c in Cita.__table__.columns}


# ---------- M09-E01 ----------

def test_predice_guarda_trazabilidad_y_audita(api_ia, usuarios, db):
    cita = crear_cita(db)
    r = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=cabecera(api_ia, usuarios["RECEPCION"]))
    assert r.status_code == 201, r.text
    p = r.json()
    assert set(p) == {"id_prediccion", "id_cita", "version_modelo", "probabilidad_no_show", "nivel_riesgo",
                      "umbral_aplicado", "features_snapshot", "explicabilidad_resumen",
                      "fecha_hora_inferencia", "resultado_simulado", "ya_existia"}
    assert p["version_modelo"] == "SIM_TEST_v1" and p["probabilidad_no_show"] == 0.512
    assert p["umbral_aplicado"] == 0.45 and p["nivel_riesgo"] == "ALTO"
    assert p["resultado_simulado"] is True and p["ya_existia"] is False
    assert p["explicabilidad_resumen"] == "Antelación alta" and p["fecha_hora_inferencia"]

    fila = db.get(PrediccionIA, p["id_prediccion"])  # RNF-010: todo queda guardado
    assert (fila.version_modelo, fila.probabilidad_no_show, fila.nivel_riesgo, fila.umbral_aplicado) == \
        ("SIM_TEST_v1", Decimal("0.512"), "ALTO", Decimal("0.450"))
    evento = _eventos_predict(db)[-1]
    assert evento.modulo == "IA" and evento.id_entidad == fila.id_prediccion
    assert evento.datos_after == {"resultado": "EXITOSO", "id_cita": cita.id_cita, "version_modelo": "SIM_TEST_v1",
                                  "probabilidad_no_show": 0.512, "nivel_riesgo": "ALTO"}


def test_snapshot_sin_target_ni_datos_posteriores(api_ia, usuarios, db, servicio):
    """RN17 / RNF-023: el snapshot y lo enviado al servicio son exactamente las variables de §4.2."""
    cita = crear_cita(db, estado_actual="CONFIRMADA", inasistencias_previas=2, asistencias_previas=1)
    r = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=cabecera(api_ia, usuarios["ADMINISTRADOR"]))
    snapshot = r.json()["features_snapshot"]
    assert set(snapshot) == VARIABLES_AUTORIZADAS
    assert set(servicio.peticiones[0]["variables"]) == VARIABLES_AUTORIZADAS
    prohibidas = {"target_no_show", "estado_actual", "check_in", "fecha_hora_cita", "paciente_anon_id",
                  "id_cita_externa", "medico"}
    assert not prohibidas & set(snapshot)
    assert snapshot["confirmada"] is True and snapshot["inasistencias_previas"] == 2
    assert snapshot["antelacion_dias"] == cita.antelacion_dias
    # El modelo ORM tampoco lo filtra por accidente: construir_snapshot solo lee las 10 variables.
    assert set(service.construir_snapshot(cita)) == set(service.VARIABLES_SNAPSHOT) == VARIABLES_AUTORIZADAS


def test_dos_peticiones_misma_version_devuelven_la_existente(api_ia, usuarios, db, servicio):
    cita = crear_cita(db)
    h = cabecera(api_ia, usuarios["TECNICO_IA"])
    r1 = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=h)
    r2 = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=h)
    assert (r1.status_code, r2.status_code) == (201, 200)
    assert r2.json()["ya_existia"] is True and r2.json()["id_prediccion"] == r1.json()["id_prediccion"]
    assert _predicciones(db, cita) == 1
    assert len(servicio.peticiones) == 1  # no se vuelve a inferir
    # Otra versión del modelo sí crea una predicción nueva.
    servicio.version = "SIM_TEST_v2"
    assert api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=h).status_code == 201
    assert _predicciones(db, cita) == 2


@pytest.mark.parametrize("fallo", ["conexion", "timeout", 503])
def test_servicio_caido_da_503_audita_y_no_toca_la_cita(api_ia, usuarios, db, servicio, fallo):
    cita = crear_cita(db)
    antes = _foto_cita(cita)
    servicio.fallar_prediccion = fallo
    r = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=cabecera(api_ia, usuarios["RECEPCION"]))
    assert r.status_code == 503 and _codigo(r) == "MOTOR_IA_NO_DISPONIBLE"
    db.expire_all()
    assert _foto_cita(db.get(Cita, cita.id_cita)) == antes
    assert _predicciones(db, cita) == 0
    evento = _eventos_predict(db)[-1]
    assert evento.datos_after == {"resultado": "FALLIDO", "motivo": "MOTOR_IA_NO_DISPONIBLE"}
    assert evento.entidad_afectada == "citas" and evento.id_entidad == cita.id_cita


def test_fallo_al_consultar_el_modelo_tambien_es_503_auditado(api_ia, usuarios, db, servicio):
    cita = crear_cita(db)
    servicio.fallar_modelo = 500
    r = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=cabecera(api_ia, usuarios["RECEPCION"]))
    assert r.status_code == 503 and _eventos_predict(db)[-1].datos_after["resultado"] == "FALLIDO"


def test_version_distinta_entre_llamadas_es_503(api_ia, usuarios, db, servicio):
    cita = crear_cita(db)
    servicio.version_prediccion = "OTRA_v9"
    r = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=cabecera(api_ia, usuarios["RECEPCION"]))
    assert r.status_code == 503 and _predicciones(db, cita) == 0


def test_modelo_no_habilitado_da_409(api_ia, usuarios, db, servicio):
    cita = crear_cita(db)
    servicio.habilitado = False
    r = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=cabecera(api_ia, usuarios["RECEPCION"]))
    assert r.status_code == 409 and _codigo(r) == "MODELO_NO_HABILITADO"
    assert servicio.peticiones == [] and _predicciones(db, cita) == 0


@pytest.mark.parametrize("cambios", [
    {"estado_actual": "CANCELADA"},
    {"fecha_hora_cita": "2026-10-23T09:00:00-05:00", "fecha_registro_cita": "2026-10-10T10:00:00-05:00"},
])
def test_cita_no_elegible_da_409(api_ia, usuarios, db, servicio, cambios):
    cita = crear_cita(db, **cambios)
    r = api_ia.post(f"/citas/{cita.id_cita}/prediccion", headers=cabecera(api_ia, usuarios["RECEPCION"]))
    assert r.status_code == 409 and _codigo(r) == "CITA_NO_ELEGIBLE"
    assert servicio.peticiones == []


def test_cita_inexistente_da_404(api_ia, usuarios):
    r = api_ia.post("/citas/999999999/prediccion", headers=cabecera(api_ia, usuarios["RECEPCION"]))
    assert r.status_code == 404 and _codigo(r) == "NO_ENCONTRADO"


def test_sin_token_401(api_ia):
    assert api_ia.post("/citas/1/prediccion").status_code == 401


@pytest.mark.parametrize("prob,nivel", [("0.451", "ALTO"), ("0.450", "MEDIO"), ("0.300", "MEDIO"),
                                        ("0.299", "BAJO")])
def test_clasificacion_segun_umbral_y_corte(prob, nivel):
    assert service.clasificar(Decimal(prob), Decimal("0.450"), Decimal("0.300")) == nivel


# ---------- M09-E02 ----------

def test_lote_con_fallo_parcial(api_ia, usuarios, db, servicio):
    nueva = crear_cita(db, id_cita_externa="CIT-L-1", fecha_hora_cita="2026-10-26T09:00:00-05:00")
    existente = crear_cita(db, id_cita_externa="CIT-L-2", fecha_hora_cita="2026-10-27T09:00:00-05:00")
    falla = crear_cita(db, id_cita_externa="CIT-L-3", fecha_hora_cita="2026-10-28T15:00:00-05:00")
    crear_cita(db, id_cita_externa="CIT-L-4", fecha_hora_cita="2026-10-29T09:00:00-05:00", estado_actual="CANCELADA")
    crear_cita(db, id_cita_externa="CIT-L-5", fecha_hora_cita="2026-11-20T09:00:00-05:00")  # fuera de rango
    crear_cita(db, id_cita_externa="CIT-L-6", fecha_hora_cita="2026-10-26T10:00:00-05:00", especialidad="PEDIATRIA")
    crear_prediccion(db, existente, "BAJO", "0.100", version="SIM_TEST_v1")
    servicio.fallar_ids = {falla.id_cita}

    r = api_ia.post("/predicciones/lote", headers=cabecera(api_ia, usuarios["ADMINISTRADOR"]),
                    json={"desde": "2026-10-26", "hasta": "2026-10-30", "especialidad": "CARDIOLOGIA"})
    assert r.status_code == 200, r.text
    assert r.json() == {"evaluadas": 4, "nuevas": 1, "existentes": 1, "no_elegibles": 1, "fallidas": 1,
                        "detalle_fallas": [{"id_cita": falla.id_cita, "codigo": "MOTOR_IA_NO_DISPONIBLE"}],
                        "version_modelo": "SIM_TEST_v1", "resultado_simulado": True}
    # el fallo no deshizo la predicción nueva, y quedó auditado
    assert _predicciones(db, nueva) == 1 and _predicciones(db, falla) == 0
    fallidos = [e for e in _eventos_predict(db) if e.datos_after["resultado"] == "FALLIDO"]
    assert [e.id_entidad for e in fallidos] == [falla.id_cita]


def test_lote_sin_especialidad_incluye_todas(api_ia, usuarios, db):
    crear_cita(db, id_cita_externa="CIT-L-7", fecha_hora_cita="2026-10-26T09:00:00-05:00")
    crear_cita(db, id_cita_externa="CIT-L-8", fecha_hora_cita="2026-10-26T10:00:00-05:00", especialidad="PEDIATRIA")
    r = api_ia.post("/predicciones/lote", headers=cabecera(api_ia, usuarios["RECEPCION"]),
                    json={"desde": "2026-10-26", "hasta": "2026-10-26"})
    assert r.json()["nuevas"] == 2


@pytest.mark.parametrize("cuerpo,campo", [
    ({"desde": "2026-10-26", "hasta": "2026-11-10"}, "hasta"),
    ({"desde": "2026-10-26", "hasta": "2026-10-25"}, "hasta"),
    ({"hasta": "2026-10-26"}, "desde"),
    ({"desde": "2026-10-26", "hasta": "2026-10-27", "especialidad": "DERMATOLOGIA"}, "especialidad"),
])
def test_lote_validacion_422(api_ia, usuarios, cuerpo, campo):
    r = api_ia.post("/predicciones/lote", headers=cabecera(api_ia, usuarios["RECEPCION"]), json=cuerpo)
    assert r.status_code == 422 and campo in r.json()["error"]["campos"]


def test_lote_modelo_no_habilitado_409_y_caido_503(api_ia, usuarios, servicio):
    h = cabecera(api_ia, usuarios["RECEPCION"])
    cuerpo = {"desde": "2026-10-26", "hasta": "2026-10-27"}
    servicio.habilitado = False
    assert _codigo(api_ia.post("/predicciones/lote", headers=h, json=cuerpo)) == "MODELO_NO_HABILITADO"
    servicio.fallar_modelo = "conexion"
    r = api_ia.post("/predicciones/lote", headers=h, json=cuerpo)
    assert r.status_code == 503 and _codigo(r) == "MOTOR_IA_NO_DISPONIBLE"


def test_lote_limita_detalle_de_fallas_a_50(api_ia, usuarios, db, servicio):
    servicio.fallar_prediccion = "conexion"
    for i in range(52):
        crear_cita(db, id_cita_externa=f"CIT-F-{i:03d}", fecha_hora_cita="2026-10-26T09:00:00-05:00")
    r = api_ia.post("/predicciones/lote", headers=cabecera(api_ia, usuarios["RECEPCION"]),
                    json={"desde": "2026-10-26", "hasta": "2026-10-26"})
    assert r.json()["fallidas"] == 52 and len(r.json()["detalle_fallas"]) == 50


# ---------- M09-E03 ----------

def test_modelo_activo_disponible_y_no_disponible(api_ia, usuarios, servicio):
    h = cabecera(api_ia, usuarios["RECEPCION"])
    r = api_ia.get("/predicciones/modelo", headers=h)
    assert r.status_code == 200
    m = r.json()
    assert m["disponible"] is True and m["version_modelo"] == "SIM_TEST_v1" and m["umbral"] == 0.45
    assert m["habilitado_piloto"] is True and m["corte_medio"] == 0.30 and isinstance(m["latencia_ms"], int)
    servicio.fallar_modelo = "timeout"
    r = api_ia.get("/predicciones/modelo", headers=h)
    assert r.status_code == 200
    assert r.json()["disponible"] is False and r.json()["latencia_ms"] is None and r.json()["version_modelo"] is None


# ---------- M09-E04 ----------

def test_listar_predicciones_filtra_y_ordena(api_ia, usuarios, db):
    c1 = crear_cita(db, id_cita_externa="CIT-P-1")
    c2 = crear_cita(db, id_cita_externa="CIT-P-2")
    crear_prediccion(db, c1, "BAJO", "0.100", version="V1", cuando=datetime(2026, 10, 20, 15, tzinfo=timezone.utc))
    crear_prediccion(db, c1, "ALTO", "0.700", version="V2", cuando=datetime(2026, 10, 21, 15, tzinfo=timezone.utc))
    crear_prediccion(db, c2, "MEDIO", "0.350", version="V2", cuando=datetime(2026, 10, 22, 15, tzinfo=timezone.utc))
    h = cabecera(api_ia, usuarios["TECNICO_IA"])

    r = api_ia.get("/predicciones", headers=h, params={"desde": "2026-10-20", "hasta": "2026-10-22"})
    cuerpo = r.json()
    assert r.status_code == 200 and cuerpo["total"] == 3 and cuerpo["limite"] == 50
    fechas = [p["fecha_hora_inferencia"] for p in cuerpo["items"]]
    assert fechas == sorted(fechas, reverse=True)
    assert all(p["resultado_simulado"] is True for p in cuerpo["items"])
    assert api_ia.get("/predicciones", headers=h, params={"id_cita": c1.id_cita}).json()["total"] == 2
    assert api_ia.get("/predicciones", headers=h, params={"version_modelo": "V2", "nivel_riesgo": "MEDIO",
                                                          "desde": "2026-10-20"}).json()["total"] == 1
    assert api_ia.get("/predicciones", headers=h, params={"hasta": "2026-10-20", "desde": "2026-10-20"}).json()["total"] == 1
    r = api_ia.get("/predicciones", headers=h, params={"limite": 1, "desplazamiento": 1, "desde": "2026-10-20",
                                                       "hasta": "2026-10-22"})
    assert len(r.json()["items"]) == 1
    assert api_ia.get("/predicciones", headers=h, params={"limite": 0}).status_code == 422


def test_recepcion_no_lista_predicciones(api_ia, usuarios):
    r = api_ia.get("/predicciones", headers=cabecera(api_ia, usuarios["RECEPCION"]))
    assert r.status_code == 403 and _codigo(r) == "SIN_PERMISO"


# ---------- RNF-012 con el simulador real ----------

def test_inferencia_con_el_simulador_en_menos_de_5_segundos(client, usuarios, db, simulador_real, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "ia_url", simulador_real)
    monkeypatch.setattr(get_settings(), "ia_api_key", None)
    app.dependency_overrides[reloj_ia] = lambda: HOY
    cita = crear_cita(db)
    h = cabecera(client, usuarios["RECEPCION"])
    inicio = time.perf_counter()
    r = client.post(f"/citas/{cita.id_cita}/prediccion", headers=h)
    duracion = time.perf_counter() - inicio
    assert r.status_code == 201, r.text
    assert duracion <= 5
    assert r.json()["version_modelo"] == "SIMULADOR_v0.1.0" and r.json()["resultado_simulado"] is True
    assert r.json()["umbral_aplicado"] == 0.45
    m = client.get("/predicciones/modelo", headers=h).json()
    assert m["disponible"] is True and m["habilitado_piloto"] is True


def test_cliente_real_contra_puerto_cerrado_es_503(client, usuarios, db, monkeypatch):
    """Con el simulador apagado (nadie escucha), la API responde 503 sin colgarse."""
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "ia_url", "http://127.0.0.1:9")
    app.dependency_overrides[reloj_ia] = lambda: HOY
    cita = crear_cita(db)
    r = client.post(f"/citas/{cita.id_cita}/prediccion", headers=cabecera(client, usuarios["RECEPCION"]))
    assert r.status_code == 503 and _codigo(r) == "MOTOR_IA_NO_DISPONIBLE"
