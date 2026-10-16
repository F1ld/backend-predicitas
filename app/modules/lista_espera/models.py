from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime,
                        ForeignKey, Integer, String, func, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.dominio import (ESPECIALIDADES, ESTADOS_CANDIDATO, ESTADOS_CUPO,
                              FRANJAS_PREFERIDAS, sql_in)


class ListaEspera(Base):
    __tablename__ = "lista_espera"
    __table_args__ = (
        CheckConstraint(sql_in("especialidad_req", ESPECIALIDADES), name="especialidad_req"),
        CheckConstraint(sql_in("franja_preferida", FRANJAS_PREFERIDAS), name="franja_preferida"),
        CheckConstraint(sql_in("estado_candidato", ESTADOS_CANDIDATO), name="estado_candidato"),
    )

    id_candidato: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paciente_anon_id: Mapped[str] = mapped_column(String(50), index=True)
    especialidad_req: Mapped[str] = mapped_column(String(50))
    franja_preferida: Mapped[str] = mapped_column(String(20))
    estado_candidato: Mapped[str] = mapped_column(String(25))
    prioridad_registro: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    fecha_registro: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CupoLiberado(Base):
    __tablename__ = "cupos_liberados"
    __table_args__ = (CheckConstraint(sql_in("estado_cupo", ESTADOS_CUPO), name="estado_cupo"),)

    id_cupo_liberado: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cita_origen: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("citas.id_cita", ondelete="RESTRICT"), unique=True
    )
    especialidad: Mapped[str] = mapped_column(String(50))
    medico: Mapped[str] = mapped_column(String(100))
    fecha_hora_cupo: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    estado_cupo: Mapped[str] = mapped_column(String(25))
    origen_liberacion: Mapped[str] = mapped_column(String(40))
    liberado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reasignacion(Base):
    __tablename__ = "reasignaciones"
    __table_args__ = (
        # Human-in-the-Loop: sin confirmación explícita no se puede registrar.
        CheckConstraint("confirmacion_humana IS TRUE", name="confirmacion_humana"),
    )

    id_reasignacion: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cupo_liberado: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cupos_liberados.id_cupo_liberado", ondelete="RESTRICT"), unique=True
    )
    id_candidato: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lista_espera.id_candidato", ondelete="RESTRICT")
    )
    id_operador_confirma: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuarios.id_usuario", ondelete="RESTRICT")
    )
    confirmacion_humana: Mapped[bool] = mapped_column(Boolean)  # sin valor por defecto
    medio_confirmacion: Mapped[str] = mapped_column(String(30))
    observaciones: Mapped[str | None] = mapped_column(String(255))
    fecha_hora_reasigna: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )