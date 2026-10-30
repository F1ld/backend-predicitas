from sqlalchemy import select

from app.modules.auditoria.models import AuditoriaEvento
from app.modules.citas.importer import importar_citas
from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.lista_espera.models import CupoLiberado
from tests.conftest import cabecera


def _crear_cita_prueba(db, id_usuario: int, codigo: str, paciente: str) -> Cita:
    importar_citas(
        db,
        [
            {
                "id_cita_externa": codigo,
                "paciente_anon_id": paciente,
                "sede": "SAN_ISIDRO",
                "especialidad": "CARDIOLOGIA",
                "medico": "Dr. Ramírez",
                "fecha_hora_cita": "2026-11-05T15:30:00-05:00",
                "fecha_registro_cita": "2026-10-08T09:00:00-05:00",
                "tipo_paciente": "CONTINUADOR",
                "canal_origen": "CALL_CENTER",
                "inasistencias_previas": 3,
                "reprogramaciones_prev": 1,
                "asistencias_previas": 1,
                "estado_actual": "RECIBIDA",
            }
        ],
        id_usuario=id_usuario,
        ip="127.0.0.1",
        origen="test_intervenciones",
    )
    return db.scalar(select(Cita).where(Cita.id_cita_externa == codigo))


def test_bloquea_envio_con_optout_y_maximo_un_recordatorio_adicional(client, usuarios, db):
    cita = _crear_cita_prueba(db, usuarios["ADMINISTRADOR"].id_usuario, "CIT-INT-001", "PAC-INT-001")
    h = cabecera(client, usuarios["RECEPCION"])

    # 1. Rechaza si se envía con consentimiento_optout = True (HTTP 409)
    r_optout = client.post(
        f"/citas/{cita.id_cita}/intervenciones",
        headers=h,
        json={"canal_contacto": "WHATSAPP", "consentimiento_optout": True},
    )
    assert r_optout.status_code == 409

    # 2. Primer envío válido se registra correctamente
    r_ok = client.post(
        f"/citas/{cita.id_cita}/intervenciones",
        headers=h,
        json={"canal_contacto": "WHATSAPP", "plantilla_mensaje": "RECORDATORIO_PREVENTIVO"},
    )
    assert r_ok.status_code == 200, r_ok.text

    # 3. Segundo envío adicional sobre la misma cita se rechaza con HTTP 409 (RN07 / RF-066)
    r_dup = client.post(
        f"/citas/{cita.id_cita}/intervenciones",
        headers=h,
        json={"canal_contacto": "SMS", "plantilla_mensaje": "SEGUNDO_RECORDATORIO"},
    )
    assert r_dup.status_code == 409


def test_respuesta_confirma_cambia_cita_a_confirmada_y_sin_respuesta_no_cancela(client, usuarios, db):
    cita1 = _crear_cita_prueba(db, usuarios["ADMINISTRADOR"].id_usuario, "CIT-INT-002", "PAC-INT-002")
    cita2 = _crear_cita_prueba(db, usuarios["ADMINISTRADOR"].id_usuario, "CIT-INT-003", "PAC-INT-003")
    h = cabecera(client, usuarios["RECEPCION"])

    # Cita 1: CONFIRMA -> estado_actual pasa a CONFIRMADA
    int1 = client.post(f"/citas/{cita1.id_cita}/intervenciones", headers=h, json={"canal_contacto": "WHATSAPP"}).json()
    r1 = client.patch(
        f"/intervenciones/{int1['id_intervencion']}",
        headers=h,
        json={"respuesta_paciente": "CONFIRMA"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["estado_cita_actual"] == "CONFIRMADA"

    # Cita 2: SIN_RESPUESTA -> cita se mantiene intacta en RECIBIDA (prohibición de cancelación unilateral RN02)
    int2 = client.post(f"/citas/{cita2.id_cita}/intervenciones", headers=h, json={"canal_contacto": "SMS"}).json()
    r2 = client.patch(
        f"/intervenciones/{int2['id_intervencion']}",
        headers=h,
        json={"respuesta_paciente": "SIN_RESPUESTA"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["estado_cita_actual"] == "RECIBIDA"


def test_solicita_liberacion_cambia_a_liberada_crea_cupo_y_audita_liberar(client, usuarios, db):
    cita = _crear_cita_prueba(db, usuarios["ADMINISTRADOR"].id_usuario, "CIT-INT-004", "PAC-INT-004")
    h = cabecera(client, usuarios["RECEPCION"])

    # Evaluar primero con IA para verificar bandeja sugerida
    client.post(f"/ia/predecir/{cita.id_cita}", headers=h)
    bandeja = client.get("/intervenciones", headers=h).json()
    assert any(c["id_cita"] == cita.id_cita for c in bandeja["citas_sugeridas"])

    interv = client.post(
        f"/citas/{cita.id_cita}/intervenciones",
        headers=h,
        json={"canal_contacto": "LLAMADA_TELEFONICA"},
    ).json()

    r = client.patch(
        f"/intervenciones/{interv['id_intervencion']}",
        headers=h,
        json={"respuesta_paciente": "SOLICITA_LIBERACION", "observacion": "Paciente viaja por trabajo"},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["estado_cita_actual"] == "LIBERADA"
    assert cuerpo["id_cupo_liberado_generado"] is not None

    # Verificar en BD: cita en LIBERADA, historial creado, cupo DISPONIBLE y evento LIBERAR en auditoría
    db.expire_all()
    cita_bd = db.get(Cita, cita.id_cita)
    assert cita_bd.estado_actual == "LIBERADA"

    cupo_bd = db.get(CupoLiberado, cuerpo["id_cupo_liberado_generado"])
    assert cupo_bd is not None and cupo_bd.estado_cupo == "DISPONIBLE"

    hist = list(db.scalars(select(HistorialEstadoCita).where(HistorialEstadoCita.id_cita == cita.id_cita)))
    assert any(e.estado_nuevo == "LIBERADA" for e in hist)

    ev_lib = db.scalar(
        select(AuditoriaEvento).where(
            AuditoriaEvento.modulo == "INTERVENCION",
            AuditoriaEvento.accion == "LIBERAR",
            AuditoriaEvento.id_entidad == cupo_bd.id_cupo_liberado,
        )
    )
    assert ev_lib is not None

