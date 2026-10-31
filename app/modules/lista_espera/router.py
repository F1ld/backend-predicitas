from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errores import NoEncontrado
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.lista_espera import repository, service
from app.modules.lista_espera.models import CupoLiberado, ListaEspera
from app.modules.lista_espera.schemas import (
    CandidatoCreateIn,
    CandidatoOut,
    CandidatoUpdateIn,
    CierreOfertaIn,
    CupoDetalleOut,
    CupoLiberadoOut,
    OfertaIn,
    PaginaCandidatoOut,
    PaginaCupoOut,
    PropuestaCandidatosOut,
    ReasignacionIn,
    ReasignacionOut,
)

router = APIRouter(tags=["lista_espera_y_reasignacion"])

ROLES_LECTURA = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
ROLES_OPERACION = ("ADMINISTRADOR", "RECEPCION")


@router.get("/lista-espera", response_model=PaginaCandidatoOut)
def listar_espera(
    q: str | None = None,
    especialidad_req: str | None = None,
    franja_preferida: str | None = None,
    estado_candidato: str | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    candidatos = repository.listar_candidatos(
        db,
        especialidad_req=especialidad_req,
        franja_preferida=franja_preferida,
        estado_candidato=estado_candidato,
    )
    if q:
        q_norm = q.strip().upper()
        candidatos = [c for c in candidatos if q_norm in c.paciente_anon_id.upper()]

    total = len(candidatos)
    paginados = candidatos[desplazamiento : desplazamiento + limite]

    return PaginaCandidatoOut(
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        items=[CandidatoOut.model_validate(c) for c in paginados],
    )


@router.post("/lista-espera", response_model=CandidatoOut)
def registrar_candidato(
    datos: CandidatoCreateIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    return service.crear_candidato(db, datos, usuario=usuario, ip=ip_cliente(request))


@router.patch("/lista-espera/{id_candidato}", response_model=CandidatoOut)
def actualizar_candidato(
    id_candidato: int,
    datos: CandidatoUpdateIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    return service.actualizar_candidato(db, id_candidato, datos, usuario=usuario, ip=ip_cliente(request))


# ==========================================
# RUTAS DE CUPOS LIBERADOS (/cupos y /cupos-liberados)
# ==========================================

def _procesar_listado_cupos(
    db: Session,
    estado_cupo: str | None,
    especialidad: str | None,
    desde: str | None,
    hasta: str | None,
    limite: int,
    desplazamiento: int,
) -> PaginaCupoOut:
    cupos = service.listar_cupos(db, estado_cupo=estado_cupo, especialidad=especialidad)
    if desde:
        try:
            d_dt = datetime.fromisoformat(desde)
            cupos = [c for c in cupos if c.fecha_hora_cupo >= d_dt]
        except ValueError:
            pass
    if hasta:
        try:
            h_dt = datetime.fromisoformat(f"{hasta}T23:59:59")
            cupos = [c for c in cupos if c.fecha_hora_cupo <= h_dt]
        except ValueError:
            pass

    total = len(cupos)
    paginados = cupos[desplazamiento : desplazamiento + limite]
    return PaginaCupoOut(
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        items=paginados,
    )


@router.get("/cupos", response_model=PaginaCupoOut)
def listar_cupos_alias(
    estado_cupo: str | None = None,
    especialidad: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limite: int = Query(default=20, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return _procesar_listado_cupos(db, estado_cupo, especialidad, desde, hasta, limite, desplazamiento)


@router.get("/cupos-liberados", response_model=PaginaCupoOut)
def listar_cupos_liberados(
    estado_cupo: str | None = Query(default=None, description="Estado del cupo (DISPONIBLE por defecto, o TODOS)"),
    especialidad: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return _procesar_listado_cupos(db, estado_cupo, especialidad, desde, hasta, limite, desplazamiento)


@router.get("/cupos/{id_cupo}", response_model=CupoDetalleOut)
def obtener_detalle_cupo(
    id_cupo: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return service.obtener_detalle_cupo(db, id_cupo)


@router.get("/cupos-liberados/{id_cupo}", response_model=CupoDetalleOut)
def obtener_detalle_cupo_liberado(
    id_cupo: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return service.obtener_detalle_cupo(db, id_cupo)


@router.get("/cupos/{id_cupo}/candidatos", response_model=list[CandidatoOut])
def obtener_candidatos_para_cupo(
    id_cupo: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    propuesta = service.proponer_candidatos_para_cupo(db, id_cupo)
    return propuesta.candidatos


@router.get("/cupos-liberados/{id_cupo}/candidatos", response_model=PropuestaCandidatosOut)
def obtener_candidatos_compatibles(
    id_cupo: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return service.proponer_candidatos_para_cupo(db, id_cupo)


@router.post("/cupos/{id_cupo}/reasignar", response_model=ReasignacionOut)
def reasignar_cupo_alias(
    id_cupo: int,
    datos: ReasignacionIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    return service.reasignar_cupo(db, id_cupo, datos, usuario=usuario, ip=ip_cliente(request))


@router.post("/cupos-liberados/{id_cupo}/reasignar", response_model=ReasignacionOut)
def reasignar_cupo(
    id_cupo: int,
    datos: ReasignacionIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    return service.reasignar_cupo(db, id_cupo, datos, usuario=usuario, ip=ip_cliente(request))


@router.post("/cupos/{id_cupo}/ofertas", response_model=CupoDetalleOut)
def registrar_oferta(
    id_cupo: int,
    datos: OfertaIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    cupo = db.get(CupoLiberado, id_cupo)
    if not cupo:
        raise NoEncontrado(f"No existe el cupo {id_cupo}")
    candidato = db.get(ListaEspera, datos.id_candidato)
    if not candidato:
        raise NoEncontrado(f"No existe el candidato {datos.id_candidato}")

    cupo.estado_cupo = "EN_OFERTA"
    candidato.estado_candidato = "CONTACTADO"
    db.commit()
    db.refresh(cupo)
    return service.obtener_detalle_cupo(db, id_cupo)


@router.post("/cupos/{id_cupo}/ofertas/rechazo", response_model=CupoDetalleOut)
def rechazo_oferta(
    id_cupo: int,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    cupo = db.get(CupoLiberado, id_cupo)
    if not cupo:
        raise NoEncontrado(f"No existe el cupo {id_cupo}")
    cupo.estado_cupo = "DISPONIBLE"
    db.commit()
    db.refresh(cupo)
    return service.obtener_detalle_cupo(db, id_cupo)


@router.post("/cupos/{id_cupo}/ofertas/desistimiento", response_model=CupoDetalleOut)
def desistimiento_oferta(
    id_cupo: int,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    cupo = db.get(CupoLiberado, id_cupo)
    if not cupo:
        raise NoEncontrado(f"No existe el cupo {id_cupo}")
    cupo.estado_cupo = "DISPONIBLE"
    db.commit()
    db.refresh(cupo)
    return service.obtener_detalle_cupo(db, id_cupo)
