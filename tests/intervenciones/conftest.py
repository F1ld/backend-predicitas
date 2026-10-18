"""Utilidades de las pruebas de M05: reloj fijo, modo sombra y datos sintéticos (PAC-TST-*)."""
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
from app.modules.intervenciones.router import modo_sombra

# Sábado 24/10/2026, 08:00 en Lima. La cita base es el martes 27/10 a las 09:00.
HOY = datetime(2026, 10, 24, 8, 0, tzinfo=LIMA)

BASE = {
    "id_cita_externa": "CIT-TST-I0001", "paciente_anon_id": "PAC-TST-I0001", "sede": "SAN_ISIDRO",
    "especialidad": "CARDIOLOGIA", "medico": "Dr. Prueba",
    "fecha_hora_cita": "2026-10-27T09:00:00-05:00", "fecha_registro_cita": "2026-10-10T10:00:00-05:00",
    "tipo_paciente": "NUEVO", "canal_origen": "WEB",
}
NUEVA = {"canal_contacto": "WHATSAPP", "plantilla_mensaje": "RECORDATORIO_CONFIRMACION_V1",
         "consentimiento_confirmado": True}


@pytest.fixture(autouse=True)
def entorno():
    """Reloj fijo en HOY y modo sombra apagado, salvo que la prueba los cambie."""
    app.dependency_overrides[reloj] = lambda: HOY
    app.dependency_overrides[modo_sombra] = lambda: False
    yield
    app.dependency_overrides.pop(reloj, None)
    app.dependency_overrides.pop(modo_sombra, None)


def crear_cita(db, nivel: str | None = "ALTO", **cambios) -> Cita:
    datos = {**BASE, **cambios}
    r = importar_citas(db, [datos], id_usuario=None, ip="127.0.0.1", origen="prueba", ahora=HOY)
    assert r.aceptadas == 1, r.detalle_rechazos
    cita = db.query(Cita).filter_by(id_cita_externa=datos["id_cita_externa"]).one()
    if nivel:
        crear_prediccion(db, cita, nivel)
    return cita


def crear_prediccion(db, cita: Cita, nivel: str, prob: str = "0.600", cuando: datetime | None = None) -> PrediccionIA:
    p = PrediccionIA(id_cita=cita.id_cita, version_modelo=f"SIM_{nivel}_{prob}", probabilidad_no_show=Decimal(prob),
                     nivel_riesgo=nivel, umbral_aplicado=Decimal("0.450"), features_snapshot={"antelacion_dias": 17},
                     **({"fecha_hora_inferencia": cuando} if cuando else {}))
    db.add(p)
    db.flush()
    return p


def crear_intervencion(db, cita: Cita, estado: str = "PENDIENTE", respuesta=None, canal="WHATSAPP",
                       optout=False, **extra) -> Intervencion:
    i = Intervencion(id_cita=cita.id_cita, canal_contacto=canal, plantilla_mensaje="RECORDATORIO_CONFIRMACION_V1",
                     estado_intervencion=estado, respuesta_paciente=respuesta, consentimiento_optout=optout, **extra)
    db.add(i)
    db.flush()
    return i
