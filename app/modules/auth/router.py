"""Endpoints M01-E01 a M01-E05 (contratos/modulo-01.json)."""
from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http import ip_cliente
from app.modules.auth import service
from app.modules.auth.dependencies import usuario_actual
from app.modules.auth.models import Usuario
from app.modules.auth.schemas import CambioClaveIn, TokenOut, UsuarioOut

router = APIRouter(prefix="/auth", tags=["autenticación"])


@router.post("/login", response_model=TokenOut)
def login(
    request: Request,
    formulario: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """M01-E01 · RF-001, RNF-005: 401 genérico y 429 tras demasiados fallos."""
    token, segundos = service.autenticar(db, formulario.username, formulario.password, ip_cliente(request))
    return TokenOut(access_token=token, expires_in=segundos)


@router.get("/me", response_model=UsuarioOut)
def me(usuario: Usuario = Depends(usuario_actual)):
    """M01-E02."""
    return usuario


@router.post("/logout", status_code=204)
def logout(request: Request, usuario: Usuario = Depends(usuario_actual), db: Session = Depends(get_db)):
    """M01-E03 · RF-002, RNF-004: los tokens emitidos antes dejan de valer."""
    service.cerrar_sesion(db, usuario, ip_cliente(request))
    return Response(status_code=204)


@router.post("/renovar", response_model=TokenOut)
def renovar(usuario: Usuario = Depends(usuario_actual)):
    """M01-E04 · RNF-004: token nuevo; el anterior vale hasta su exp."""
    token, segundos = service.renovar(usuario)
    return TokenOut(access_token=token, expires_in=segundos)


@router.post("/cambiar-clave", response_model=TokenOut)
def cambiar_clave(
    datos: CambioClaveIn,
    request: Request,
    usuario: Usuario = Depends(usuario_actual),
    db: Session = Depends(get_db),
):
    """M01-E05 · RF-008: invalida los tokens anteriores y entrega uno nuevo."""
    token, segundos = service.cambiar_clave(db, usuario, datos.clave_actual, datos.clave_nueva,
                                            ip_cliente(request))
    return TokenOut(access_token=token, expires_in=segundos)
