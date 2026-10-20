"""Esquemas de autenticación (contratos/modulo-01.json → tipos y validaciones)."""
from datetime import datetime

from pydantic import AfterValidator, BaseModel, ConfigDict
from typing import Annotated

CLAVE_MIN, CLAVE_MAX = 8, 128


def validar_clave(clave: str) -> str:
    """Política de contraseña (F-03): 8..128 caracteres, al menos una letra y un número."""
    if not CLAVE_MIN <= len(clave) <= CLAVE_MAX:
        raise ValueError(f"Debe tener entre {CLAVE_MIN} y {CLAVE_MAX} caracteres")
    if not any(c.isalpha() for c in clave) or not any(c.isdigit() for c in clave):
        raise ValueError("Debe incluir al menos una letra y un número")
    return clave


Clave = Annotated[str, AfterValidator(validar_clave)]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos


class UsuarioOut(BaseModel):
    """Nunca incluye password_hash (RNF-002)."""
    model_config = ConfigDict(from_attributes=True)

    id_usuario: int
    nombre_completo: str
    correo_institucional: str
    rol: str
    activo: bool
    creado_en: datetime
    actualizado_en: datetime | None


class CambioClaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clave_actual: str
    clave_nueva: Clave
