from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.dominio import ROLES, sql_in


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (CheckConstraint(sql_in("rol", ROLES), name="rol"),)

    id_usuario: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nombre_completo: Mapped[str] = mapped_column(String(120))
    correo_institucional: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(30))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))