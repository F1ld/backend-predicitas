"""Utilidades de las pruebas de M02: reloj fijo y fábricas de datos sintéticos."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.main import app
from app.modules.citas.importer import importar_citas
from app.modules.citas.models import Cita
from app.modules.citas.reglas import LIMA
from app.modules.citas.router import reloj
from app.modules.ia.models import PrediccionIA
from app.modules.intervenciones.models import Intervencion

# Sábado 24/10/2026, 08:00 en Lima: el día de la cita base.
HOY = datetime(2026, 10, 24, 8, 0, tzinfo=LIMA)

BASE = {
    "id_cita_externa": "CIT-TST-000001", "paciente_anon_id": "PAC-TST-00001", "sede": "SAN_ISIDRO",
    "especialidad": "CARDIOLOGIA", "medico": "Dr. Prueba",
    "fecha_hora_cita": "2026-10-24T09:00:00-05:00", "fecha_registro_cita": "2026-10-10T10:00:00-05:00",
    "tipo_paciente": "NUEVO", "canal_origen": "WEB",
}


@pytest.fixture
def fijar_reloj():
    """Sustituye el reloj de la API (reglas «hoy» en Lima). El fixture client limpia los overrides."""
    def _fijar(momento: datetime = HOY):
        app.dependency_overrides[reloj] = lambda: momento
        return momento
    yield _fijar
    app.dependency_overrides.pop(reloj, None)


def crear_cita(db, ahora: datetime = HOY, **cambios) -> Cita:
    datos = {**BASE, **cambios}
    r = importar_citas(db, [datos], id_usuario=None, ip="127.0.0.1", origen="prueba", ahora=ahora)
    assert r.aceptadas == 1, r.detalle_rechazos
    return db.query(Cita).filter_by(id_cita_externa=datos["id_cita_externa"]).one()


def crear_prediccion(db, cita: Cita, nivel: str, prob: str, version: str = "SIM_v1", cuando=None) -> PrediccionIA:
    p = PrediccionIA(id_cita=cita.id_cita, version_modelo=version, probabilidad_no_show=Decimal(prob),
                     nivel_riesgo=nivel, umbral_aplicado=Decimal("0.450"), features_snapshot={"antelacion_dias": 1},
                     **({"fecha_hora_inferencia": cuando} if cuando else {}))
    db.add(p)
    db.flush()
    return p


def crear_intervencion(db, cita: Cita, estado: str = "PENDIENTE", respuesta=None, canal="WHATSAPP",
                       cuando=None) -> Intervencion:
    i = Intervencion(id_cita=cita.id_cita, canal_contacto=canal, plantilla_mensaje="RECORDATORIO_CONFIRMACION_V1",
                     estado_intervencion=estado, respuesta_paciente=respuesta,
                     **({"fecha_hora_envio": cuando} if cuando else {}))
    db.add(i)
    db.flush()
    return i
