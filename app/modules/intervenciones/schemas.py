from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntervencionCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    canal_contacto: Literal["WHATSAPP", "SMS", "LLAMADA_TELEFONICA"]
    plantilla_mensaje: str = Field(
        default="PLANTILLA_CONFIRMACION_PREVENTIVA",
        min_length=1,
        max_length=100,
    )
    consentimiento_optout: bool = False
    estado_intervencion: Literal["PENDIENTE", "ENVIADA", "ENTREGADA", "FALLIDA"] = "ENVIADA"


class IntervencionRespuestaIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    respuesta_paciente: Literal["CONFIRMA", "SOLICITA_LIBERACION", "SOLICITA_REPROG", "SIN_RESPUESTA"]
    consentimiento_optout: bool | None = None
    observacion: str | None = Field(default=None, max_length=255)


class IntervencionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_intervencion: int
    id_cita: int
    id_cita_externa: str = ""
    id_operador: int | None
    canal_contacto: str
    plantilla_mensaje: str
    consentimiento_optout: bool
    estado_intervencion: str
    respuesta_paciente: str | None
    fecha_hora_envio: datetime
    fecha_hora_respuesta: datetime | None
    estado_cita_actual: str | None = None
    id_cupo_liberado_generado: int | None = None
    acciones_disponibles: list[str] = Field(default_factory=list)


class CitaSugeridaIntervencionOut(BaseModel):
    id_cita: int
    id_cita_externa: str
    paciente_anon_id: str
    especialidad: str
    medico: str
    fecha_hora_cita: datetime
    franja_horaria: str
    estado_actual: str
    probabilidad_no_show: Decimal
    nivel_riesgo: str
    explicabilidad_resumen: str | None
    accion_sugerida: str
    canal_sugerido: str
    intervenciones_enviadas: int
    tiene_optout: bool


class RiesgoResumen(BaseModel):
    id_prediccion: int
    probabilidad_no_show: float
    nivel_riesgo: str
    version_modelo: str
    fecha_hora_inferencia: datetime
    resultado_simulado: bool = False


class ElegibleOut(BaseModel):
    id_cita: int
    id_cita_externa: str
    paciente_anon_id: str
    especialidad: str
    medico: str
    fecha_hora_cita: datetime
    estado_actual: str
    riesgo: RiesgoResumen
    intervenciones_previas: int = 0


class PaginaElegiblesOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[ElegibleOut]


class PaginaIntervencionesOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[IntervencionOut]
    total_sugeridas: int = 0
    total_intervenciones: int = 0
    citas_sugeridas: list[CitaSugeridaIntervencionOut] = Field(default_factory=list)
    historial_intervenciones: list[IntervencionOut] = Field(default_factory=list)


class BandejaIntervencionesOut(BaseModel):
    total_sugeridas: int
    total_intervenciones: int
    citas_sugeridas: list[CitaSugeridaIntervencionOut]
    historial_intervenciones: list[IntervencionOut]
