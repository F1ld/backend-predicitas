from sqlalchemy import select

from app.modules.citas.importer import importar_citas
from app.modules.citas.models import Cita
from app.modules.citas.synthetic import generar_citas
from tests.conftest import cabecera

REGISTRO = {
    "id_cita_externa": "CIT-TST-000001", "paciente_anon_id": "PAC-TST-00001", "sede": "SAN_ISIDRO",
    "especialidad": "CARDIOLOGIA", "medico": "Dr. Prueba",
    "fecha_hora_cita": "2026-10-24T09:00:00-05:00", "fecha_registro_cita": "2026-10-10T10:00:00-05:00",
    "tipo_paciente": "NUEVO", "canal_origen": "WEB",
}


def _importar(db, registros):
    return importar_citas(db, registros, id_usuario=None, ip="127.0.0.1", origen="prueba")


def test_importador_deriva_variables_en_el_servidor(db):
    assert _importar(db, [REGISTRO]).aceptadas == 1
    cita = db.scalar(select(Cita).where(Cita.id_cita_externa == "CIT-TST-000001"))
    assert (cita.antelacion_dias, cita.franja_horaria, cita.dia_semana) == (14, "MANANA", "SABADO")
    assert cita.estado_actual == "RECIBIDA" and cita.target_no_show is None


def test_importador_acepta_validas_y_rechaza_invalidas_con_motivo(db):
    registros = generar_citas(historicas=30, proximas=10, semilla=7, prefijo="TST")
    r = _importar(db, registros)
    assert (r.aceptadas, r.rechazadas) == (40, 4)
    texto = " ".join(m for rechazo in r.detalle_rechazos for m in rechazo.motivos)
    assert "MIRAFLORES" in texto and "DERMATOLOGIA" in texto and "duplicada" in texto and "posterior" in texto
    # el desenlace solo existe en las citas ATENDIDA / NO_SHOW (aislamiento del target)
    for c in db.scalars(select(Cita).where(Cita.id_cita_externa.like("CIT-TST-%"))):
        assert (c.target_no_show is not None) == (c.estado_actual in ("ATENDIDA", "NO_SHOW"))


def test_reimportar_lo_mismo_rechaza_todo_como_duplicado(db):
    _importar(db, [REGISTRO])
    r = _importar(db, [REGISTRO])
    assert (r.aceptadas, r.rechazadas) == (0, 1)


def test_recepcion_cambia_estado_y_queda_historial(client, usuarios, db, fijar_reloj):
    fijar_reloj()  # el día de la cita: el desenlace ya no es anticipado (F-06)
    _importar(db, [REGISTRO])
    cita = db.scalar(select(Cita).where(Cita.id_cita_externa == "CIT-TST-000001"))
    h = cabecera(client, usuarios["RECEPCION"])

    r = client.post(f"/citas/{cita.id_cita}/estado", headers=h, json={"estado_nuevo": "ATENDIDA"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado_actual"] == "ATENDIDA" and cuerpo["target_no_show"] == 0
    assert [e["estado_nuevo"] for e in cuerpo["historial"]] == ["RECIBIDA", "ATENDIDA"]

    # ATENDIDA es un estado final: otro cambio se rechaza
    r2 = client.post(f"/citas/{cita.id_cita}/estado", headers=h, json={"estado_nuevo": "CANCELADA"})
    assert r2.status_code == 409
    assert r2.json()["error"]["codigo"] == "TRANSICION_INVALIDA"
    assert r2.json()["error"]["campos"] == {}


def test_tecnico_ia_puede_leer_pero_no_modificar(client, usuarios, db):
    _importar(db, [REGISTRO])
    cita = db.scalar(select(Cita).where(Cita.id_cita_externa == "CIT-TST-000001"))
    h = cabecera(client, usuarios["TECNICO_IA"])
    assert client.get(f"/citas/{cita.id_cita}", headers=h).status_code == 200
    r = client.post(f"/citas/{cita.id_cita}/estado", headers=h, json={"estado_nuevo": "CONFIRMADA"})
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] == "SIN_PERMISO"


def test_no_se_puede_liberar_manualmente(client, usuarios, db):
    _importar(db, [REGISTRO])
    cita = db.scalar(select(Cita).where(Cita.id_cita_externa == "CIT-TST-000001"))
    h = cabecera(client, usuarios["RECEPCION"])
    r = client.post(f"/citas/{cita.id_cita}/estado", headers=h, json={"estado_nuevo": "LIBERADA"})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "VALIDACION"
    assert "estado_nuevo" in r.json()["error"]["campos"]