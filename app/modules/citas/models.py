from datetime import datetime

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey,
                        Integer, SmallInteger, String, func, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.dominio import (CANALES_ORIGEN, ESPECIALIDADES, ESTADOS_CITA,
                              FRANJAS_CITA, SEDES, TIPOS_PACIENTE, sql_in)


class Cita(Base):
    __tablename__ = "citas"
    __table_args__ = (
        CheckConstraint(sql_in("sede", SEDES), name="sede"),
        CheckConstraint(sql_in("especialidad", ESPECIALIDADES), name="especialidad"),
        CheckConstraint("antelacion_dias >= 0", name="antelacion_dias"),
        CheckConstraint(sql_in("tipo_paciente", TIPOS_PACIENTE), name="tipo_paciente"),
        CheckConstraint(sql_in("canal_origen", CANALES_ORIGEN), name="canal_origen"),
        CheckConstraint(sql_in("franja_horaria", FRANJAS_CITA), name="franja_horaria"),
        CheckConstraint(sql_in("estado_actual", ESTADOS_CITA), name="estado_actual"),
        CheckConstraint("target_no_show IN (0, 1)", name="target_no_show"),
        # Aislamiento del target: solo existe valor tras el desenlace de la cita.
        CheckConstraint(
            "target_no_show IS NULL OR estado_actual IN ('ATENDIDA', 'NO_SHOW')",
            name="target_solo_con_desenlace",
        ),
    )

    id_cita: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cita_externa: Mapped[str] = mapped_column(String(50), unique=True)
    paciente_anon_id: Mapped[str] = mapped_column(String(50), index=True)
    sede: Mapped[str] = mapped_column(String(50))
    especialidad: Mapped[str] = mapped_column(String(50))
    medico: Mapped[str] = mapped_column(String(100))
    fecha_hora_cita: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fecha_registro_cita: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    antelacion_dias: Mapped[int] = mapped_column(Integer)
    tipo_paciente: Mapped[str] = mapped_column(String(20))
    canal_origen: Mapped[str] = mapped_column(String(30))
    franja_horaria: Mapped[str] = mapped_column(String(20))
    dia_semana: Mapped[str] = mapped_column(String(15))
    inasistencias_previas: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    reprogramaciones_prev: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    asistencias_previas: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    estado_actual: Mapped[str] = mapped_column(String(30))
    target_no_show: Mapped[int | None] = mapped_column(SmallInteger)


class HistorialEstadoCita(Base):
    __tablename__ = "historial_estados_cita"

    id_historial: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cita: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("citas.id_cita", ondelete="RESTRICT"), index=True
    )
    id_usuario_actor: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuarios.id_usuario", ondelete="RESTRICT")
    )
    estado_anterior: Mapped[str | None] = mapped_column(String(30))
    estado_nuevo: Mapped[str] = mapped_column(String(30))
    motivo_cambio: Mapped[str | None] = mapped_column(String(255))
    fecha_hora_evento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )