from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.modules.lista_espera.models import CupoLiberado, ListaEspera, Reasignacion


def listar_candidatos(
    db: Session,
    *,
    especialidad_req: str | None = None,
    franja_preferida: str | None = None,
    estado_candidato: str | None = None,
) -> list[ListaEspera]:
    stmt = select(ListaEspera).order_by(
        ListaEspera.prioridad_registro.asc(),
        ListaEspera.fecha_registro.asc(),
        ListaEspera.id_candidato.asc(),
    )
    if especialidad_req:
        stmt = stmt.where(ListaEspera.especialidad_req == especialidad_req.upper())
    if franja_preferida:
        stmt = stmt.where(ListaEspera.franja_preferida == franja_preferida.upper())
    if estado_candidato:
        stmt = stmt.where(ListaEspera.estado_candidato == estado_candidato.upper())
    return list(db.scalars(stmt))


def listar_cupos_liberados(
    db: Session,
    *,
    estado_cupo: str | None = "DISPONIBLE",
    especialidad: str | None = None,
) -> list[CupoLiberado]:
    stmt = select(CupoLiberado).order_by(
        CupoLiberado.fecha_hora_cupo.asc(),
        CupoLiberado.id_cupo_liberado.asc(),
    )
    if estado_cupo and estado_cupo.upper() != "TODOS":
        stmt = stmt.where(CupoLiberado.estado_cupo == estado_cupo.upper())
    if especialidad:
        stmt = stmt.where(CupoLiberado.especialidad == especialidad.upper())
    return list(db.scalars(stmt))


def buscar_candidatos_compatibles(
    db: Session,
    *,
    especialidad: str,
    franja_cupo: str,
) -> list[ListaEspera]:
    """Filtra candidatos ACTIVO/CONTACTADO compatibles por especialidad y franja, ordenados por prioridad y FIFO."""
    preferencia_exacta = case(
        (ListaEspera.franja_preferida == franja_cupo, 0),
        else_=1,
    )
    stmt = (
        select(ListaEspera)
        .where(
            ListaEspera.estado_candidato.in_(("ACTIVO", "CONTACTADO")),
            ListaEspera.especialidad_req == especialidad,
            ListaEspera.franja_preferida.in_((franja_cupo, "INDIFERENTE")),
        )
        .order_by(
            ListaEspera.prioridad_registro.asc(),
            preferencia_exacta.asc(),
            ListaEspera.fecha_registro.asc(),
            ListaEspera.id_candidato.asc(),
        )
    )
    return list(db.scalars(stmt))


def listar_reasignaciones(db: Session) -> list[Reasignacion]:
    stmt = select(Reasignacion).order_by(
        Reasignacion.fecha_hora_reasigna.desc(),
        Reasignacion.id_reasignacion.desc(),
    )
    return list(db.scalars(stmt))

