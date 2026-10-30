from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.lista_espera import repository, service
from app.modules.lista_espera.schemas import (
    CandidatoCreateIn,
    CandidatoOut,
    CandidatoUpdateIn,
    CupoLiberadoOut,
    PropuestaCandidatosOut,
    ReasignacionIn,
    ReasignacionOut,
)

router = APIRouter(tags=["lista_espera_y_reasignacion"])

ROLES_LECTURA = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
ROLES_OPERACION = ("ADMINISTRADOR", "RECEPCION")


@router.get("/lista-espera", response_model=list[CandidatoOut])
def listar_espera(
    especialidad_req: str | None = None,
    franja_preferida: str | None = None,
    estado_candidato: str | None = None,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    candidatos = repository.listar_candidatos(
        db,
        especialidad_req=especialidad_req,
        franja_preferida=franja_preferida,
        estado_candidato=estado_candidato,
    )
    return [CandidatoOut.model_validate(c) for c in candidatos]


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


@router.get("/cupos-liberados", response_model=list[CupoLiberadoOut])
def listar_cupos_liberados(
    estado_cupo: str | None = Query(default="DISPONIBLE", description="Estado del cupo (DISPONIBLE por defecto, o TODOS)"),
    especialidad: str | None = None,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return service.listar_cupos(db, estado_cupo=estado_cupo, especialidad=especialidad)


@router.get("/cupos-liberados/{id_cupo}/candidatos", response_model=PropuestaCandidatosOut)
def obtener_candidatos_compatibles(
    id_cupo: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return service.proponer_candidatos_para_cupo(db, id_cupo)


@router.post("/cupos-liberados/{id_cupo}/reasignar", response_model=ReasignacionOut)
def reasignar_cupo(
    id_cupo: int,
    datos: ReasignacionIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_OPERACION)),
    db: Session = Depends(get_db),
):
    return service.reasignar_cupo(db, id_cupo, datos, usuario=usuario, ip=ip_cliente(request))

