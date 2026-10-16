from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime,
                        ForeignKey, String, func, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.dominio import (CANALES_CONTACTO, ESTADOS_INTERVENCION,
                              RESPUESTAS_PACIENTE, sql_in)


class Intervencion(Base):
    __tablename__ = "intervenciones"
    __table_args__ = (
        CheckConstraint(sql_in("canal_contacto", CANALES_CONTACTO), name="canal_contacto"),
        CheckConstraint(sql_in("estado_intervencion", ESTADOS_INTERVENCION), name="estado_intervencion"),
        CheckConstraint(sql_in("respuesta_paciente", RESPUESTAS_PACIENTE), name="respuesta_paciente"),
    )

    id_intervencion: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cita: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("citas.id_cita", ondelete="RESTRICT"), index=True
    )
    id_operador: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id_usuario", ondelete="RESTRICT")
    )
    canal_contacto: Mapped[str] = mapped_column(String(30))
    plantilla_mensaje: Mapped[str] = mapped_column(String(100))
    consentimiento_optout: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    estado_intervencion: Mapped[str] = mapped_column(String(30))
    respuesta_paciente: Mapped[str | None] = mapped_column(String(50))
    fecha_hora_envio: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fecha_hora_respuesta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))