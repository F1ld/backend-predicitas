"""Endpoints M01-E06 a M01-E11 (contratos/modulo-01.json). Solo ADMINISTRADOR (RF-003)."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.auth.schemas import UsuarioOut
from app.modules.usuarios import service
from app.modules.usuarios.schemas import (
    ClaveTemporalOut, EstadoIn, FiltrosUsuarios, PaginaUsuariosOut, Rol, UsuarioCrearIn, UsuarioEditarIn,
)

router = APIRouter(prefix="/usuarios", tags=["usuarios"])
solo_admin = requiere_roles("ADMINISTRADOR")


@router.get("", response_model=PaginaUsuariosOut)
def listar(
    q: str | None = Query(default=None, max_length=100),
    rol: Rol | None = None,
    activo: bool | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(solo_admin),
    db: Session = Depends(get_db),
):
    """M01-E06 · RF-007: ordenada por nombre_completo."""
    filtros = FiltrosUsuarios(q=q, rol=rol, activo=activo, limite=limite, desplazamiento=desplazamiento)
    return service.listar(db, filtros)


@router.post("", response_model=UsuarioOut, status_code=201)
def crear(datos: UsuarioCrearIn, request: Request, actor: Usuario = Depends(solo_admin),
          db: Session = Depends(get_db)):
    """M01-E07 · RF-004."""
    return service.crear(db, datos, actor, ip_cliente(request))


@router.get("/{id_usuario}", response_model=UsuarioOut)
def obtener(id_usuario: int, _: Usuario = Depends(solo_admin), db: Session = Depends(get_db)):
    """M01-E08."""
    return service.obtener(db, id_usuario)


@router.patch("/{id_usuario}", response_model=UsuarioOut)
def editar(id_usuario: int, datos: UsuarioEditarIn, request: Request, actor: Usuario = Depends(solo_admin),
           db: Session = Depends(get_db)):
    """M01-E09 · RF-005."""
    return service.editar(db, id_usuario, datos, actor, ip_cliente(request))


@router.post("/{id_usuario}/estado", response_model=UsuarioOut)
def cambiar_estado(id_usuario: int, datos: EstadoIn, request: Request, actor: Usuario = Depends(solo_admin),
                   db: Session = Depends(get_db)):
    """M01-E10 · RF-006."""
    return service.cambiar_estado(db, id_usuario, datos, actor, ip_cliente(request))


@router.post("/{id_usuario}/restablecer-acceso", response_model=ClaveTemporalOut)
def restablecer_acceso(id_usuario: int, request: Request, actor: Usuario = Depends(solo_admin),
                       db: Session = Depends(get_db)):
    """M01-E11 · RF-008: la clave temporal se muestra una sola vez."""
    return service.restablecer_acceso(db, id_usuario, actor, ip_cliente(request))
