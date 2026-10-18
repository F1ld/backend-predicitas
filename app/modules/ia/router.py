"""Endpoints M09-E01 a M09-E04 (contratos/modulo-09.json).

M09-E01 empieza por /citas pero vive aquí (nota del contrato): la ranura de routers lo registra
igual y el módulo de citas no depende de IA.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.citas.reglas import LIMA
from app.modules.ia import service
from app.modules.ia.cliente import ClienteIA, get_cliente
from app.modules.ia.schemas import (LoteIn, LoteOut, ModeloActivoOut, NivelRiesgo, PaginaPrediccionesOut,
                                    PrediccionOut)

router = APIRouter(tags=["ia"])
OPERADORES = requiere_roles("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
CONSULTA_TECNICA = requiere_roles("ADMINISTRADOR", "TECNICO_IA")


def reloj_ia() -> datetime:
    """«Ahora» para decidir si una cita es futura. Las pruebas lo sustituyen."""
    return datetime.now(LIMA)


@router.post("/citas/{id_cita}/prediccion", response_model=PrediccionOut, status_code=201,
             responses={200: {"model": PrediccionOut, "description": "Ya existía para la versión activa"}})
def predecir(id_cita: int, request: Request, response: Response, usuario: Usuario = Depends(OPERADORES),
             db: Session = Depends(get_db), cliente: ClienteIA = Depends(get_cliente),
             ahora: datetime = Depends(reloj_ia)):
    """M09-E01 · RF-052 a RF-054, RF-098, RF-099: 201 nueva, 200 si ya existía."""
    resultado = service.predecir_cita(db, cliente, id_cita, usuario, ip_cliente(request), ahora)
    if resultado.ya_existia:
        response.status_code = 200
    return resultado


@router.post("/predicciones/lote", response_model=LoteOut)
def lote(datos: LoteIn, request: Request, usuario: Usuario = Depends(OPERADORES),
         db: Session = Depends(get_db), cliente: ClienteIA = Depends(get_cliente),
         ahora: datetime = Depends(reloj_ia)):
    """M09-E02 · RF-052, RF-100."""
    return service.predecir_lote(db, cliente, datos, usuario, ip_cliente(request), ahora)


@router.get("/predicciones/modelo", response_model=ModeloActivoOut)
def modelo(_: Usuario = Depends(OPERADORES), cliente: ClienteIA = Depends(get_cliente)):
    """M09-E03 · RF-053, RF-056: disponible=false si el servicio no responde (nunca 503)."""
    return service.modelo_activo(cliente)


@router.get("/predicciones", response_model=PaginaPrediccionesOut)
def listar(
    id_cita: int | None = None,
    version_modelo: str | None = Query(default=None, max_length=30),
    nivel_riesgo: NivelRiesgo | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(CONSULTA_TECNICA),
    db: Session = Depends(get_db),
):
    """M09-E04 · RF-092: consulta técnica, descendente por fecha de inferencia."""
    return service.listar(db, id_cita=id_cita, version_modelo=version_modelo, nivel_riesgo=nivel_riesgo,
                          desde=desde, hasta=hasta, limite=limite, desplazamiento=desplazamiento)
