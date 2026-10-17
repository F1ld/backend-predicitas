from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.citas.reglas import LIMA


def ids_existentes(db: Session, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    return set(db.scalars(select(Cita.id_cita_externa).where(Cita.id_cita_externa.in_(ids))))


def listar(
    db: Session, *, desde: date | None, hasta: date | None, especialidad: str | None,
    estado: str | None, texto: str | None, limite: int, desplazamiento: int,
) -> tuple[int, list[Cita]]:
    consulta = select(Cita)
    if desde:
        consulta = consulta.where(Cita.fecha_hora_cita >= datetime.combine(desde, time.min, tzinfo=LIMA))
    if hasta:
        consulta = consulta.where(
            Cita.fecha_hora_cita < datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=LIMA)
        )
    if especialidad:
        consulta = consulta.where(Cita.especialidad == especialidad.upper())
    if estado:
        consulta = consulta.where(Cita.estado_actual == estado.upper())
    if texto:
        consulta = consulta.where(Cita.id_cita_externa.ilike(f"%{texto}%"))

    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    items = db.scalars(
        consulta.order_by(Cita.fecha_hora_cita, Cita.id_cita).limit(limite).offset(desplazamiento)
    ).all()
    return total, list(items)


def historial_de(db: Session, id_cita: int) -> list[HistorialEstadoCita]:
    return list(db.scalars(
        select(HistorialEstadoCita)
        .where(HistorialEstadoCita.id_cita == id_cita)
        .order_by(HistorialEstadoCita.fecha_hora_evento, HistorialEstadoCita.id_historial)
    ))