from pydantic import BaseModel, ConfigDict


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id_usuario: int
    nombre_completo: str
    correo_institucional: str
    rol: str
    activo: bool