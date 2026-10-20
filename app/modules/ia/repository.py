from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.citas.models import Cita
from app.modules.ia.models import PrediccionIA


def por_cita_y_version(db: Session, id_cita: int, version_modelo: str) -> PrediccionIA | None:
    # Usa el índice único uq_predicciones_ia_cita_version.
    return db.scalar(select(PrediccionIA).where(PrediccionIA.id_cita == id_cita,
                                                PrediccionIA.version_modelo == version_modelo))


def citas_en_rango(db: Session, inicio: datetime, fin: datetime, especialidad: str | None) -> list[int]:
    consulta = (select(Cita.id_cita)
                .where(Cita.fecha_hora_cita >= inicio, Cita.fecha_hora_cita < fin)
                .order_by(Cita.fecha_hora_cita, Cita.id_cita))
    if especialidad:
        consulta = consulta.where(Cita.especialidad == especialidad)
    return list(db.scalars(consulta))


def listar(db: Session, *, id_cita: int | None, version_modelo: str | None, nivel_riesgo: str | None,
           inicio: datetime | None, fin: datetime | None, limite: int,
           desplazamiento: int) -> tuple[int, list[PrediccionIA]]:
    consulta = select(PrediccionIA)
    if id_cita is not None:
        consulta = consulta.where(PrediccionIA.id_cita == id_cita)
    if version_modelo:
        consulta = consulta.where(PrediccionIA.version_modelo == version_modelo)
    if nivel_riesgo:
        consulta = consulta.where(PrediccionIA.nivel_riesgo == nivel_riesgo)
    if inicio is not None:
        consulta = consulta.where(PrediccionIA.fecha_hora_inferencia >= inicio)
    if fin is not None:
        consulta = consulta.where(PrediccionIA.fecha_hora_inferencia < fin)
    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    filas = db.scalars(consulta.order_by(PrediccionIA.fecha_hora_inferencia.desc(),
                                         PrediccionIA.id_prediccion.desc())
                       .limit(limite).offset(desplazamiento))
    return total, list(filas)
