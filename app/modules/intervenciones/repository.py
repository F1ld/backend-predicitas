from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.citas.models import Cita
from app.modules.ia.models import PrediccionIA
from app.modules.intervenciones.models import Intervencion
from app.modules.lista_espera.models import CupoLiberado


def listar_por_cita(db: Session, id_cita: int) -> list[Intervencion]:
    stmt = (
        select(Intervencion)
        .where(Intervencion.id_cita == id_cita)
        .order_by(Intervencion.fecha_hora_envio.desc(), Intervencion.id_intervencion.desc())
    )
    return list(db.scalars(stmt))


def contar_activas_por_cita(db: Session, id_cita: int) -> int:
    stmt = select(func.count(Intervencion.id_intervencion)).where(
        Intervencion.id_cita == id_cita,
        Intervencion.estado_intervencion != "FALLIDA",
    )
    return int(db.scalar(stmt) or 0)


def tiene_optout_vigente(db: Session, id_cita: int, paciente_anon_id: str) -> bool:
    """Verifica si existe derecho de oposición (opt-out) registrado en la cita o para el paciente."""
    stmt = (
        select(Intervencion.id_intervencion)
        .join(Cita, Cita.id_cita == Intervencion.id_cita)
        .where(
            Intervencion.consentimiento_optout.is_(True),
            (Intervencion.id_cita == id_cita) | (Cita.paciente_anon_id == paciente_anon_id),
        )
        .limit(1)
    )
    return db.scalar(stmt) is not None


def listar_historial(
    db: Session,
    *,
    estado_intervencion: str | None = None,
    canal_contacto: str | None = None,
    limite: int = 100,
) -> list[Intervencion]:
    stmt = select(Intervencion).order_by(
        Intervencion.fecha_hora_envio.desc(),
        Intervencion.id_intervencion.desc(),
    )
    if estado_intervencion:
        stmt = stmt.where(Intervencion.estado_intervencion == estado_intervencion.upper())
    if canal_contacto:
        stmt = stmt.where(Intervencion.canal_contacto == canal_contacto.upper())
    return list(db.scalars(stmt.limit(limite)))


def listar_citas_riesgo_medio_alto(
    db: Session,
    *,
    nivel_riesgo: str | None = None,
    especialidad: str | None = None,
) -> list[tuple[Cita, PrediccionIA]]:
    """Retorna citas operativas (RECIBIDA/CONFIRMADA) con predicción en riesgo ALTO o MEDIO."""
    niveles = [nivel_riesgo.upper()] if nivel_riesgo else ["ALTO", "MEDIO"]
    stmt = (
        select(Cita, PrediccionIA)
        .join(PrediccionIA, PrediccionIA.id_cita == Cita.id_cita)
        .where(
            Cita.estado_actual.in_(("RECIBIDA", "CONFIRMADA", "REPROGRAMADA")),
            PrediccionIA.nivel_riesgo.in_(niveles),
        )
        .order_by(
            PrediccionIA.probabilidad_no_show.desc(),
            Cita.fecha_hora_cita.asc(),
        )
    )
    if especialidad:
        stmt = stmt.where(Cita.especialidad == especialidad.upper())
    return list(db.execute(stmt).all())


def obtener_cupo_por_cita_origen(db: Session, id_cita: int) -> CupoLiberado | None:
    stmt = select(CupoLiberado).where(CupoLiberado.id_cita_origen == id_cita)
    return db.scalar(stmt)

