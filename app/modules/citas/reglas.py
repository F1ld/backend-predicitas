from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.dominio import DIAS_SEMANA

LIMA = ZoneInfo("America/Lima")

# Estados con los que puede ingresar una cita al piloto. LIBERADA queda fuera:
# exige un cupo liberado formal (flujo de Intervención).
ESTADOS_IMPORTABLES = ("RECIBIDA", "CONFIRMADA", "REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW")

# Desenlace final -> valor del target (0 = asistió, 1 = no asistió).
ESTADOS_DESENLACE = {"ATENDIDA": 0, "NO_SHOW": 1}

# Transiciones permitidas por el endpoint de cambio de estado. Los estados
# que no figuran como clave (CANCELADA, LIBERADA, ATENDIDA, NO_SHOW) son finales.
TRANSICIONES = {
    "RECIBIDA": {"CONFIRMADA", "REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW"},
    "CONFIRMADA": {"REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW"},
    "REPROGRAMADA": {"CONFIRMADA", "CANCELADA", "ATENDIDA", "NO_SHOW"},
}


def derivar_variables(fecha_hora_cita: datetime, fecha_registro_cita: datetime) -> dict:
    """Calcula antelación, franja y día en hora de Lima. Lanza ValueError si no es válida."""
    cita = fecha_hora_cita.astimezone(LIMA)
    registro = fecha_registro_cita.astimezone(LIMA)
    antelacion = (cita.date() - registro.date()).days
    if antelacion < 0:
        raise ValueError("fecha_registro_cita es posterior a fecha_hora_cita")
    if cita.weekday() == 6:
        raise ValueError("la cita cae en domingo (fuera de los días del piloto)")
    return {
        "antelacion_dias": antelacion,
        "franja_horaria": "MANANA" if cita.hour < 13 else "TARDE",
        "dia_semana": DIAS_SEMANA[cita.weekday()],
    }