from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.citas.models import Cita
from app.modules.ia.models import PrediccionIA


def obtener_por_cita_y_version(db: Session, id_cita: int, version_modelo: str) -> PrediccionIA | None:
    stmt = select(PrediccionIA).where(
        PrediccionIA.id_cita == id_cita,
        PrediccionIA.version_modelo == version_modelo,
    )
    return db.scalar(stmt)


def listar_por_cita(db: Session, id_cita: int) -> list[PrediccionIA]:
    stmt = (
        select(PrediccionIA)
        .where(PrediccionIA.id_cita == id_cita)
        .order_by(PrediccionIA.fecha_hora_inferencia.desc(), PrediccionIA.id_prediccion.desc())
    )
    return list(db.scalars(stmt))


def guardar_o_actualizar_prediccion(
    db: Session,
    *,
    id_cita: int,
    version_modelo: str,
    probabilidad_no_show: Decimal,
    nivel_riesgo: str,
    umbral_aplicado: Decimal,
    features_snapshot: dict[str, Any],
    explicabilidad_resumen: str,
) -> tuple[PrediccionIA, dict[str, Any] | None]:
    existente = obtener_por_cita_y_version(db, id_cita, version_modelo)
    if existente is not None:
        antes = {
            "probabilidad_no_show": float(existente.probabilidad_no_show),
            "nivel_riesgo": existente.nivel_riesgo,
            "explicabilidad_resumen": existente.explicabilidad_resumen,
        }
        existente.probabilidad_no_show = probabilidad_no_show
        existente.nivel_riesgo = nivel_riesgo
        existente.umbral_aplicado = umbral_aplicado
        existente.features_snapshot = features_snapshot
        existente.explicabilidad_resumen = explicabilidad_resumen
        db.flush()
        return existente, antes

    nueva = PrediccionIA(
        id_cita=id_cita,
        version_modelo=version_modelo,
        probabilidad_no_show=probabilidad_no_show,
        nivel_riesgo=nivel_riesgo,
        umbral_aplicado=umbral_aplicado,
        features_snapshot=features_snapshot,
        explicabilidad_resumen=explicabilidad_resumen,
    )
    db.add(nueva)
    db.flush()
    return nueva, None


def citas_operativas_sin_prediccion(db: Session, version_modelo: str, forzar: bool = False) -> list[Cita]:
    """Obtiene las citas próximas en estado RECIBIDA sin predicción vigente para version_modelo."""
    stmt = (
        select(Cita)
        .where(
            Cita.estado_actual == "RECIBIDA",
            Cita.target_no_show.is_(None),
        )
        .order_by(Cita.fecha_hora_cita.asc(), Cita.id_cita.asc())
    )
    if not forzar:
        subq = (
            select(PrediccionIA.id_cita)
            .where(PrediccionIA.version_modelo == version_modelo)
        )
        stmt = stmt.where(Cita.id_cita.not_in(subq))
    return list(db.scalars(stmt))


def conteos_dataset_bd(db: Session) -> dict[str, int]:
    total_hist = db.scalar(select(func.count(Cita.id_cita)).where(Cita.target_no_show.is_not(None))) or 0
    no_show_hist = db.scalar(select(func.count(Cita.id_cita)).where(Cita.target_no_show == 1)) or 0
    atendidas_hist = db.scalar(select(func.count(Cita.id_cita)).where(Cita.target_no_show == 0)) or 0
    proximas_op = db.scalar(select(func.count(Cita.id_cita)).where(Cita.target_no_show.is_(None))) or 0
    return {
        "total_historicas_bd": int(total_hist),
        "atendidas_bd": int(atendidas_hist),
        "no_show_bd": int(no_show_hist),
        "proximas_bd": int(proximas_op),
    }

