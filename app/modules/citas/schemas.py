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


def _con_zona_lima(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor.replace(tzinfo=LIMA) if valor.tzinfo is None else valor  # sin zona = hora de Lima


class CitaImportIn(BaseModel):
    """Una fila de importación o un registro manual (RF-009, RF-010, RF-011 a RF-014).

    Es la única validación de entrada de citas: importador y registro manual la comparten.
    Los contadores en None significan «no informados»: los calcula el sistema (RN17).
    Las columnas extra (p. ej. target) se ignoran.
    """

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
    inasistencias_previas: int | None = Field(default=None, ge=0)
    reprogramaciones_prev: int = Field(default=0, ge=0)
    asistencias_previas: int | None = Field(default=None, ge=0)
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
        return _con_zona_lima(valor)


class CitaRegistroIn(BaseModel):
    """Cuerpo de POST /citas (M02-E03). Los dominios se validan con CitaImportIn en el servicio,
    para distinguir FUERA_DE_PERIMETRO (sede, especialidad) de VALIDACION."""

    model_config = ConfigDict(extra="forbid")

    id_cita_externa: str = Field(min_length=1, max_length=50)
    paciente_anon_id: str = Field(min_length=1, max_length=50)
    sede: str
    especialidad: str
    medico: str = Field(min_length=1, max_length=100)
    fecha_hora_cita: datetime
    fecha_registro_cita: datetime
    tipo_paciente: str
    canal_origen: str
    inasistencias_previas: int | None = Field(default=None, ge=0)
    asistencias_previas: int | None = Field(default=None, ge=0)
    reprogramaciones_prev: int = Field(default=0, ge=0)


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


class RiesgoResumen(BaseModel):
    id_prediccion: int
    probabilidad_no_show: float
    nivel_riesgo: str
    version_modelo: str
    fecha_hora_inferencia: datetime
    resultado_simulado: bool


class CitaResumenOut(CitaOut):
    riesgo: RiesgoResumen | None
    estado_intervencion: str | None
    respuesta_paciente: str | None
    tiene_check_in: bool


class HistorialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_historial: int
    id_usuario_actor: int | None
    estado_anterior: str | None
    estado_nuevo: str
    motivo_cambio: str | None
    fecha_hora_evento: datetime


class CheckInOut(BaseModel):
    fecha_hora_check_in: datetime
    id_usuario: int


class PrediccionOut(BaseModel):
    """Forma de contratos/modulo-09.json, construida desde predicciones_ia."""

    id_prediccion: int
    id_cita: int
    version_modelo: str
    probabilidad_no_show: float
    nivel_riesgo: str
    umbral_aplicado: float
    features_snapshot: dict
    explicabilidad_resumen: str | None
    fecha_hora_inferencia: datetime
    resultado_simulado: bool
    ya_existia: bool


class IntervencionOut(BaseModel):
    """Forma de contratos/modulo-05.json, construida desde intervenciones."""

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


class OfertaOut(BaseModel):
    id_candidato: int
    paciente_anon_id: str
    id_operador: int
    fecha_hora_oferta: datetime


class CupoOut(BaseModel):
    """Forma de contratos/modulo-06.json, construida desde cupos_liberados."""

    id_cupo_liberado: int
    id_cita_origen: int
    id_cita_externa_origen: str
    especialidad: str
    medico: str
    fecha_hora_cupo: datetime
    franja_horaria: str
    estado_cupo: str
    origen_liberacion: str
    liberado_en: datetime
    oferta_vigente: OfertaOut | None


class ReasignacionOut(BaseModel):
    id_reasignacion: int
    id_cupo_liberado: int
    id_candidato: int
    paciente_anon_id: str
    id_operador_confirma: int
    confirmacion_humana: bool
    medio_confirmacion: str
    observaciones: str | None
    fecha_hora_reasigna: datetime


class CitaDetalleOut(CitaOut):
    historial: list[HistorialOut]
    check_in: CheckInOut | None
    predicciones: list[PrediccionOut]
    intervenciones: list[IntervencionOut]
    cupo_liberado: CupoOut | None
    reasignacion: ReasignacionOut | None


class PaginaCitasOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[CitaResumenOut]


class CambioEstadoIn(BaseModel):
    estado_nuevo: Literal["CONFIRMADA", "REPROGRAMADA", "CANCELADA", "ATENDIDA", "NO_SHOW"]
    motivo: str | None = Field(default=None, max_length=255)
    nueva_fecha_hora_cita: datetime | None = None
    liberar_cupo: bool | None = None
    id_intervencion: int | None = None

    @field_validator("nueva_fecha_hora_cita", mode="after")
    @classmethod
    def _con_zona(cls, valor: datetime | None) -> datetime | None:
        return _con_zona_lima(valor)


class CheckInIn(BaseModel):
    observacion: str | None = Field(default=None, max_length=255)


class CatalogosOut(BaseModel):
    especialidades: list[str]
    estados: list[str]
    niveles_riesgo: list[str]
    medicos: list[str]
    canales_origen: list[str]
    tipos_paciente: list[str]


class RechazoOut(BaseModel):
    fila: int
    id_cita_externa: str
    motivos: list[str]


class ResultadoImportacionOut(BaseModel):
    recibidas: int
    aceptadas: int
    rechazadas: int
    detalle_rechazos: list[RechazoOut]
