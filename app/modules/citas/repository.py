from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.modules.auditoria.models import AuditoriaEvento
from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.citas.reglas import ACCION_CHECK_IN, ESTADOS_DESENLACE, LIMA
from app.modules.ia.models import PrediccionIA
from app.modules.intervenciones.models import Intervencion
from app.modules.lista_espera.models import CupoLiberado, ListaEspera, Reasignacion


def ids_existentes(db: Session, ids: set[str]) -> set[str]:
    if not ids:
        return set()
    return set(db.scalars(select(Cita.id_cita_externa).where(Cita.id_cita_externa.in_(ids))))


def desenlaces_de(db: Session, pacientes: set[str]) -> dict[str, list[tuple[datetime, str]]]:
    """Citas con desenlace ya registradas de cada paciente: base de los contadores RN17."""
    resultado: dict[str, list[tuple[datetime, str]]] = {p: [] for p in pacientes}
    if not pacientes:
        return resultado
    filas = db.execute(
        select(Cita.paciente_anon_id, Cita.fecha_hora_cita, Cita.estado_actual)
        .where(Cita.paciente_anon_id.in_(pacientes), Cita.estado_actual.in_(ESTADOS_DESENLACE))
    )
    for paciente, fecha, estado in filas:
        resultado[paciente].append((fecha, estado))
    return resultado


def _filtro_check_in():
    return exists().where(
        AuditoriaEvento.modulo == "CITAS", AuditoriaEvento.accion == ACCION_CHECK_IN,
        AuditoriaEvento.entidad_afectada == "citas", AuditoriaEvento.id_entidad == Cita.id_cita,
    )


def _ultima(modelo, orden):
    """Subconsulta con la fila más reciente de `modelo` por cita (evita N+1)."""
    numerada = select(
        modelo, func.row_number().over(partition_by=modelo.id_cita, order_by=orden).label("rn")
    ).subquery()
    return select(numerada).where(numerada.c.rn == 1).subquery()


def listar(
    db: Session, *, desde: date | None, hasta: date | None, especialidad: str | None,
    medico: str | None, estado: str | None, nivel_riesgo: str | None,
    con_intervencion: bool | None, texto: str | None, limite: int, desplazamiento: int,
) -> tuple[int, list]:
    """RF-016, RF-017: una sola consulta con la predicción y la intervención más recientes."""
    pred = _ultima(PrediccionIA, (PrediccionIA.fecha_hora_inferencia.desc(), PrediccionIA.id_prediccion.desc()))
    inter = _ultima(Intervencion, (Intervencion.fecha_hora_envio.desc(), Intervencion.id_intervencion.desc()))
    check_in = _filtro_check_in().label("tiene_check_in")

    consulta = (
        select(Cita, pred.c.id_prediccion, pred.c.probabilidad_no_show, pred.c.nivel_riesgo,
               pred.c.version_modelo, pred.c.fecha_hora_inferencia,
               inter.c.estado_intervencion, inter.c.respuesta_paciente, check_in)
        .outerjoin(pred, pred.c.id_cita == Cita.id_cita)
        .outerjoin(inter, inter.c.id_cita == Cita.id_cita)
    )
    condiciones = []
    if desde:
        condiciones.append(Cita.fecha_hora_cita >= datetime.combine(desde, time.min, tzinfo=LIMA))
    if hasta:
        condiciones.append(Cita.fecha_hora_cita < datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=LIMA))
    if especialidad:
        condiciones.append(Cita.especialidad == especialidad)
    if medico:
        condiciones.append(Cita.medico == medico)
    if estado:
        condiciones.append(Cita.estado_actual == estado)
    if nivel_riesgo == "SIN_PREDICCION":
        condiciones.append(pred.c.id_prediccion.is_(None))
    elif nivel_riesgo:
        condiciones.append(pred.c.nivel_riesgo == nivel_riesgo)
    if con_intervencion is not None:
        condiciones.append(inter.c.id_intervencion.is_not(None) if con_intervencion
                           else inter.c.id_intervencion.is_(None))
    if texto:
        patron = "%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        condiciones.append(or_(
            Cita.id_cita_externa.ilike(patron, escape="\\"), Cita.paciente_anon_id.ilike(patron, escape="\\"),
            Cita.medico.ilike(patron, escape="\\"),
        ))
    if condiciones:
        consulta = consulta.where(and_(*condiciones))

    total = db.scalar(select(func.count()).select_from(consulta.subquery()))
    filas = db.execute(
        consulta.order_by(Cita.fecha_hora_cita, Cita.id_cita).limit(limite).offset(desplazamiento)
    ).all()
    return total, list(filas)


def historial_de(db: Session, id_cita: int) -> list[HistorialEstadoCita]:
    return list(db.scalars(
        select(HistorialEstadoCita)
        .where(HistorialEstadoCita.id_cita == id_cita)
        .order_by(HistorialEstadoCita.fecha_hora_evento, HistorialEstadoCita.id_historial)
    ))


def check_in_de(db: Session, id_cita: int) -> AuditoriaEvento | None:
    return db.scalar(
        select(AuditoriaEvento).where(
            AuditoriaEvento.modulo == "CITAS", AuditoriaEvento.accion == ACCION_CHECK_IN,
            AuditoriaEvento.entidad_afectada == "citas", AuditoriaEvento.id_entidad == id_cita,
        ).order_by(AuditoriaEvento.id_log).limit(1)
    )


def predicciones_de(db: Session, id_cita: int) -> list[PrediccionIA]:
    return list(db.scalars(
        select(PrediccionIA).where(PrediccionIA.id_cita == id_cita)
        .order_by(PrediccionIA.fecha_hora_inferencia.desc(), PrediccionIA.id_prediccion.desc())
    ))


def intervenciones_de(db: Session, id_cita: int) -> list[Intervencion]:
    return list(db.scalars(
        select(Intervencion).where(Intervencion.id_cita == id_cita)
        .order_by(Intervencion.fecha_hora_envio.desc(), Intervencion.id_intervencion.desc())
    ))


def cupo_de(db: Session, id_cita: int) -> CupoLiberado | None:
    return db.scalar(select(CupoLiberado).where(CupoLiberado.id_cita_origen == id_cita))


def ultima_oferta(db: Session, id_cupo: int) -> tuple[AuditoriaEvento, ListaEspera | None] | None:
    """D-014: la oferta vigente de un cupo es su último evento OFERTAR."""
    evento = db.scalar(
        select(AuditoriaEvento).where(
            AuditoriaEvento.modulo == "REASIGNACION", AuditoriaEvento.accion == "OFERTAR",
            AuditoriaEvento.entidad_afectada == "cupos_liberados", AuditoriaEvento.id_entidad == id_cupo,
        ).order_by(AuditoriaEvento.creado_en.desc(), AuditoriaEvento.id_log.desc()).limit(1)
    )
    if evento is None:
        return None
    id_candidato = (evento.datos_after or {}).get("id_candidato")
    return evento, db.get(ListaEspera, id_candidato) if id_candidato is not None else None


def reasignacion_de(db: Session, id_cupo: int) -> tuple[Reasignacion, ListaEspera] | None:
    fila = db.execute(
        select(Reasignacion, ListaEspera)
        .join(ListaEspera, ListaEspera.id_candidato == Reasignacion.id_candidato)
        .where(Reasignacion.id_cupo_liberado == id_cupo)
    ).first()
    return (fila[0], fila[1]) if fila else None


def medicos(db: Session) -> list[str]:
    # Se ordena en Python: el orden no depende de la collation de la base.
    return sorted(db.scalars(select(Cita.medico).distinct()))
