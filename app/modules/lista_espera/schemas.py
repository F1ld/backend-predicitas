from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidatoCreateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    paciente_anon_id: str = Field(min_length=1, max_length=50)
    especialidad_req: Literal["CARDIOLOGIA", "TRAUMATOLOGIA", "PEDIATRIA"]
    franja_preferida: Literal["MANANA", "TARDE", "INDIFERENTE"] = "INDIFERENTE"
    prioridad_registro: int = Field(default=1, ge=1, le=10)


class CandidatoUpdateIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    franja_preferida: Literal["MANANA", "TARDE", "INDIFERENTE"] | None = None
    estado_candidato: Literal["ACTIVO", "CONTACTADO", "ASIGNADO", "DESISTIDO"] | None = None
    prioridad_registro: int | None = Field(default=None, ge=1, le=10)


class CandidatoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_candidato: int
    paciente_anon_id: str
    especialidad_req: str
    franja_preferida: str
    estado_candidato: str
    prioridad_registro: int
    fecha_registro: datetime
    criterio_compatibilidad: str | None = None


class CupoLiberadoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_cupo_liberado: int
    id_cita_origen: int
    especialidad: str
    medico: str
    fecha_hora_cupo: datetime
    franja_horaria: str | None = None
    estado_cupo: str
    origen_liberacion: str
    liberado_en: datetime


class PropuestaCandidatosOut(BaseModel):
    cupo: CupoLiberadoOut
    total_compatibles: int
    candidatos: list[CandidatoOut]


class ReasignacionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id_candidato: int
    confirmacion_humana: bool
    medio_confirmacion: Literal["LLAMADA_CONFIRMADA", "PRESENCIAL"] = "LLAMADA_CONFIRMADA"
    observaciones: str | None = Field(default=None, max_length=255)


class ReasignacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_reasignacion: int
    id_cupo_liberado: int
    id_candidato: int
    id_operador_confirma: int
    confirmacion_humana: bool
    medio_confirmacion: str
    observaciones: str | None
    fecha_hora_reasigna: datetime
    estado_cupo_final: str
    estado_candidato_final: str

