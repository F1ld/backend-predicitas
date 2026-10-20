from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dominio import (CANALES_CONTACTO, ESPECIALIDADES, ESTADOS_INTERVENCION, NIVELES_RIESGO,
                              RESPUESTAS_PACIENTE)
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.citas.router import reloj  # mismo reloj inyectable que M02
from app.modules.intervenciones import service
from app.modules.intervenciones.schemas import (CupoOut, EstadoEnvioIn, IntervencionIn, IntervencionOut,
                                                LiberarIn, PaginaElegiblesOut, PaginaIntervencionesOut,
                                                PlantillaOut, Rep02Out, RespuestaIn)

# Sin prefijo: el módulo expone /intervenciones y /reportes/rep-02 (contratos/modulo-05.json).
router = APIRouter(tags=["intervenciones"])

LECTORES = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
ESCRITORES = ("ADMINISTRADOR", "RECEPCION")

Especialidad = Literal[ESPECIALIDADES]  # type: ignore[valid-type]


def modo_sombra() -> bool:
    """INTERVENCION_MODO_SOMBRA (Plan de Desarrollo §7). Inyectable en las pruebas."""
    return get_settings().intervencion_modo_sombra


@router.get("/intervenciones/elegibles", response_model=PaginaElegiblesOut)
def elegibles(
    desde: date | None = None,
    hasta: date | None = None,
    especialidad: Especialidad | None = None,
    nivel_riesgo: Literal["ALTO", "MEDIO"] | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
):
    """M05-E01 (RF-057)."""
    return service.elegibles(db, ahora=ahora, desde=desde, hasta=hasta, especialidad=especialidad,
                             nivel_riesgo=nivel_riesgo, limite=limite, desplazamiento=desplazamiento)


@router.get("/intervenciones/plantillas", response_model=list[PlantillaOut])  # antes de /{id}
def plantillas(_: Usuario = Depends(requiere_roles(*ESCRITORES))):
    """M05-E09."""
    return service.plantillas()


@router.post("/intervenciones", response_model=IntervencionOut, status_code=201)
def crear(
    datos: IntervencionIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
    sombra: bool = Depends(modo_sombra),
):
    """M05-E02 (RF-058, RF-063)."""
    return service.crear(db, datos, usuario, ip_cliente(request), ahora, sombra)


@router.get("/intervenciones", response_model=PaginaIntervencionesOut)
def listar(
    id_cita: int | None = None,
    estado_intervencion: Literal[ESTADOS_INTERVENCION] | None = None,  # type: ignore[valid-type]
    canal_contacto: Literal[CANALES_CONTACTO] | None = None,  # type: ignore[valid-type]
    respuesta_paciente: Literal[RESPUESTAS_PACIENTE] | None = None,  # type: ignore[valid-type]
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*LECTORES)),
    db: Session = Depends(get_db),
):
    """M05-E03."""
    return service.listar(db, id_cita=id_cita, estado=estado_intervencion, canal=canal_contacto,
                          respuesta=respuesta_paciente, desde=desde, hasta=hasta,
                          limite=limite, desplazamiento=desplazamiento)


@router.get("/intervenciones/{id_intervencion}", response_model=IntervencionOut)
def detalle(id_intervencion: int, _: Usuario = Depends(requiere_roles(*LECTORES)), db: Session = Depends(get_db)):
    """M05-E04."""
    return service.detalle(db, id_intervencion)


@router.post("/intervenciones/{id_intervencion}/estado", response_model=IntervencionOut)
def cambiar_estado(
    id_intervencion: int,
    datos: EstadoEnvioIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
):
    """M05-E05 (RF-059, RF-061)."""
    return service.cambiar_estado(db, id_intervencion, datos.estado_intervencion, usuario, ip_cliente(request), ahora)


@router.post("/intervenciones/{id_intervencion}/respuesta", response_model=IntervencionOut)
def respuesta(
    id_intervencion: int,
    datos: RespuestaIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
):
    """M05-E06 (RF-062, RF-064, RF-067)."""
    return service.responder_intervencion(db, id_intervencion, datos.respuesta_paciente, datos.optout,
                                          usuario, ip_cliente(request), ahora)


@router.post("/intervenciones/{id_intervencion}/optout", response_model=IntervencionOut)
def optout(id_intervencion: int, request: Request, usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
           db: Session = Depends(get_db)):
    """M05-E07 (RF-064)."""
    return service.registrar_optout(db, id_intervencion, usuario, ip_cliente(request))


@router.post("/intervenciones/{id_intervencion}/liberar-cupo", response_model=CupoOut, status_code=201)
def liberar_cupo(
    id_intervencion: int,
    request: Request,
    datos: LiberarIn | None = None,
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
):
    """M05-E08 (RF-068, RN04)."""
    return service.liberar_cupo(db, id_intervencion, datos.motivo if datos else None, usuario,
                                ip_cliente(request), ahora)


@router.get("/reportes/rep-02", response_model=Rep02Out)
def rep02(
    request: Request,
    desde: date | None = None,
    hasta: date | None = None,
    canal_contacto: Literal[CANALES_CONTACTO] | None = None,  # type: ignore[valid-type]
    nivel_riesgo: Literal[NIVELES_RIESGO] | None = None,  # type: ignore[valid-type]
    especialidad: Especialidad | None = None,
    formato: str = "json",
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
):
    """M05-E10 (REP-02): json, csv o xlsx."""
    return service.exportar_rep02(db, formato, usuario, ip_cliente(request), desde=desde, hasta=hasta,
                                  canal=canal_contacto, nivel_riesgo=nivel_riesgo, especialidad=especialidad)
