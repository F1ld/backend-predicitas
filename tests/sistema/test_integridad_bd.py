from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

import app.core.models  # noqa: F401
from app.core.database import SessionLocal
from app.modules.auditoria.models import AuditoriaEvento
from app.modules.citas.models import Cita


@pytest.fixture
def db():
    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.rollback()
        sesion.close()


def _cita(**cambios) -> Cita:
    ahora = datetime.now(timezone.utc)
    datos = dict(
        id_cita_externa="CIT-TEST-0001", paciente_anon_id="PAC-TEST-0001",
        sede="SAN_ISIDRO", especialidad="CARDIOLOGIA", medico="Dr. Prueba",
        fecha_hora_cita=ahora + timedelta(days=10), fecha_registro_cita=ahora,
        antelacion_dias=10, tipo_paciente="NUEVO", canal_origen="WEB",
        franja_horaria="MANANA", dia_semana="LUNES", estado_actual="RECIBIDA",
    )
    datos.update(cambios)
    return Cita(**datos)


def test_sede_fuera_del_piloto_se_rechaza(db):
    db.add(_cita(sede="MIRAFLORES"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_target_sin_desenlace_se_rechaza(db):
    db.add(_cita(target_no_show=1))
    with pytest.raises(IntegrityError):
        db.flush()


def test_auditoria_es_solo_insercion(db):
    evento = AuditoriaEvento(
        modulo="CITAS", accion="IMPORT", entidad_afectada="citas", direccion_ip="127.0.0.1"
    )
    db.add(evento)
    db.flush()
    evento.accion = "UPDATE"
    # RNF-009 (D-015): lo rechaza el permiso de predicitas_app (T-011) o el trigger; ambos son DBAPIError.
    with pytest.raises(DBAPIError):
        db.flush()