from datetime import datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey,
                        Numeric, String, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.dominio import NIVELES_RIESGO, sql_in


class PrediccionIA(Base):
    __tablename__ = "predicciones_ia"
    __table_args__ = (
        UniqueConstraint("id_cita", "version_modelo", name="uq_predicciones_ia_cita_version"),
        CheckConstraint(
            "probabilidad_no_show >= 0.000 AND probabilidad_no_show <= 1.000",
            name="probabilidad_no_show",
        ),
        CheckConstraint(sql_in("nivel_riesgo", NIVELES_RIESGO), name="nivel_riesgo"),
    )

    id_prediccion: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_cita: Mapped[int] = mapped_column(BigInteger, ForeignKey("citas.id_cita", ondelete="RESTRICT"))
    version_modelo: Mapped[str] = mapped_column(String(30))
    probabilidad_no_show: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    nivel_riesgo: Mapped[str] = mapped_column(String(20))
    umbral_aplicado: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    features_snapshot: Mapped[dict] = mapped_column(JSONB)
    explicabilidad_resumen: Mapped[str | None] = mapped_column(String(255))
    fecha_hora_inferencia: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )