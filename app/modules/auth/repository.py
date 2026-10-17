from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.models import Usuario


def por_correo(db: Session, correo: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(func.lower(Usuario.correo_institucional) == correo.strip().lower()))


def por_id(db: Session, id_usuario: int) -> Usuario | None:
    return db.get(Usuario, id_usuario)