"""Esquemas de gestión de usuarios (contratos/modulo-01.json → M01-E06 a M01-E11, validaciones)."""
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.modules.auth.schemas import Clave, UsuarioOut

Rol = Literal["ADMINISTRADOR", "RECEPCION", "TECNICO_IA"]

# 2..120 caracteres; los espacios al borde se quitan antes de medir.
NombreCompleto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


def _correo_normalizado(correo: str) -> str:
    correo = correo.strip().lower()
    if len(correo) > 100:
        raise ValueError("Máximo 100 caracteres")
    return correo


Correo = Annotated[EmailStr, AfterValidator(_correo_normalizado)]


class UsuarioCrearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre_completo: NombreCompleto
    correo_institucional: Correo
    rol: Rol
    clave_inicial: Clave


class UsuarioEditarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre_completo: NombreCompleto | None = None
    rol: Rol | None = None


class EstadoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activo: bool


class ClaveTemporalOut(BaseModel):
    id_usuario: int
    clave_temporal: str


class PaginaUsuariosOut(BaseModel):
    total: int
    limite: int
    desplazamiento: int
    items: list[UsuarioOut]


class FiltrosUsuarios(BaseModel):
    q: str | None = Field(default=None, max_length=100)
    rol: Rol | None = None
    activo: bool | None = None
    limite: int = Field(default=50, ge=1, le=200)
    desplazamiento: int = Field(default=0, ge=0)
