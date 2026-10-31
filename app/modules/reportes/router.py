from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import requiere_roles
from app.modules.auth.models import Usuario
from app.modules.reportes import service
from app.modules.reportes.schemas import Rep02Out, Rep03Out

router = APIRouter(prefix="/reportes", tags=["reportes"])

ROLES_REPORTE = ("ADMINISTRADOR", "RECEPCION")


@router.get("/rep-02", response_model=Rep02Out)
def obtener_rep02(
    desde: str | None = None,
    hasta: str | None = None,
    canal_contacto: str | None = None,
    nivel_riesgo: str | None = None,
    especialidad: str | None = None,
    formato: str = Query(default="json", regex="^(json|csv|xlsx)$"),
    _: Usuario = Depends(requiere_roles(*ROLES_REPORTE)),
    db: Session = Depends(get_db),
):
    reporte = service.generar_rep02(
        db,
        desde=desde,
        hasta=hasta,
        canal_contacto=canal_contacto,
        nivel_riesgo=nivel_riesgo,
        especialidad=especialidad,
    )
    if formato in ("csv", "xlsx"):
        contenido_csv = service.generar_rep02_csv(reporte)
        return Response(
            content=contenido_csv.encode("utf-8-sig"),
            media_type="text/csv" if formato == "csv" else "application/vnd.ms-excel",
            headers={"Content-Disposition": f'attachment; filename="rep-02.{formato}"'},
        )
    return reporte


@router.get("/rep-03", response_model=Rep03Out)
def obtener_rep03(
    desde: str | None = None,
    hasta: str | None = None,
    especialidad: str | None = None,
    id_operador: int | None = None,
    formato: str = Query(default="json", regex="^(json|csv|xlsx)$"),
    _: Usuario = Depends(requiere_roles(*ROLES_REPORTE)),
    db: Session = Depends(get_db),
):
    reporte = service.generar_rep03(
        db,
        desde=desde,
        hasta=hasta,
        especialidad=especialidad,
        id_operador=id_operador,
    )
    if formato in ("csv", "xlsx"):
        contenido_csv = service.generar_rep03_csv(reporte)
        return Response(
            content=contenido_csv.encode("utf-8-sig"),
            media_type="text/csv" if formato == "csv" else "application/vnd.ms-excel",
            headers={"Content-Disposition": f'attachment; filename="rep-03.{formato}"'},
        )
    return reporte


# Alias directos para las rutas intuitivas
@router.get("/intervenciones", response_model=Rep02Out)
def alias_reporte_intervenciones(
    desde: str | None = None,
    hasta: str | None = None,
    canal_contacto: str | None = None,
    nivel_riesgo: str | None = None,
    especialidad: str | None = None,
    formato: str = Query(default="json", regex="^(json|csv|xlsx)$"),
    usuario: Usuario = Depends(requiere_roles(*ROLES_REPORTE)),
    db: Session = Depends(get_db),
):
    return obtener_rep02(
        desde=desde,
        hasta=hasta,
        canal_contacto=canal_contacto,
        nivel_riesgo=nivel_riesgo,
        especialidad=especialidad,
        formato=formato,
        _=usuario,
        db=db,
    )


@router.get("/reasignaciones", response_model=Rep03Out)
def alias_reporte_reasignaciones(
    desde: str | None = None,
    hasta: str | None = None,
    especialidad: str | None = None,
    id_operador: int | None = None,
    formato: str = Query(default="json", regex="^(json|csv|xlsx)$"),
    usuario: Usuario = Depends(requiere_roles(*ROLES_REPORTE)),
    db: Session = Depends(get_db),
):
    return obtener_rep03(
        desde=desde,
        hasta=hasta,
        especialidad=especialidad,
        id_operador=id_operador,
        formato=formato,
        _=usuario,
        db=db,
    )
