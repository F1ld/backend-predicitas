"""Esquemas de M09 (contratos/modulo-09.json → tipos)."""
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_serializer, field_validator

Especialidad = Literal["CARDIOLOGIA", "TRAUMATOLOGIA", "PEDIATRIA"]
NivelRiesgo = Literal["BAJO", "MEDIO", "ALTO"]
MAX_DIAS_LOTE = 14


class PrediccionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    ya_existia: bool = False

    @field_serializer("probabilidad_no_show", "umbral_aplicado")
    def _tres_decimales(self, valor: float) -> float:
        return round(float(valor), 3)


class PaginaPrediccionesOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[PrediccionOut]


class ModeloActivoOut(BaseModel):
    """GET /v1/modelo del servicio + disponibilidad. Si el servicio no responde, solo los 3 últimos."""
    version_modelo: str | None = None
    umbral: float | None = None
    habilitado_piloto: bool | None = None
    resultado_simulado: bool | None = None
    version_dataset: str | None = None
    fecha_aprobacion: str | None = None
    variables: list[str] | None = None
    disponible: bool
    latencia_ms: int | None
    corte_medio: float


class LoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desde: date
    hasta: date
    especialidad: Especialidad | None = None

    @field_validator("hasta")
    @classmethod
    def _rango(cls, hasta: date, info: ValidationInfo) -> date:
        desde = info.data.get("desde")
        if desde is not None and hasta < desde:
            raise ValueError("hasta debe ser igual o posterior a desde")
        if desde is not None and hasta > desde + timedelta(days=MAX_DIAS_LOTE):
            raise ValueError(f"hasta puede ser como máximo {MAX_DIAS_LOTE} días después de desde")
        return hasta


class FallaLote(BaseModel):
    id_cita: int
    codigo: str


class LoteOut(BaseModel):
    evaluadas: int = 0
    nuevas: int = 0
    existentes: int = 0
    no_elegibles: int = 0
    fallidas: int = 0
    detalle_fallas: list[FallaLote] = []
    version_modelo: str | None = None
    resultado_simulado: bool = True
