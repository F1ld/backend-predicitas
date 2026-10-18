"""Reglas puras de M05 · Intervención inteligente (reglas-de-negocio F-09, D-013).

Sin acceso a base de datos: se prueban solas y las usan el servicio y el repositorio.
"""
from app.modules.citas.reglas import ESTADOS_ACTIVOS

# Riesgo que habilita el acompañamiento (RF-057). Nunca prioriza ni restringe la atención (RN12).
NIVELES_ELEGIBLES = ("ALTO", "MEDIO")

# Envío simulado (RF-059, RF-061): contratos/modulo-05.json → M05-E05.transiciones.
TRANSICIONES_ENVIO = {
    "PENDIENTE": {"ENVIADA", "FALLIDA"},
    "ENVIADA": {"ENTREGADA", "FALLIDA"},
}

# Límite de mensajes (RN07, RNF-032, RF-066): una intervención que llegue al paciente
# y un único reintento tras FALLIDA. Mientras haya una no fallida, no se crea otra.
MAX_FALLIDAS = 2

# Catálogo fijo (diccionario → catalogos.plantilla_mensaje). Una plantilla por canal admitido.
PLANTILLAS = (
    ("RECORDATORIO_CONFIRMACION_V1", ("WHATSAPP", "SMS"), "Recordatorio de la cita con pedido de confirmación"),
    ("RECORDATORIO_LIBERACION_V1", ("WHATSAPP", "SMS"), "Recordatorio con la opción de ceder el cupo"),
    ("LLAMADA_GUION_V1", ("LLAMADA_TELEFONICA",), "Guion de llamada de recordatorio y confirmación"),
)
CONTENIDO_PENDIENTE = "[PENDIENTE: contenido aprobado]"


def canales_de(plantilla: str) -> tuple[str, ...]:
    for nombre, canales, _ in PLANTILLAS:
        if nombre == plantilla:
            return canales
    return ()


def puede_crear_otra(estados_previos: list[str]) -> bool:
    """RF-066: True si la cita admite una intervención nueva."""
    if any(estado != "FALLIDA" for estado in estados_previos):
        return False
    return len(estados_previos) < MAX_FALLIDAS


def admite_respuesta(estado: str, canal: str) -> bool:
    """RF-062: desde ENTREGADA, o desde ENVIADA en una llamada telefónica."""
    return estado == "ENTREGADA" or (estado == "ENVIADA" and canal == "LLAMADA_TELEFONICA")


def acciones_disponibles(estado: str, canal: str, respuesta: str | None, optout: bool,
                         estado_cita: str) -> list[str]:
    """Botones de la vista de seguimiento (M05-V03), en el orden del contrato."""
    acciones = []
    if estado == "PENDIENTE":
        acciones.append("REGISTRAR_ENVIO")
    if estado in TRANSICIONES_ENVIO and "ENTREGADA" in TRANSICIONES_ENVIO[estado]:
        acciones.append("REGISTRAR_ENTREGA")
    if estado in TRANSICIONES_ENVIO:
        acciones.append("REGISTRAR_FALLO")
    if admite_respuesta(estado, canal):
        acciones.append("REGISTRAR_RESPUESTA")
    if estado == "RESPONDIDA" and not optout:
        acciones.append("REGISTRAR_OPTOUT")
    if estado == "RESPONDIDA" and estado_cita in ESTADOS_ACTIVOS:
        if respuesta == "CONFIRMA" and estado_cita != "CONFIRMADA":
            acciones.append("CONFIRMAR_CITA")
        if respuesta == "SOLICITA_LIBERACION":
            acciones.append("LIBERAR_CUPO")
    return acciones
