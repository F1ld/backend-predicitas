"""Cliente del servicio de inferencia (contratos/servicio-inferencia.json, contratos/modulo-09.json →
cliente_del_servicio).

Habla con IA_URL usando httpx, con timeout IA_TIMEOUT_SEGUNDOS y la cabecera X-API-Key si
IA_API_KEY está definida. Cualquier problema (conexión rechazada, timeout, 5xx, 4xx o una
respuesta que no cumple el contrato) se convierte en MotorIANoDisponible (503): quien llama
nunca ve una excepción de httpx ni un dato a medias (RF-103, RNF-015).
"""
import time
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.core.errores import MotorIANoDisponible

MENSAJE_NO_DISPONIBLE = "El servicio de inferencia no está disponible. Inténtalo más tarde."


class ModeloServicio(BaseModel):
    """Respuesta de GET /v1/modelo (IA-E02)."""
    version_modelo: str = Field(min_length=1, max_length=30)
    umbral: float = Field(ge=0, le=1)
    habilitado_piloto: bool
    resultado_simulado: bool
    version_dataset: str
    fecha_aprobacion: str | None = None
    variables: list[str]


class PrediccionServicio(BaseModel):
    """Respuesta de POST /v1/predicciones (IA-E03)."""
    id_cita: int
    probabilidad_no_show: float = Field(ge=0, le=1)
    version_modelo: str = Field(min_length=1, max_length=30)
    umbral: float = Field(ge=0, le=1)
    explicabilidad_resumen: str | None = Field(default=None, max_length=255)
    resultado_simulado: bool


class Variables(BaseModel):
    """Variables que se envían (reglas-de-negocio §4.2). Solo datos disponibles al inferir (RN17)."""
    especialidad: Literal["CARDIOLOGIA", "TRAUMATOLOGIA", "PEDIATRIA"]
    tipo_paciente: Literal["NUEVO", "CONTINUADOR"]
    antelacion_dias: int = Field(ge=0)
    canal_origen: Literal["WEB", "CALL_CENTER", "PRESENCIAL"]
    franja_horaria: Literal["MANANA", "TARDE"]
    dia_semana: Literal["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO"]
    inasistencias_previas: int = Field(ge=0)
    reprogramaciones_prev: int = Field(ge=0)
    asistencias_previas: int = Field(ge=0)
    confirmada: bool


class ClienteIA:
    """`transporte` permite inyectar httpx.MockTransport en las pruebas."""

    def __init__(self, transporte: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        cabeceras = {"X-API-Key": s.ia_api_key} if s.ia_api_key else {}
        self._http = httpx.Client(base_url=s.ia_url.rstrip("/"), timeout=s.ia_timeout_segundos,
                                  headers=cabeceras, transport=transporte)
        self.ultima_latencia_ms: int | None = None

    def close(self) -> None:
        self._http.close()

    def _pedir(self, metodo: str, ruta: str, **kwargs) -> dict:
        inicio = time.perf_counter()
        try:
            respuesta = self._http.request(metodo, ruta, **kwargs)
            respuesta.raise_for_status()
            datos = respuesta.json()
        except (httpx.HTTPError, ValueError):
            raise MotorIANoDisponible(MENSAJE_NO_DISPONIBLE) from None
        finally:
            self.ultima_latencia_ms = round((time.perf_counter() - inicio) * 1000)
        return datos

    def obtener_modelo(self) -> ModeloServicio:
        try:
            return ModeloServicio.model_validate(self._pedir("GET", "/v1/modelo"))
        except ValidationError:
            raise MotorIANoDisponible(MENSAJE_NO_DISPONIBLE) from None

    def predecir(self, id_cita: int, variables: Variables) -> PrediccionServicio:
        cuerpo = {"id_cita": id_cita, "variables": variables.model_dump()}
        try:
            prediccion = PrediccionServicio.model_validate(self._pedir("POST", "/v1/predicciones", json=cuerpo))
        except ValidationError:
            raise MotorIANoDisponible(MENSAJE_NO_DISPONIBLE) from None
        if prediccion.id_cita != id_cita:  # el eco no coincide: respuesta fuera de contrato
            raise MotorIANoDisponible(MENSAJE_NO_DISPONIBLE)
        return prediccion


def get_cliente():
    """Dependencia de FastAPI: un cliente por petición. Las pruebas la sustituyen."""
    cliente = ClienteIA()
    try:
        yield cliente
    finally:
        cliente.close()
