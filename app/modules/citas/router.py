import csv
import io
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dominio import ESPECIALIDADES, ESTADOS_CITA, NIVELES_RIESGO
from app.core.errores import ArchivoInvalido
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.citas import service
from app.modules.citas.importer import importar_citas
from app.modules.citas.reglas import ahora_lima
from app.modules.citas.schemas import (CambioEstadoIn, CatalogosOut, CheckInIn, CheckInOut,
                                       CitaDetalleOut, CitaRegistroIn, PaginaCitasOut,
                                       ResultadoImportacionOut)

router = APIRouter(prefix="/citas", tags=["citas"])

LECTORES = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
ESCRITORES = ("ADMINISTRADOR", "RECEPCION")
MAX_BYTES = 2 * 1024 * 1024
MAX_FILAS = 5000


def reloj() -> datetime:
    """«Ahora» en Lima. Inyectable: las pruebas lo sustituyen con dependency_overrides."""
    return ahora_lima()


@router.get("", response_model=PaginaCitasOut)
def listar(
    desde: date | None = None,
    hasta: date | None = None,
    especialidad: Literal[ESPECIALIDADES] | None = None,  # type: ignore[valid-type]
    medico: str | None = None,
    estado: Literal[ESTADOS_CITA] | None = None,  # type: ignore[valid-type]
    nivel_riesgo: Literal[NIVELES_RIESGO + ("SIN_PREDICCION",)] | None = None,  # type: ignore[valid-type]
    con_intervencion: bool | None = None,
    q: str | None = Query(default=None, description="Busca en id_cita_externa, paciente_anon_id y medico"),
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*LECTORES)),
    db: Session = Depends(get_db),
):
    """M02-E01 (RF-016, RF-017)."""
    return service.listar_citas(
        db, desde=desde, hasta=hasta, especialidad=especialidad, medico=medico, estado=estado,
        nivel_riesgo=nivel_riesgo, con_intervencion=con_intervencion, texto=q,
        limite=limite, desplazamiento=desplazamiento,
    )


@router.post("", response_model=CitaDetalleOut, status_code=201)
def registrar(
    datos: CitaRegistroIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
):
    """M02-E03 (RF-010)."""
    return service.registrar_cita(db, datos, usuario, ip_cliente(request), ahora)


@router.get("/catalogos", response_model=CatalogosOut)  # antes de /{id_cita}
def catalogos(_: Usuario = Depends(requiere_roles(*LECTORES)), db: Session = Depends(get_db)):
    """M02-E07."""
    return service.catalogos(db)


@router.post("/importar", response_model=ResultadoImportacionOut)
def importar(
    request: Request,
    archivo: UploadFile = File(..., description="CSV UTF-8 con encabezados"),
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
):
    """M02-E04 (F-04)."""
    contenido = archivo.file.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        raise ArchivoInvalido("El archivo supera los 2 MB permitidos")
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ArchivoInvalido("El archivo debe estar codificado en UTF-8")

    filas = [
        {k: v for k, v in fila.items() if k and v not in (None, "")}  # celdas vacías = valor por defecto
        for fila in csv.DictReader(io.StringIO(texto))
    ]
    if not filas:
        raise ArchivoInvalido("El archivo no contiene filas")
    if len(filas) > MAX_FILAS:
        raise ArchivoInvalido(f"El archivo supera el máximo de {MAX_FILAS} filas")

    return importar_citas(
        db, filas, id_usuario=usuario.id_usuario, ip=ip_cliente(request),
        origen=f"archivo:{archivo.filename}", ahora=ahora,
    )


@router.get("/{id_cita}", response_model=CitaDetalleOut)
def detalle(id_cita: int, _: Usuario = Depends(requiere_roles(*LECTORES)), db: Session = Depends(get_db)):
    """M02-E02 (RF-018)."""
    return service.detalle_cita(db, id_cita)


@router.post("/{id_cita}/estado", response_model=CitaDetalleOut)
def cambiar_estado(
    id_cita: int,
    cambio: CambioEstadoIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
):
    """M02-E05 (F-06)."""
    return service.cambiar_estado(db, id_cita, cambio, usuario, ip_cliente(request), ahora)


@router.post("/{id_cita}/check-in", response_model=CheckInOut, status_code=201)
def check_in(
    id_cita: int,
    request: Request,
    datos: CheckInIn | None = None,
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
    ahora: datetime = Depends(reloj),
):
    """M02-E06 (RF-104, D-012)."""
    observacion = datos.observacion if datos else None
    return service.registrar_check_in(db, id_cita, observacion, usuario, ip_cliente(request), ahora)
