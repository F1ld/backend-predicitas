"""Pruebas de contratos/modulo-02.json (M02-E01 a M02-E07), F-04 a F-07, RN17 y `transicionar`.

Datos 100 % sintéticos (PAC-TST-*). El reloj de la API se fija con `fijar_reloj`.
"""
import io
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.errores import TransicionInvalida
from app.modules.auditoria.models import AuditoriaEvento
from app.modules.citas.importer import importar_citas
from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.citas.reglas import LIMA, contar_previos
from app.modules.citas.service import transicionar
from app.modules.citas.synthetic import generar_citas
from app.modules.lista_espera.models import CupoLiberado, ListaEspera, Reasignacion
from tests.citas.conftest import BASE, HOY, crear_cita, crear_intervencion, crear_prediccion
from tests.conftest import cabecera


def _eventos(db, accion, id_entidad=None):
    consulta = select(AuditoriaEvento).where(AuditoriaEvento.accion == accion)
    if id_entidad is not None:
        consulta = consulta.where(AuditoriaEvento.id_entidad == id_entidad)
    return list(db.scalars(consulta))


def _codigo(r):
    return r.json()["error"]["codigo"]


# ---------------------------------------------------------------- M02-E01 bandeja

def test_listado_resumen_con_riesgo_intervencion_y_check_in(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    cita = crear_cita(db)
    crear_prediccion(db, cita, "BAJO", "0.100", version="v1", cuando=HOY - timedelta(days=2))
    crear_prediccion(db, cita, "ALTO", "0.612", version="v2", cuando=HOY - timedelta(days=1))
    crear_intervencion(db, cita, "FALLIDA", cuando=HOY - timedelta(days=2))
    crear_intervencion(db, cita, "RESPONDIDA", "CONFIRMA", cuando=HOY - timedelta(days=1))
    h = cabecera(client, usuarios["RECEPCION"])
    assert client.post(f"/citas/{cita.id_cita}/check-in", headers=h).status_code == 201

    r = client.get("/citas", headers=cabecera(client, usuarios["TECNICO_IA"]))
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["riesgo"]["nivel_riesgo"] == "ALTO" and item["riesgo"]["probabilidad_no_show"] == 0.612
    assert item["riesgo"]["version_modelo"] == "v2" and item["riesgo"]["resultado_simulado"] is True
    assert (item["estado_intervencion"], item["respuesta_paciente"]) == ("RESPONDIDA", "CONFIRMA")
    assert item["tiene_check_in"] is True
    assert set(BASE) <= set(item)


def test_filtros_medico_riesgo_e_intervencion(client, usuarios, db):
    alta = crear_cita(db, id_cita_externa="CIT-TST-A", medico="Dra. Alfa")
    baja = crear_cita(db, id_cita_externa="CIT-TST-B", medico="Dr. Beta")
    sin = crear_cita(db, id_cita_externa="CIT-TST-C", medico="Dr. Beta")
    crear_prediccion(db, alta, "ALTO", "0.700")
    crear_prediccion(db, baja, "BAJO", "0.100")
    crear_intervencion(db, alta)
    h = cabecera(client, usuarios["ADMINISTRADOR"])

    def ids(**params):
        r = client.get("/citas", headers=h, params=params)
        assert r.status_code == 200, r.text
        return {i["id_cita_externa"] for i in r.json()["items"]}

    assert ids(medico="Dr. Beta") == {"CIT-TST-B", "CIT-TST-C"}
    assert ids(nivel_riesgo="ALTO") == {"CIT-TST-A"}
    assert ids(nivel_riesgo="SIN_PREDICCION") == {"CIT-TST-C"}
    assert ids(con_intervencion="true") == {"CIT-TST-A"}
    assert ids(con_intervencion="false") == {"CIT-TST-B", "CIT-TST-C"}
    assert ids(especialidad="CARDIOLOGIA", estado="RECIBIDA", desde="2026-10-24", hasta="2026-10-24") == \
        {"CIT-TST-A", "CIT-TST-B", "CIT-TST-C"}
    assert ids(hasta="2026-10-23") == set()
    assert sin.id_cita


def test_busqueda_q_en_id_paciente_y_medico(client, usuarios, db):
    crear_cita(db, id_cita_externa="CIT-TST-XYZ", paciente_anon_id="PAC-TST-11111", medico="Dra. Gómez")
    crear_cita(db, id_cita_externa="CIT-TST-OTRA", paciente_anon_id="PAC-TST-22222", medico="Dr. Ruiz")
    h = cabecera(client, usuarios["RECEPCION"])
    for q, esperado in (("xyz", "CIT-TST-XYZ"), ("pac-tst-222", "CIT-TST-OTRA"), ("GÓMEZ", "CIT-TST-XYZ")):
        items = client.get("/citas", headers=h, params={"q": q}).json()["items"]
        assert [i["id_cita_externa"] for i in items] == [esperado], q
    assert client.get("/citas", headers=h, params={"q": "%"}).json()["total"] == 0  # comodines escapados


def test_listado_valida_parametros_y_ordena(client, usuarios, db):
    crear_cita(db, id_cita_externa="CIT-TST-2", fecha_hora_cita="2026-10-26T10:00:00-05:00")
    crear_cita(db, id_cita_externa="CIT-TST-1", fecha_hora_cita="2026-10-24T10:00:00-05:00")
    h = cabecera(client, usuarios["RECEPCION"])
    r = client.get("/citas", headers=h, params={"limite": 1})
    assert r.json()["total"] == 2 and [i["id_cita_externa"] for i in r.json()["items"]] == ["CIT-TST-1"]
    r = client.get("/citas", headers=h, params={"nivel_riesgo": "EXTREMO"})
    assert r.status_code == 422 and _codigo(r) == "VALIDACION" and "nivel_riesgo" in r.json()["error"]["campos"]
    assert client.get("/citas").status_code == 401


def test_rendimiento_listado_con_5000_citas(client, usuarios, db):
    """RNF-011: GET /citas responde en ≤ 3 s con 5 000 citas."""
    registros = generar_citas(historicas=5000, proximas=0, semilla=11, prefijo="PRF", con_invalidas=False)
    assert importar_citas(db, registros, id_usuario=None, ip="127.0.0.1", origen="rendimiento").aceptadas == 5000
    h = cabecera(client, usuarios["RECEPCION"])
    for params in ({}, {"q": "PRF-0049", "nivel_riesgo": "SIN_PREDICCION"}, {"desplazamiento": 4900}):
        inicio = time.perf_counter()
        r = client.get("/citas", headers=h, params=params)
        transcurrido = time.perf_counter() - inicio
        assert r.status_code == 200
        print(f"GET /citas {params or '(sin filtros)'}: {transcurrido * 1000:.0f} ms, total={r.json()['total']}")
        assert transcurrido <= 3


# ---------------------------------------------------------------- M02-E02 detalle

def test_detalle_completo(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    cita = crear_cita(db)
    viejo = crear_prediccion(db, cita, "BAJO", "0.100", version="v1", cuando=HOY - timedelta(days=2))
    nuevo = crear_prediccion(db, cita, "MEDIO", "0.350", version="v2", cuando=HOY - timedelta(days=1))
    inter = crear_intervencion(db, cita, "RESPONDIDA", "SOLICITA_LIBERACION")
    cupo = CupoLiberado(id_cita_origen=cita.id_cita, especialidad="CARDIOLOGIA", medico="Dr. Prueba",
                        fecha_hora_cupo=cita.fecha_hora_cita, estado_cupo="EN_OFERTA",
                        origen_liberacion="INTERVENCION_VOLUNTARIA")
    candidato = ListaEspera(paciente_anon_id="PAC-TST-ESPERA", especialidad_req="CARDIOLOGIA",
                            franja_preferida="INDIFERENTE", estado_candidato="CONTACTADO")
    db.add_all([cupo, candidato])
    db.flush()
    db.add(AuditoriaEvento(modulo="REASIGNACION", accion="OFERTAR", entidad_afectada="cupos_liberados",
                           id_entidad=cupo.id_cupo_liberado, datos_after={"id_candidato": candidato.id_candidato},
                           id_usuario=usuarios["RECEPCION"].id_usuario, direccion_ip="127.0.0.1"))
    db.flush()
    h = cabecera(client, usuarios["RECEPCION"])
    client.post(f"/citas/{cita.id_cita}/check-in", headers=h)

    d = client.get(f"/citas/{cita.id_cita}", headers=cabecera(client, usuarios["TECNICO_IA"])).json()
    assert [p["id_prediccion"] for p in d["predicciones"]] == [nuevo.id_prediccion, viejo.id_prediccion]
    assert d["predicciones"][0]["umbral_aplicado"] == 0.45 and d["predicciones"][0]["resultado_simulado"] is True
    i = d["intervenciones"][0]
    assert i["id_intervencion"] == inter.id_intervencion and i["id_cita_externa"] == cita.id_cita_externa
    assert set(i["acciones_disponibles"]) == {"REGISTRAR_OPTOUT", "LIBERAR_CUPO"}
    c = d["cupo_liberado"]
    assert c["id_cita_externa_origen"] == cita.id_cita_externa and c["franja_horaria"] == "MANANA"
    assert c["oferta_vigente"]["id_candidato"] == candidato.id_candidato
    assert c["oferta_vigente"]["paciente_anon_id"] == "PAC-TST-ESPERA"
    assert d["check_in"]["id_usuario"] == usuarios["RECEPCION"].id_usuario
    assert d["reasignacion"] is None

    cupo.estado_cupo = "REASIGNADO"
    db.add(Reasignacion(id_cupo_liberado=cupo.id_cupo_liberado, id_candidato=candidato.id_candidato,
                        id_operador_confirma=usuarios["RECEPCION"].id_usuario, confirmacion_humana=True,
                        medio_confirmacion="PRESENCIAL"))
    db.flush()
    d = client.get(f"/citas/{cita.id_cita}", headers=h).json()
    assert d["reasignacion"]["paciente_anon_id"] == "PAC-TST-ESPERA"
    assert d["cupo_liberado"]["oferta_vigente"] is None


@pytest.mark.parametrize(("estado", "canal", "respuesta", "cita_estado", "esperado"), [
    ("PENDIENTE", "SMS", None, "RECIBIDA", {"REGISTRAR_ENVIO", "REGISTRAR_FALLO"}),
    ("ENVIADA", "SMS", None, "RECIBIDA", {"REGISTRAR_ENTREGA", "REGISTRAR_FALLO"}),
    ("ENVIADA", "LLAMADA_TELEFONICA", None, "RECIBIDA",
     {"REGISTRAR_ENTREGA", "REGISTRAR_FALLO", "REGISTRAR_RESPUESTA"}),
    ("ENTREGADA", "SMS", None, "RECIBIDA", {"REGISTRAR_RESPUESTA"}),
    ("RESPONDIDA", "SMS", "CONFIRMA", "RECIBIDA", {"REGISTRAR_OPTOUT", "CONFIRMAR_CITA"}),
    ("RESPONDIDA", "SMS", "CONFIRMA", "CONFIRMADA", {"REGISTRAR_OPTOUT"}),
    ("FALLIDA", "SMS", None, "RECIBIDA", set()),
])
def test_acciones_disponibles_de_intervencion(client, usuarios, db, estado, canal, respuesta, cita_estado, esperado):
    cita = crear_cita(db, estado_actual=cita_estado)
    crear_intervencion(db, cita, estado, respuesta, canal=canal)
    d = client.get(f"/citas/{cita.id_cita}", headers=cabecera(client, usuarios["RECEPCION"])).json()
    assert set(d["intervenciones"][0]["acciones_disponibles"]) == esperado


def test_detalle_inexistente_404(client, usuarios):
    r = client.get("/citas/999999999", headers=cabecera(client, usuarios["RECEPCION"]))
    assert r.status_code == 404 and _codigo(r) == "NO_ENCONTRADO"


# ---------------------------------------------------------------- M02-E03 registro manual

def test_registro_manual_entra_en_recibida_con_historial_y_auditoria(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    h = cabecera(client, usuarios["RECEPCION"])
    r = client.post("/citas", headers=h, json={**BASE, "fecha_hora_cita": "2026-10-24T09:00:00"})  # sin zona = Lima
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["estado_actual"] == "RECIBIDA" and d["target_no_show"] is None
    assert (d["antelacion_dias"], d["franja_horaria"], d["dia_semana"]) == (14, "MANANA", "SABADO")
    assert [e["estado_nuevo"] for e in d["historial"]] == ["RECIBIDA"]
    assert d["check_in"] is None and d["predicciones"] == [] and d["cupo_liberado"] is None
    eventos = _eventos(db, "CREATE", d["id_cita"])
    assert len(eventos) == 1 and eventos[0].modulo == "CITAS"
    assert eventos[0].datos_after["id_cita_externa"] == BASE["id_cita_externa"]

    r = client.post("/citas", headers=h, json=BASE)
    assert r.status_code == 409 and _codigo(r) == "CITA_DUPLICADA"


@pytest.mark.parametrize(("cambio", "codigo", "campo"), [
    ({"sede": "MIRAFLORES"}, "FUERA_DE_PERIMETRO", "sede"),
    ({"especialidad": "DERMATOLOGIA"}, "FUERA_DE_PERIMETRO", "especialidad"),
    ({"fecha_hora_cita": "2026-10-25T09:00:00-05:00"}, "FUERA_DE_PERIMETRO", "fecha_hora_cita"),  # domingo
    ({"fecha_registro_cita": "2026-10-25T09:00:00-05:00"}, "FECHAS_INCONSISTENTES", "fecha_registro_cita"),
    ({"tipo_paciente": "VIP"}, "VALIDACION", "tipo_paciente"),
    ({"inasistencias_previas": -1}, "VALIDACION", "inasistencias_previas"),
    ({"estado_actual": "ATENDIDA"}, "VALIDACION", "estado_actual"),  # RN03: no se elige el estado
])
def test_registro_manual_rechazos(client, usuarios, cambio, codigo, campo):
    r = client.post("/citas", headers=cabecera(client, usuarios["ADMINISTRADOR"]), json={**BASE, **cambio})
    assert r.status_code == 422 and _codigo(r) == codigo, r.text
    assert campo in r.json()["error"]["campos"]


def test_registro_manual_sin_permiso_tecnico(client, usuarios):
    r = client.post("/citas", headers=cabecera(client, usuarios["TECNICO_IA"]), json=BASE)
    assert r.status_code == 403 and _codigo(r) == "SIN_PERMISO"


# ---------------------------------------------------------------- RN17 contadores

def test_rn17_contar_previos_solo_usa_citas_anteriores_al_registro():
    registro = datetime(2026, 10, 10, 10, 0, tzinfo=LIMA)
    desenlaces = [
        (registro - timedelta(days=30), "NO_SHOW"),
        (registro - timedelta(days=10), "ATENDIDA"),
        (registro - timedelta(minutes=1), "ATENDIDA"),
        (registro, "NO_SHOW"),  # misma hora: no es anterior
        (registro + timedelta(days=1), "NO_SHOW"),  # posterior al registro: sería leakage
    ]
    assert contar_previos(desenlaces, registro) == (1, 2)


def test_rn17_registro_manual_calcula_contadores_omitidos(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    paciente = "PAC-TST-RN17"
    previas = [("CIT-TST-P1", "2026-09-01T09:00:00-05:00", "NO_SHOW"),
               ("CIT-TST-P2", "2026-09-15T09:00:00-05:00", "ATENDIDA"),
               ("CIT-TST-P3", "2026-10-15T09:00:00-05:00", "NO_SHOW"),  # posterior al registro de la nueva
               ("CIT-TST-P4", "2026-09-19T09:00:00-05:00", "CANCELADA")]  # sin desenlace
    for id_ext, fecha, estado in previas:
        crear_cita(db, id_cita_externa=id_ext, paciente_anon_id=paciente, fecha_hora_cita=fecha,
                   fecha_registro_cita="2026-08-20T09:00:00-05:00", estado_actual=estado)
    crear_cita(db, id_cita_externa="CIT-TST-OTRO", paciente_anon_id="PAC-TST-OTRO",
               fecha_hora_cita="2026-09-02T09:00:00-05:00", fecha_registro_cita="2026-08-20T09:00:00-05:00",
               estado_actual="NO_SHOW")
    h = cabecera(client, usuarios["RECEPCION"])
    d = client.post("/citas", headers=h, json={**BASE, "paciente_anon_id": paciente}).json()
    assert (d["inasistencias_previas"], d["asistencias_previas"]) == (1, 1)

    informados = {**BASE, "id_cita_externa": "CIT-TST-DECL", "paciente_anon_id": paciente,
                  "inasistencias_previas": 5, "asistencias_previas": 0}
    d = client.post("/citas", headers=h, json=informados).json()
    assert (d["inasistencias_previas"], d["asistencias_previas"]) == (5, 0)  # declarados: se respetan


def test_rn17_importacion_cuenta_filas_anteriores_del_mismo_lote(db):
    paciente = "PAC-TST-LOTE"
    fila = lambda id_ext, cita, registro, estado: {  # noqa: E731
        **BASE, "id_cita_externa": id_ext, "paciente_anon_id": paciente,
        "fecha_hora_cita": cita, "fecha_registro_cita": registro, "estado_actual": estado}
    lote = [  # desordenado a propósito
        fila("CIT-TST-L3", "2026-10-24T09:00:00-05:00", "2026-10-10T09:00:00-05:00", "RECIBIDA"),
        fila("CIT-TST-L2", "2026-10-05T09:00:00-05:00", "2026-09-20T09:00:00-05:00", "ATENDIDA"),
        fila("CIT-TST-L1", "2026-09-10T09:00:00-05:00", "2026-09-01T09:00:00-05:00", "NO_SHOW"),
    ]
    r = importar_citas(db, lote, id_usuario=None, ip="127.0.0.1", origen="prueba", ahora=HOY)
    assert r.aceptadas == 3
    citas = {c.id_cita_externa: c for c in db.scalars(select(Cita).where(Cita.paciente_anon_id == paciente))}
    assert (citas["CIT-TST-L1"].inasistencias_previas, citas["CIT-TST-L1"].asistencias_previas) == (0, 0)
    assert (citas["CIT-TST-L2"].inasistencias_previas, citas["CIT-TST-L2"].asistencias_previas) == (1, 0)
    assert (citas["CIT-TST-L3"].inasistencias_previas, citas["CIT-TST-L3"].asistencias_previas) == (1, 1)
    assert citas["CIT-TST-L1"].id_cita < citas["CIT-TST-L2"].id_cita < citas["CIT-TST-L3"].id_cita


# ---------------------------------------------------------------- M02-E04 importación

def test_importacion_rechaza_desenlace_en_fecha_futura(db):
    r = importar_citas(db, [{**BASE, "estado_actual": "NO_SHOW"}], id_usuario=None, ip="127.0.0.1",
                       origen="prueba", ahora=HOY - timedelta(days=1))
    assert r.rechazadas == 1 and "fecha futura" in r.detalle_rechazos[0].motivos[0]


def test_importacion_por_http_y_errores_de_archivo(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    h = cabecera(client, usuarios["RECEPCION"])
    cabeceras = ",".join(BASE)
    csv_ok = f"{cabeceras},estado_actual\n" + ",".join(BASE.values()) + ",RECIBIDA\n"
    r = client.post("/citas/importar", headers=h, files={"archivo": ("c.csv", io.BytesIO(csv_ok.encode()), "text/csv")})
    assert r.status_code == 200 and r.json()["aceptadas"] == 1
    assert len(_eventos(db, "IMPORT")) == 1

    for contenido in (f"{cabeceras}\n".encode(), "ñ".encode("latin-1"), b"x" * (2 * 1024 * 1024 + 1)):
        r = client.post("/citas/importar", headers=h, files={"archivo": ("c.csv", io.BytesIO(contenido), "text/csv")})
        assert r.status_code == 422 and _codigo(r) == "ARCHIVO_INVALIDO"
    r = client.post("/citas/importar", headers=cabecera(client, usuarios["TECNICO_IA"]),
                    files={"archivo": ("c.csv", io.BytesIO(csv_ok.encode()), "text/csv")})
    assert r.status_code == 403


def test_importacion_supera_maximo_de_filas(client, usuarios):
    filas = "\n".join(f"CIT-{n}" for n in range(5001))
    r = client.post("/citas/importar", headers=cabecera(client, usuarios["RECEPCION"]),
                    files={"archivo": ("c.csv", io.BytesIO(f"id_cita_externa\n{filas}\n".encode()), "text/csv")})
    assert r.status_code == 422 and _codigo(r) == "ARCHIVO_INVALIDO"


# ---------------------------------------------------------------- M02-E05 cambio de estado

def _estado(client, h, cita, **cuerpo):
    return client.post(f"/citas/{cita.id_cita}/estado", headers=h, json=cuerpo)


def test_reprogramada_recalcula_y_suma_reprogramaciones(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    cita = crear_cita(db, reprogramaciones_prev=2)
    h = cabecera(client, usuarios["RECEPCION"])
    r = _estado(client, h, cita, estado_nuevo="REPROGRAMADA", nueva_fecha_hora_cita="2026-10-28T15:30:00-05:00")
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["antelacion_dias"], d["franja_horaria"], d["dia_semana"], d["reprogramaciones_prev"]) == \
        (18, "TARDE", "MIERCOLES", 3)
    # REPROGRAMADA → REPROGRAMADA (D-011), con hora sin zona = Lima
    d = _estado(client, h, cita, estado_nuevo="REPROGRAMADA", nueva_fecha_hora_cita="2026-10-30T09:00:00").json()
    assert (d["dia_semana"], d["franja_horaria"], d["reprogramaciones_prev"]) == ("VIERNES", "MANANA", 4)
    ultimo = _eventos(db, "UPDATE", cita.id_cita)[-1]
    assert ultimo.datos_before["reprogramaciones_prev"] == 3 and ultimo.datos_after["reprogramaciones_prev"] == 4


@pytest.mark.parametrize(("cuerpo", "codigo", "campo"), [
    ({"estado_nuevo": "REPROGRAMADA"}, "VALIDACION", "nueva_fecha_hora_cita"),
    ({"estado_nuevo": "CONFIRMADA", "nueva_fecha_hora_cita": "2026-10-28T09:00:00-05:00"},
     "VALIDACION", "nueva_fecha_hora_cita"),
    ({"estado_nuevo": "REPROGRAMADA", "nueva_fecha_hora_cita": "2026-11-01T09:00:00-05:00"},
     "FUERA_DE_PERIMETRO", "nueva_fecha_hora_cita"),  # domingo
    ({"estado_nuevo": "REPROGRAMADA", "nueva_fecha_hora_cita": "2026-10-01T09:00:00-05:00"},
     "VALIDACION", "nueva_fecha_hora_cita"),  # antes del registro
    ({"estado_nuevo": "ATENDIDA", "liberar_cupo": True}, "VALIDACION", "liberar_cupo"),
    ({"estado_nuevo": "CANCELADA", "id_intervencion": 1}, "VALIDACION", "id_intervencion"),
])
def test_cambio_estado_validaciones(client, usuarios, db, fijar_reloj, cuerpo, codigo, campo):
    fijar_reloj()
    cita = crear_cita(db)
    r = _estado(client, cabecera(client, usuarios["RECEPCION"]), cita, **cuerpo)
    assert r.status_code == 422 and _codigo(r) == codigo, r.text
    assert campo in r.json()["error"]["campos"]


def test_cancelada_con_liberar_cupo_crea_cupo_en_la_misma_transaccion(client, usuarios, db, fijar_reloj):
    fijar_reloj(HOY - timedelta(days=3))
    cita = crear_cita(db)
    r = _estado(client, cabecera(client, usuarios["RECEPCION"]), cita, estado_nuevo="CANCELADA", liberar_cupo=True)
    assert r.status_code == 200, r.text
    c = r.json()["cupo_liberado"]
    assert (c["estado_cupo"], c["origen_liberacion"], c["medico"]) == ("DISPONIBLE", "CANCELACION_EXTERNA", "Dr. Prueba")
    assert r.json()["estado_actual"] == "CANCELADA"
    liberar = _eventos(db, "LIBERAR", c["id_cupo_liberado"])
    assert len(liberar) == 1 and liberar[0].modulo == "REASIGNACION"


def test_cancelada_liberar_cupo_de_cita_pasada(client, usuarios, db, fijar_reloj):
    fijar_reloj(HOY + timedelta(hours=2))  # 10:00, la cita era a las 09:00
    cita = crear_cita(db)
    r = _estado(client, cabecera(client, usuarios["RECEPCION"]), cita, estado_nuevo="CANCELADA", liberar_cupo=True)
    assert r.status_code == 409 and _codigo(r) == "CITA_PASADA"
    assert db.scalar(select(CupoLiberado).where(CupoLiberado.id_cita_origen == cita.id_cita)) is None


def test_cancelada_sin_liberar_no_crea_cupo(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    cita = crear_cita(db)
    r = _estado(client, cabecera(client, usuarios["RECEPCION"]), cita, estado_nuevo="CANCELADA", motivo="Externa")
    assert r.status_code == 200 and r.json()["cupo_liberado"] is None


def test_confirmada_con_intervencion_de_la_misma_cita(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    cita = crear_cita(db)
    otra = crear_cita(db, id_cita_externa="CIT-TST-OTRA")
    propia = crear_intervencion(db, cita, "RESPONDIDA", "CONFIRMA")
    ajena = crear_intervencion(db, otra, "RESPONDIDA", "CONFIRMA")
    h = cabecera(client, usuarios["RECEPCION"])
    r = _estado(client, h, cita, estado_nuevo="CONFIRMADA", id_intervencion=ajena.id_intervencion)
    assert r.status_code == 422 and "id_intervencion" in r.json()["error"]["campos"]
    r = _estado(client, h, cita, estado_nuevo="CONFIRMADA", id_intervencion=propia.id_intervencion)
    assert r.status_code == 200 and r.json()["estado_actual"] == "CONFIRMADA"
    assert _eventos(db, "UPDATE", cita.id_cita)[-1].datos_after["id_intervencion"] == propia.id_intervencion


@pytest.mark.parametrize("estado", ["ATENDIDA", "NO_SHOW"])
def test_desenlace_anticipado(client, usuarios, db, fijar_reloj, estado):
    fijar_reloj(HOY - timedelta(days=1))
    cita = crear_cita(db)
    r = _estado(client, cabecera(client, usuarios["RECEPCION"]), cita, estado_nuevo=estado)
    assert r.status_code == 409 and _codigo(r) == "DESENLACE_ANTICIPADO"


def test_desenlace_de_cita_pasada_fija_target(client, usuarios, db, fijar_reloj):
    fijar_reloj(HOY + timedelta(days=2))
    cita = crear_cita(db)
    d = _estado(client, cabecera(client, usuarios["RECEPCION"]), cita, estado_nuevo="NO_SHOW").json()
    assert (d["estado_actual"], d["target_no_show"]) == ("NO_SHOW", 1)


def test_check_in_bloquea_no_show(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    cita = crear_cita(db)
    h = cabecera(client, usuarios["RECEPCION"])
    assert client.post(f"/citas/{cita.id_cita}/check-in", headers=h).status_code == 201
    r = _estado(client, h, cita, estado_nuevo="NO_SHOW")
    assert r.status_code == 409 and _codigo(r) == "CHECK_IN_REGISTRADO"
    assert _estado(client, h, cita, estado_nuevo="ATENDIDA").status_code == 200


def test_cambio_estado_404(client, usuarios):
    r = client.post("/citas/999999999/estado", headers=cabecera(client, usuarios["RECEPCION"]),
                    json={"estado_nuevo": "CONFIRMADA"})
    assert r.status_code == 404 and _codigo(r) == "NO_ENCONTRADO"


# ---------------------------------------------------------------- M02-E06 check-in

def test_check_in_registra_evento_una_sola_vez(client, usuarios, db, fijar_reloj):
    fijar_reloj()
    cita = crear_cita(db, estado_actual="CONFIRMADA")
    h = cabecera(client, usuarios["RECEPCION"])
    r = client.post(f"/citas/{cita.id_cita}/check-in", headers=h, json={"observacion": "Llegó temprano"})
    assert r.status_code == 201, r.text
    assert r.json()["id_usuario"] == usuarios["RECEPCION"].id_usuario and r.json()["fecha_hora_check_in"]
    eventos = _eventos(db, "CHECK_IN", cita.id_cita)
    assert len(eventos) == 1 and eventos[0].modulo == "CITAS" and eventos[0].entidad_afectada == "citas"
    db.refresh(cita)
    assert cita.estado_actual == "CONFIRMADA"  # no cambia el estado
    r = client.post(f"/citas/{cita.id_cita}/check-in", headers=h)
    assert r.status_code == 409 and _codigo(r) == "CHECK_IN_DUPLICADO"


def test_check_in_errores(client, usuarios, db, fijar_reloj):
    h = cabecera(client, usuarios["RECEPCION"])
    cita = crear_cita(db)
    fijar_reloj(HOY + timedelta(days=1))
    r = client.post(f"/citas/{cita.id_cita}/check-in", headers=h)
    assert r.status_code == 409 and _codigo(r) == "FUERA_DE_FECHA"
    fijar_reloj()
    cancelada = crear_cita(db, id_cita_externa="CIT-TST-CANC", estado_actual="CANCELADA")
    r = client.post(f"/citas/{cancelada.id_cita}/check-in", headers=h)
    assert r.status_code == 409 and _codigo(r) == "ESTADO_FINAL"
    assert client.post("/citas/999999999/check-in", headers=h).status_code == 404
    r = client.post(f"/citas/{cita.id_cita}/check-in", headers=cabecera(client, usuarios["TECNICO_IA"]))
    assert r.status_code == 403


# ---------------------------------------------------------------- M02-E07 catálogos

def test_catalogos(client, usuarios, db):
    crear_cita(db, id_cita_externa="CIT-TST-M1", medico="Dr. Zeta")
    crear_cita(db, id_cita_externa="CIT-TST-M2", medico="Dra. Alfa")
    crear_cita(db, id_cita_externa="CIT-TST-M3", medico="Dra. Alfa")
    r = client.get("/citas/catalogos", headers=cabecera(client, usuarios["TECNICO_IA"]))
    assert r.status_code == 200
    d = r.json()
    assert d["especialidades"] == ["CARDIOLOGIA", "TRAUMATOLOGIA", "PEDIATRIA"]
    assert "LIBERADA" in d["estados"] and d["niveles_riesgo"] == ["BAJO", "MEDIO", "ALTO"]
    assert d["medicos"] == sorted(set(d["medicos"])) and {"Dr. Zeta", "Dra. Alfa"} <= set(d["medicos"])
    assert d["canales_origen"] and d["tipos_paciente"]


# ---------------------------------------------------------------- servicio interno transicionar

@pytest.mark.parametrize("origen", ["RECIBIDA", "CONFIRMADA", "REPROGRAMADA"])
def test_transicionar_a_liberada(db, usuarios, origen):
    cita = crear_cita(db, estado_actual=origen)
    transicionar(db, cita, "LIBERADA", usuario=usuarios["RECEPCION"], ip="127.0.0.1", motivo="Liberación voluntaria")
    db.flush()
    assert cita.estado_actual == "LIBERADA" and cita.target_no_show is None
    hist = db.scalars(select(HistorialEstadoCita).where(HistorialEstadoCita.id_cita == cita.id_cita)
                      .order_by(HistorialEstadoCita.id_historial)).all()
    assert (hist[-1].estado_anterior, hist[-1].estado_nuevo) == (origen, "LIBERADA")
    assert _eventos(db, "UPDATE", cita.id_cita)[-1].datos_after["estado_actual"] == "LIBERADA"


@pytest.mark.parametrize(("origen", "destino"), [("CANCELADA", "LIBERADA"), ("ATENDIDA", "LIBERADA"),
                                                 ("RECIBIDA", "REPROGRAMADA"), ("RECIBIDA", "RECIBIDA")])
def test_transicionar_invalida(db, usuarios, origen, destino):
    cita = crear_cita(db, estado_actual=origen, fecha_hora_cita="2026-10-10T09:00:00-05:00",
                      fecha_registro_cita="2026-10-01T09:00:00-05:00")
    with pytest.raises(TransicionInvalida):
        transicionar(db, cita, destino, usuario=usuarios["RECEPCION"], ip="127.0.0.1")


def test_transicionar_no_hace_commit(db, usuarios):
    cita = crear_cita(db)
    db.commit()  # punto de partida confirmado (dentro de la transacción de prueba)
    transicionar(db, cita, "LIBERADA", usuario=usuarios["RECEPCION"], ip="127.0.0.1")
    db.rollback()
    db.refresh(cita)
    assert cita.estado_actual == "RECIBIDA"
