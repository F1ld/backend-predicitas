from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.ia import repository, service
from app.modules.ia.schemas import (
    DatasetResumenOut,
    MetricasModeloOut,
    PrediccionIAOut,
    ResultadoPrediccionLoteOut,
)

router = APIRouter(prefix="/ia", tags=["ia"])

ROLES_LECTURA = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
ROLES_INFERENCIA = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")


@router.post("/predecir/{id_cita}", response_model=PrediccionIAOut)
def predecir_cita(
    id_cita: int,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ROLES_INFERENCIA)),
    db: Session = Depends(get_db),
):
    return service.predecir_cita(db, id_cita, usuario=usuario, ip=ip_cliente(request))


@router.post("/predecir-lote", response_model=ResultadoPrediccionLoteOut)
def predecir_lote(
    request: Request,
    forzar: bool = Query(default=False, description="Si es True, recalcula también las citas que ya tienen predicción"),
    usuario: Usuario = Depends(requiere_roles(*ROLES_INFERENCIA)),
    db: Session = Depends(get_db),
):
    return service.predecir_lote(db, forzar=forzar, usuario=usuario, ip=ip_cliente(request))


@router.get("/predicciones/{id_cita}", response_model=list[PrediccionIAOut])
def listar_predicciones_cita(
    id_cita: int,
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return [PrediccionIAOut.model_validate(p) for p in repository.listar_por_cita(db, id_cita)]


@router.get("/metricas", response_model=MetricasModeloOut)
def obtener_metricas(
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
):
    return service.obtener_metricas_modelo()


@router.get("/dataset-resumen", response_model=DatasetResumenOut)
def obtener_dataset_resumen(
    _: Usuario = Depends(requiere_roles(*ROLES_LECTURA)),
    db: Session = Depends(get_db),
):
    return service.obtener_dataset_resumen(db)

