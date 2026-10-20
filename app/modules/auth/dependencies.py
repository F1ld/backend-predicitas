"""Dependencias de sesión y permisos (F-02, D-010, RF-003, RNF-001).

- Sin token → 401 NO_AUTENTICADO (lo lanza OAuth2PasswordBearer y lo traduce el manejador común).
- Token vencido, inválido o invalidado, o usuario inactivo → 401 SESION_INVALIDA.
- Rol sin permiso → 403 SIN_PERMISO.
"""
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errores import SinPermiso
from app.modules.auth import service
from app.modules.auth.models import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def usuario_actual(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Usuario:
    return service.usuario_de_token(db, token)


def requiere_roles(*roles: str):
    def _dependencia(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
        if usuario.rol not in roles:
            raise SinPermiso("No tiene permisos para esta operación")
        return usuario

    return _dependencia
