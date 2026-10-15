from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

#Toda la configuración sale del .env; el código nunca lleva "secretos". La expiración es de 30 minutos (Obviamente por inactividad y tambien, el valor es configurable).

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()