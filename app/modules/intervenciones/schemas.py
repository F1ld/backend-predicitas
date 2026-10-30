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


class BandejaIntervencionesOut(BaseModel):
    total_sugeridas: int
    total_intervenciones: int
    citas_sugeridas: list[CitaSugeridaIntervencionOut]
    historial_intervenciones: list[IntervencionOut]

