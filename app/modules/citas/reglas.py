from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.dominio import DIAS_SEMANA

LIMA = ZoneInfo("America/Lima")

# Estados con los que puede ingresar una cita al piloto. LIBERADA queda fuera:
# exige un cupo liberado formal (flujo de Intervención).
ESTADOS_IMPORTABLES = ("RECIBIDA", "CONFIRMADA", "REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW")

# Estados no finales: admiten cambios, check-in y liberación.
ESTADOS_ACTIVOS = ("RECIBIDA", "CONFIRMADA", "REPROGRAMADA")

# Desenlace final -> valor del target (0 = asistió, 1 = no asistió).
ESTADOS_DESENLACE = {"ATENDIDA": 0, "NO_SHOW": 1}

# Transiciones permitidas (F-06). Los estados que no figuran como clave
# (CANCELADA, LIBERADA, ATENDIDA, NO_SHOW) son finales. LIBERADA solo la usa
# el servicio interno `transicionar` (F-09), nunca el endpoint de cambio de estado.
TRANSICIONES = {
    "RECIBIDA": {"CONFIRMADA", "REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW", "LIBERADA"},
    "CONFIRMADA": {"REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW", "LIBERADA"},
    "REPROGRAMADA": {"CONFIRMADA", "REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW", "LIBERADA"},  # D-011
}

# Evento de auditoría que representa la llegada del paciente (D-012, RF-104).
ACCION_CHECK_IN = "CHECK_IN"


class FechasInconsistentes(ValueError):
    """fecha_registro_cita posterior a fecha_hora_cita."""


class FechaEnDomingo(ValueError):
    """La cita cae en domingo, fuera de los días del piloto."""


def ahora_lima() -> datetime:
    """Reloj de la aplicación en hora de Lima. Las pruebas lo sustituyen (router.reloj)."""
    return datetime.now(LIMA)


def fecha_lima(momento: datetime):
    return momento.astimezone(LIMA).date()


def derivar_variables(fecha_hora_cita: datetime, fecha_registro_cita: datetime) -> dict:
    """Calcula antelación, franja y día en hora de Lima. Lanza ValueError si no es válida."""
    cita = fecha_hora_cita.astimezone(LIMA)
    registro = fecha_registro_cita.astimezone(LIMA)
    antelacion = (cita.date() - registro.date()).days
    if antelacion < 0:
        raise FechasInconsistentes("fecha_registro_cita es posterior a fecha_hora_cita")
    if cita.weekday() == 6:
        raise FechaEnDomingo("la cita cae en domingo (fuera de los días del piloto)")
    return {
        "antelacion_dias": antelacion,
        "franja_horaria": franja_de(cita),
        "dia_semana": DIAS_SEMANA[cita.weekday()],
    }


def franja_de(momento: datetime) -> str:
    return "MANANA" if momento.astimezone(LIMA).hour < 13 else "TARDE"


def contar_previos(desenlaces: list[tuple[datetime, str]], fecha_registro_cita: datetime) -> tuple[int, int]:
    """RN17 (reglas-de-negocio §4.3): cuenta (inasistencias, asistencias) del paciente usando
    solo citas con desenlace cuya fecha_hora_cita es anterior al registro de la nueva cita."""
    previas = [estado for fecha, estado in desenlaces if fecha < fecha_registro_cita]
    return previas.count("NO_SHOW"), previas.count("ATENDIDA")
