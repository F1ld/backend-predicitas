from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditoriaEvento(Base):
    __tablename__ = "auditoria_eventos"

    id_log: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_usuario: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id_usuario", ondelete="RESTRICT")
    )
    modulo: Mapped[str] = mapped_column(String(50))
    accion: Mapped[str] = mapped_column(String(50))
    entidad_afectada: Mapped[str] = mapped_column(String(50))
    id_entidad: Mapped[int | None] = mapped_column(BigInteger)
    datos_before: Mapped[dict | None] = mapped_column(JSONB)
    datos_after: Mapped[dict | None] = mapped_column(JSONB)
    direccion_ip: Mapped[str] = mapped_column(String(45))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())