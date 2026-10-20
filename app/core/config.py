"""Configuración del backend (contratos/comun.json → variables_entorno_backend).

Toda la configuración sale del entorno o del archivo .env; el código nunca lleva secretos.
Los valores por defecto son los del contrato. DATABASE_URL y SECRET_KEY son obligatorias.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"

    # Base de datos (D-015): la app usa el rol predicitas_app; Alembic y los scripts, el rol dueño.
    database_url: str
    database_url_migraciones: str | None = None

    # Autenticación. La sesión expira a los 30 minutos (configurable).
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    login_max_intentos: int = 5
    login_ventana_minutos: int = 15
    login_bloqueo_minutos: int = 15

    # Motor de IA (servicio de inferencia o simulador).
    ia_url: str = "http://ia:8100"
    ia_api_key: str | None = None
    ia_timeout_segundos: float = 5
    ia_corte_medio: float = 0.30

    intervencion_modo_sombra: bool = False

    # Orígenes permitidos por CORS, separados por comas.
    cors_origenes: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def lista_cors_origenes(self) -> list[str]:
        return [o.strip() for o in self.cors_origenes.split(",") if o.strip()]

    @property
    def url_migraciones(self) -> str:
        """Alembic usa DATABASE_URL_MIGRACIONES si existe; si no, DATABASE_URL."""
        return self.database_url_migraciones or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
