from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auditoria.models import AuditoriaEvento
from app.modules.auth.models import Usuario


def por_correo(db: Session, correo: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(func.lower(Usuario.correo_institucional) == correo.strip().lower()))


def por_id(db: Session, id_usuario: int) -> Usuario | None:
    return db.get(Usuario, id_usuario)


def _logins(id_usuario: int):
    # Usa el índice (id_usuario, accion, creado_en) de m01_001_indices_auditoria.
    return (AuditoriaEvento.id_usuario == id_usuario) & (AuditoriaEvento.accion == "LOGIN")


def fallos_recientes(db: Session, id_usuario: int, desde: datetime, limite: int) -> list[datetime]:
    """Fechas de los LOGIN FALLIDO de la cuenta desde `desde` y posteriores a su último
    LOGIN EXITOSO, de la más reciente a la más antigua (D-009)."""
    ultimo_exito = db.scalar(
        select(func.max(AuditoriaEvento.creado_en))
        .where(_logins(id_usuario), AuditoriaEvento.datos_after["resultado"].astext == "EXITOSO")
    )
    consulta = (
        select(AuditoriaEvento.creado_en)
        .where(_logins(id_usuario), AuditoriaEvento.creado_en >= desde,
               AuditoriaEvento.datos_after["resultado"].astext == "FALLIDO")
        .order_by(AuditoriaEvento.creado_en.desc())
        .limit(limite)
    )
    if ultimo_exito is not None:
        consulta = consulta.where(AuditoriaEvento.creado_en > ultimo_exito)
    return list(db.scalars(consulta))


def hay_logout_desde(db: Session, id_usuario: int, momento: datetime) -> bool:
    """¿Hay un LOGOUT del usuario en `momento` o después? (D-010)."""
    return db.scalar(
        select(AuditoriaEvento.id_log)
        .where(AuditoriaEvento.id_usuario == id_usuario, AuditoriaEvento.accion == "LOGOUT",
               AuditoriaEvento.creado_en >= momento)
        .limit(1)
    ) is not None
