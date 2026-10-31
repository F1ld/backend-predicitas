from typing import Any
from pydantic import BaseModel


class ResumenRep02(BaseModel):
    enviadas: int
    entregadas: int
    respondidas: int
    confirmaciones: int
    liberaciones: int
    tasa_respuesta: float


class PorCanalRep02(BaseModel):
    canal_contacto: str
    respuesta_paciente: str | None = None
    cantidad: int


class Rep02Fila(BaseModel):
    id_intervencion: int
    id_cita_externa: str
    especialidad: str
    nivel_riesgo: str | None = None
    canal_contacto: str
    estado_intervencion: str
    respuesta_paciente: str | None = None
    tiempo_respuesta_minutos: int | None = None
    cupo_liberado: bool


class Rep02Out(BaseModel):
    resumen: ResumenRep02
    por_canal: list[PorCanalRep02]
    filas: list[Rep02Fila]
    resultado_simulado: bool = False


class ResumenRep03(BaseModel):
    cupos_liberados: int
    cupos_reasignados: int
    tasa_recuperacion: float
    horas_promedio_matching: float | None = None


class PorEspecialidadRep03(BaseModel):
    especialidad: str
    liberados: int
    reasignados: int


class Rep03Fila(BaseModel):
    id_cupo_liberado: int
    fecha_hora_cupo: str
    especialidad: str
    medico: str
    horas_disponible: float
    paciente_anon_id_asignado: str | None = None
    id_operador_confirma: int | None = None
    estado_cupo: str


class Rep03Out(BaseModel):
    resumen: ResumenRep03
    por_especialidad: list[PorEspecialidadRep03]
    filas: list[Rep03Fila]
