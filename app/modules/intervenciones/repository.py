from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.modules.citas.models import Cita
from app.modules.citas.reglas import ESTADOS_ACTIVOS, LIMA
from app.modules.ia.models import PrediccionIA
from app.modules.intervenciones.models import Intervencion
from app.modules.intervenciones.reglas import MAX_FALLIDAS, NIVELES_ELEGIBLES
from app.modules.lista_espera.models import CupoLiberado


def _inicio(dia: date) -> datetime:
    return datetime.combine(dia, time.min, tzinfo=LIMA)


def _ultima_prediccion():
    """Predicción más reciente de cada cita (una fila por id_cita, sin N+1)."""
    numerada = select(
        PrediccionIA.id_prediccion, PrediccionIA.id_cita, PrediccionIA.probabilidad_no_show,
        PrediccionIA.nivel_riesgo, PrediccionIA.version_modelo, PrediccionIA.fecha_hora_inferencia,
        func.row_number().over(
            partition_by=PrediccionIA.id_cita,
            order_by=(PrediccionIA.fecha_hora_inferencia.desc(), PrediccionIA.id_prediccion.desc()),
        ).label("rn"),
    ).subquery()
    return select(numerada).where(numerada.c.rn == 1).subquery()


def ultima_prediccion_de(db: Session, id_cita: int) -> PrediccionIA | None:
    return db.scalar(
        select(PrediccionIA).where(PrediccionIA.id_cita == id_cita)
        .order_by(PrediccionIA.fecha_hora_inferencia.desc(), PrediccionIA.id_prediccion.desc()).limit(1)
    )


def _optout_vigente(paciente_col):
    otra_cita = aliased(Cita)
    return exists().where(
        Intervencion.id_cita == otra_cita.id_cita,
        otra_cita.paciente_anon_id == paciente_col,
        Intervencion.consentimiento_optout.is_(True),
    )


def optout_vigente(db: Session, paciente_anon_id: str) -> bool:
    """RF-065: un opt-out en cualquier cita del paciente lo bloquea en todas."""
    return bool(db.scalar(select(_optout_vigente(paciente_anon_id))))


def estados_previos(db: Session, id_cita: int) -> list[str]:
    return list(db.scalars(select(Intervencion.estado_intervencion).where(Intervencion.id_cita == id_cita)))


def elegibles(
    db: Session, *, ahora: datetime, desde: date, hasta: date, especialidad: str | None,
    nivel_riesgo: str | None, limite: int, desplazamiento: int,
) -> tuple[int, list]:
    """RF-057: futuras, en estado no final, última predicción ALTO o MEDIO, sin opt-out del
    paciente y que todavía admiten una intervención (misma regla que la creación, RF-066)."""
    pred = _ultima_prediccion()
    previas = (
        select(Intervencion.id_cita, func.count().label("total"),
               func.count().filter(Intervencion.estado_intervencion != "FALLIDA").label("no_fallidas"))
        .group_by(Intervencion.id_cita).subquery()
    )
    total_previas = func.coalesce(previas.c.total, 0)
    condiciones = [
        Cita.estado_actual.in_(ESTADOS_ACTIVOS),
        Cita.fecha_hora_cita > ahora,
        Cita.fecha_hora_cita >= _inicio(desde),
        Cita.fecha_hora_cita < _inicio(hasta + timedelta(days=1)),
        pred.c.nivel_riesgo.in_((nivel_riesgo,) if nivel_riesgo else NIVELES_ELEGIBLES),
        ~_optout_vigente(Cita.paciente_anon_id),
        func.coalesce(previas.c.no_fallidas, 0) == 0,
        total_previas < MAX_FALLIDAS,
    ]
    if especialidad:
        condiciones.append(Cita.especialidad == especialidad)
    consulta = (
        select(Cita, pred.c.id_prediccion, pred.c.probabilidad_no_show, pred.c.nivel_riesgo,
               pred.c.version_modelo, pred.c.fecha_hora_inferencia, total_previas.label("previas"))
        .join(pred, pred.c.id_cita == Cita.id_cita)
        .outerjoin(previas, previas.c.id_cita == Cita.id_cita)
        .where(and_(*condiciones))
    )
    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    orden_nivel = case((pred.c.nivel_riesgo == "ALTO", 0), else_=1)
    filas = db.execute(
        consulta.order_by(orden_nivel, Cita.fecha_hora_cita, Cita.id_cita).limit(limite).offset(desplazamiento)
    ).all()
    return total, list(filas)


def listar(
    db: Session, *, id_cita: int | None, estado: str | None, canal: str | None, respuesta: str | None,
    desde: date | None, hasta: date | None, limite: int, desplazamiento: int,
) -> tuple[int, list[tuple[Intervencion, Cita]]]:
    consulta = select(Intervencion, Cita).join(Cita, Cita.id_cita == Intervencion.id_cita)
    if id_cita is not None:
        consulta = consulta.where(Intervencion.id_cita == id_cita)
    if estado:
        consulta = consulta.where(Intervencion.estado_intervencion == estado)
    if canal:
        consulta = consulta.where(Intervencion.canal_contacto == canal)
    if respuesta:
        consulta = consulta.where(Intervencion.respuesta_paciente == respuesta)
    if desde:
        consulta = consulta.where(Intervencion.fecha_hora_envio >= _inicio(desde))
    if hasta:
        consulta = consulta.where(Intervencion.fecha_hora_envio < _inicio(hasta + timedelta(days=1)))
    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    filas = db.execute(
        consulta.order_by(Intervencion.fecha_hora_envio.desc(), Intervencion.id_intervencion.desc())
        .limit(limite).offset(desplazamiento)
    ).all()
    return total, [(i, c) for i, c in filas]


def con_cita(db: Session, id_intervencion: int, *, bloquear: bool = False) -> tuple[Intervencion, Cita] | None:
    consulta = select(Intervencion, Cita).join(Cita, Cita.id_cita == Intervencion.id_cita).where(
        Intervencion.id_intervencion == id_intervencion)
    if bloquear:
        consulta = consulta.with_for_update()  # bloquea intervención y cita
    fila = db.execute(consulta).first()
    return (fila[0], fila[1]) if fila else None


def cupo_de(db: Session, id_cita: int) -> CupoLiberado | None:
    return db.scalar(select(CupoLiberado).where(CupoLiberado.id_cita_origen == id_cita))


def filas_rep02(
    db: Session, *, desde: date | None, hasta: date | None, canal: str | None,
    nivel_riesgo: str | None, especialidad: str | None,
) -> list:
    """REP-02: una fila por intervención con la última predicción y el cupo voluntario de la cita."""
    pred = _ultima_prediccion()
    cupo_voluntario = exists().where(
        CupoLiberado.id_cita_origen == Intervencion.id_cita,
        CupoLiberado.origen_liberacion == "INTERVENCION_VOLUNTARIA",
    )
    consulta = (
        select(Intervencion, Cita.id_cita_externa, Cita.especialidad, pred.c.nivel_riesgo,
               and_(Intervencion.respuesta_paciente == "SOLICITA_LIBERACION", cupo_voluntario).label("cupo"))
        .join(Cita, Cita.id_cita == Intervencion.id_cita)
        .outerjoin(pred, pred.c.id_cita == Intervencion.id_cita)
    )
    if desde:
        consulta = consulta.where(Intervencion.fecha_hora_envio >= _inicio(desde))
    if hasta:
        consulta = consulta.where(Intervencion.fecha_hora_envio < _inicio(hasta + timedelta(days=1)))
    if canal:
        consulta = consulta.where(Intervencion.canal_contacto == canal)
    if nivel_riesgo:
        consulta = consulta.where(pred.c.nivel_riesgo == nivel_riesgo)
    if especialidad:
        consulta = consulta.where(Cita.especialidad == especialidad)
    return list(db.execute(consulta.order_by(Intervencion.fecha_hora_envio, Intervencion.id_intervencion)).all())
