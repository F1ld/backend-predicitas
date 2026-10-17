from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errores import NoAutenticado, SinPermiso
from app.core.security import decodificar_token
from app.modules.auth import repository
from app.modules.auth.models import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def usuario_actual(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Usuario:
    payload = decodificar_token(token)
    try:
        id_usuario = int(payload["sub"]) if payload else None
    except (KeyError, ValueError):
        id_usuario = None
    if id_usuario is None:
        raise NoAutenticado("Token inválido o expirado")

    usuario = repository.por_id(db, id_usuario)
    if usuario is None or not usuario.activo:
        raise NoAutenticado("Usuario inexistente o inactivo")
    return usuario


def requiere_roles(*roles: str):
    def _dependencia(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if usuario.rol not in roles:
            raise SinPermiso("No tiene permisos para esta operación")
        return usuario

    return _dependencia