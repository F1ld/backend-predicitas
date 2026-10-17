import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errores import ArchivoInvalido
from app.core.http import ip_cliente
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.citas import service
from app.modules.citas.importer import importar_citas
from app.modules.citas.schemas import (CambioEstadoIn, CitaDetalleOut, PaginaCitasOut,
                                       ResultadoImportacionOut)

router = APIRouter(prefix="/citas", tags=["citas"])

LECTORES = ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA")
ESCRITORES = ("ADMINISTRADOR", "RECEPCION")
MAX_BYTES = 2 * 1024 * 1024
MAX_FILAS = 5000


@router.get("", response_model=PaginaCitasOut)
def listar(
    desde: date | None = None,
    hasta: date | None = None,
    especialidad: str | None = None,
    estado: str | None = None,
    q: str | None = Query(default=None, description="Busca por id_cita_externa"),
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    _: Usuario = Depends(requiere_roles(*LECTORES)),
    db: Session = Depends(get_db),
):
    return service.listar_citas(
        db, desde=desde, hasta=hasta, especialidad=especialidad, estado=estado,
        texto=q, limite=limite, desplazamiento=desplazamiento,
    )


@router.get("/{id_cita}", response_model=CitaDetalleOut)
def detalle(id_cita: int, _: Usuario = Depends(requiere_roles(*LECTORES)), db: Session = Depends(get_db)):
    return service.detalle_cita(db, id_cita)


@router.post("/{id_cita}/estado", response_model=CitaDetalleOut)
def cambiar_estado(
    id_cita: int,
    cambio: CambioEstadoIn,
    request: Request,
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
):
    return service.cambiar_estado(db, id_cita, cambio.estado_nuevo, cambio.motivo, usuario, ip_cliente(request))


@router.post("/importar", response_model=ResultadoImportacionOut)
def importar(
    request: Request,
    archivo: UploadFile = File(..., description="CSV UTF-8 con encabezados"),
    usuario: Usuario = Depends(requiere_roles(*ESCRITORES)),
    db: Session = Depends(get_db),
):
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
        origen=f"archivo:{archivo.filename}",
    )