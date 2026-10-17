from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http import ip_cliente
from app.modules.auditoria.service import registrar_evento
from app.modules.auth import service
from app.modules.auth.dependencies import usuario_actual
from app.modules.auth.models import Usuario
from app.modules.auth.schemas import TokenOut, UsuarioOut

router = APIRouter(prefix="/auth", tags=["autenticación"])


@router.post("/login", response_model=TokenOut)
def login(
    request: Request,
    formulario: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    token, segundos = service.autenticar(db, formulario.username, formulario.password, ip_cliente(request))
    return TokenOut(access_token=token, expires_in=segundos)


@router.get("/me", response_model=UsuarioOut)
def me(usuario: Usuario = Depends(usuario_actual)):
    return usuario


@router.post("/logout", status_code=204)
def logout(request: Request, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    registrar_evento(
        db, modulo="AUTENTICACION", accion="LOGOUT", entidad_afectada="usuarios",
        direccion_ip=ip_cliente(request), id_usuario=usuario.id_usuario, id_entidad=usuario.id_usuario,
    )
    db.commit()
    return Response(status_code=204)