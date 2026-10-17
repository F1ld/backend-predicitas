from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.dominio import CANALES_ORIGEN, ESPECIALIDADES, SEDES, TIPOS_PACIENTE
from app.modules.citas.reglas import ESTADOS_IMPORTABLES, LIMA

_DOMINIOS = {
    "sede": SEDES,
    "especialidad": ESPECIALIDADES,
    "tipo_paciente": TIPOS_PACIENTE,
    "canal_origen": CANALES_ORIGEN,
    "estado_actual": ESTADOS_IMPORTABLES,
}


class CitaImportIn(BaseModel):
    """Una fila de importación. Las columnas extra (p. ej. target) se ignoran."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id_cita_externa: str = Field(min_length=1, max_length=50)
    paciente_anon_id: str = Field(min_length=1, max_length=50)
    sede: str
    especialidad: str
    medico: str = Field(min_length=1, max_length=100)
    fecha_hora_cita: datetime
    fecha_registro_cita: datetime
    tipo_paciente: str
    canal_origen: str
    inasistencias_previas: int = Field(default=0, ge=0)
    reprogramaciones_prev: int = Field(default=0, ge=0)
    asistencias_previas: int = Field(default=0, ge=0)
    estado_actual: str = "RECIBIDA"

    @field_validator(*_DOMINIOS, mode="before")
    @classmethod
    def _validar_dominio(cls, valor, info):
        if not isinstance(valor, str):
            raise ValueError("debe ser texto")
        valor = valor.strip().upper()
        validos = _DOMINIOS[info.field_name]
        if valor not in validos:
            raise ValueError(f"valor fuera del dominio permitido: {valor!r} (permitidos: {', '.join(validos)})")
        return valor

    @field_validator("fecha_hora_cita", "fecha_registro_cita", mode="after")
    @classmethod
    def _con_zona(cls, valor: datetime) -> datetime:
        return valor.replace(tzinfo=LIMA) if valor.tzinfo is None else valor  # sin zona = hora de Lima


class CitaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_cita: int
    id_cita_externa: str
    paciente_anon_id: str
    sede: str
    especialidad: str
    medico: str
    fecha_hora_cita: datetime
    fecha_registro_cita: datetime
    antelacion_dias: int
    tipo_paciente: str
    canal_origen: str
    franja_horaria: str
    dia_semana: str
    inasistencias_previas: int
    reprogramaciones_prev: int
    asistencias_previas: int
    estado_actual: str
    target_no_show: int | None


class HistorialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_historial: int
    id_usuario_actor: int | None
    estado_anterior: str | None
    estado_nuevo: str
    motivo_cambio: str | None
    fecha_hora_evento: datetime


class CitaDetalleOut(CitaOut):
    historial: list[HistorialOut]


class PaginaCitasOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[CitaOut]


class CambioEstadoIn(BaseModel):
    estado_nuevo: Literal["CONFIRMADA", "REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW"]
    motivo: str | None = Field(default=None, max_length=255)


class RechazoOut(BaseModel):
    fila: int
    id_cita_externa: str
    motivos: list[str]


class ResultadoImportacionOut(BaseModel):
    recibidas: int
    aceptadas: int
    rechazadas: int
    detalle_rechazos: list[RechazoOut]