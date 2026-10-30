from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.intervenciones import repository, service
from app.modules.intervenciones.schemas import (
    BandejaIntervencionesOut,
    IntervencionCreateIn,
    IntervencionOut,
    IntervencionRespuestaIn,
)

router = APIRouter(tags=["intervenciones"])

ROLES_LECTURA = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
ROLES_OPERACION = ("ADMINISTRADOR", "RECEPCION")


@router.get("/intervenciones", response_model=BandejaIntervencionesOut)
def listar_intervenciones(
    nivel_riesgo: str | None = None,
    especialidad: str | None = None,
    estado_intervencion: str | None = None,
    canal_contacto: str | None = None,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return service.listar_bandeja_intervenciones(
        db,
        nivel_riesgo=nivel_riesgo,
        especialidad=especialidad,
        estado_intervencion=estado_intervencion,
        canal_contacto=canal_contacto,
    )


@router.get("/citas/{id_cita}/intervenciones", response_model=list[IntervencionOut])
def listar_intervenciones_de_cita(
    id_cita: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return [IntervencionOut.model_validate(i) for i in repository.listar_por_cita(db, id_cita)]


@router.post("/citas/{id_cita}/intervenciones", response_model=IntervencionOut)
def crear_intervencion(
    id_cita: int,
    datos: IntervencionCreateIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    return service.crear_intervencion(db, id_cita, datos, usuario=usuario, ip=ip_cliente(request))


@router.patch("/intervenciones/{id_intervencion}", response_model=IntervencionOut)
def registrar_respuesta(
    id_intervencion: int,
    datos: IntervencionRespuestaIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    return service.registrar_respuesta_intervencion(
        db,
        id_intervencion,
        datos,
        usuario=usuario,
        ip=ip_cliente(request),
    )

