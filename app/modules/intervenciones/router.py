from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errores import NoEncontrado
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.intervenciones import repository, service
from app.modules.intervenciones.models import Intervencion
from app.modules.intervenciones.schemas import (
    BandejaIntervencionesOut,
    IntervencionCreateIn,
    IntervencionOut,
    IntervencionRespuestaIn,
    PaginaElegiblesOut,
    PaginaIntervencionesOut,
)

router = APIRouter(tags=["intervenciones"])

ROLES_LECTURA = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
ROLES_OPERACION = ("ADMINISTRADOR", "RECEPCION")


@router.get("/intervenciones/elegibles", response_model=PaginaElegiblesOut)
def listar_intervenciones_elegibles(
    desde: str | None = None,
    hasta: str | None = None,
    especialidad: str | None = None,
    nivel_riesgo: str | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return service.listar_citas_elegibles(
        db,
        desde=desde,
        hasta=hasta,
        especialidad=especialidad,
        nivel_riesgo=nivel_riesgo,
        limite=limite,
        desplazamiento=desplazamiento,
    )


@router.get("/intervenciones", response_model=PaginaIntervencionesOut)
def listar_intervenciones(
    nivel_riesgo: str | None = None,
    especialidad: str | None = None,
    estado_intervencion: str | None = None,
    canal_contacto: str | None = None,
    respuesta_paciente: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    id_cita: int | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    bandeja = service.listar_bandeja_intervenciones(
        db,
        nivel_riesgo=nivel_riesgo,
        especialidad=especialidad,
        estado_intervencion=estado_intervencion,
        canal_contacto=canal_contacto,
    )
    # Filtro adicional de historial si aplica
    historial = [service._enriquecer_out(i) for i in repository.listar_historial(db, estado_intervencion=estado_intervencion, canal_contacto=canal_contacto, limite=1000)]
    if id_cita:
        historial = [h for h in historial if h.id_cita == id_cita]
    if respuesta_paciente:
        historial = [h for h in historial if h.respuesta_paciente == respuesta_paciente.upper()]

    total = len(historial)
    items_paginados = historial[desplazamiento : desplazamiento + limite]

    return PaginaIntervencionesOut(
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        items=items_paginados,
        total_sugeridas=bandeja.total_sugeridas,
        total_intervenciones=total,
        citas_sugeridas=bandeja.citas_sugeridas,
        historial_intervenciones=items_paginados,
    )


@router.get("/intervenciones/{id_intervencion}", response_model=IntervencionOut)
def obtener_intervencion(
    id_intervencion: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    intervencion = db.get(Intervencion, id_intervencion)
    if intervencion is None:
        raise NoEncontrado(f"No existe la intervención {id_intervencion}")
    return service._enriquecer_out(intervencion)


@router.get("/citas/{id_cita}/intervenciones", response_model=list[IntervencionOut])
def listar_intervenciones_de_cita(
    id_cita: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return [service._enriquecer_out(i) for i in repository.listar_por_cita(db, id_cita)]


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
