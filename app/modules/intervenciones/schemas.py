from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictBool

from app.core.dominio import CANALES_CONTACTO, RESPUESTAS_PACIENTE
from app.modules.citas.schemas import CupoOut, RiesgoResumen  # formas de modulo-02 y modulo-06

__all__ = ["CupoOut", "RiesgoResumen"]


class IntervencionOut(BaseModel):
    id_intervencion: int
    id_cita: int
    id_cita_externa: str
    id_operador: int | None
    canal_contacto: str
    plantilla_mensaje: str
    consentimiento_optout: bool
    estado_intervencion: str
    respuesta_paciente: str | None
    fecha_hora_envio: datetime
    fecha_hora_respuesta: datetime | None
    acciones_disponibles: list[str]


class PaginaIntervencionesOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[IntervencionOut]


class ElegibleOut(BaseModel):
    id_cita: int
    id_cita_externa: str
    paciente_anon_id: str
    especialidad: str
    medico: str
    fecha_hora_cita: datetime
    estado_actual: str
    riesgo: RiesgoResumen
    intervenciones_previas: int


class PaginaElegiblesOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[ElegibleOut]


class IntervencionIn(BaseModel):
    """M05-E02 (RF-063, RN13, D-024). consentimiento_confirmado solo admite el booleano JSON literal:
    StrictBool rechaza 1, "true", "yes", 0 o "false" con 422 VALIDACION (sin coerción). La ausencia,
    null y false llegan al servicio, que responde 422 CONSENTIMIENTO_REQUERIDO si no es true."""

    id_cita: int
    canal_contacto: Literal[CANALES_CONTACTO]  # type: ignore[valid-type]
    plantilla_mensaje: str = Field(min_length=1, max_length=100)
    consentimiento_confirmado: StrictBool | None = None


class EstadoEnvioIn(BaseModel):
    estado_intervencion: Literal["ENVIADA", "ENTREGADA", "FALLIDA"]


class RespuestaIn(BaseModel):
    respuesta_paciente: Literal[RESPUESTAS_PACIENTE]  # type: ignore[valid-type]
    optout: bool = False


class LiberarIn(BaseModel):
    motivo: str | None = Field(default=None, max_length=255)


class PlantillaOut(BaseModel):
    id: str
    canal_contacto: str
    descripcion: str
    contenido: str


class Rep02Fila(BaseModel):
    id_intervencion: int
    id_cita_externa: str
    especialidad: str
    nivel_riesgo: str | None
    canal_contacto: str
    estado_intervencion: str
    respuesta_paciente: str | None
    tiempo_respuesta_minutos: int | None
    cupo_liberado: bool


class Rep02Resumen(BaseModel):
    enviadas: int
    entregadas: int
    respondidas: int
    confirmaciones: int
    liberaciones: int
    tasa_respuesta: float


class Rep02PorCanal(BaseModel):
    canal_contacto: str
    respuesta_paciente: str | None
    cantidad: int


class Rep02Out(BaseModel):
    resumen: Rep02Resumen
    por_canal: list[Rep02PorCanal]
    filas: list[Rep02Fila]
    resultado_simulado: bool
