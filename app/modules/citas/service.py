from datetime import date

from sqlalchemy.orm import Session

from app.core.errores import NoEncontrado, TransicionInvalida
from app.modules.auditoria.service import registrar_evento
from app.modules.auth.models import Usuario
from app.modules.citas import repository
from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.citas.reglas import ESTADOS_DESENLACE, TRANSICIONES
from app.modules.citas.schemas import CitaDetalleOut, CitaOut, HistorialOut, PaginaCitasOut


def listar_citas(
    db: Session, *, desde: date | None, hasta: date | None, especialidad: str | None,
    estado: str | None, texto: str | None, limite: int, desplazamiento: int,
) -> PaginaCitasOut:
    total, items = repository.listar(
        db, desde=desde, hasta=hasta, especialidad=especialidad, estado=estado,
        texto=texto, limite=limite, desplazamiento=desplazamiento,
    )
    return PaginaCitasOut(
        total=total, limite=limite, desplazamiento=desplazamiento,
        items=[CitaOut.model_validate(c) for c in items],
    )


def detalle_cita(db: Session, id_cita: int) -> CitaDetalleOut:
    cita = db.get(Cita, id_cita)
    if cita is None:
        raise NoEncontrado(f"No existe la cita {id_cita}")
    historial = [HistorialOut.model_validate(h) for h in repository.historial_de(db, id_cita)]
    return CitaDetalleOut(**CitaOut.model_validate(cita).model_dump(), historial=historial)


def cambiar_estado(
    db: Session, id_cita: int, estado_nuevo: str, motivo: str | None, usuario: Usuario, ip: str
) -> CitaDetalleOut:
    cita = db.get(Cita, id_cita, with_for_update=True)  # bloquea la fila: evita cambios concurrentes
    if cita is None:
        raise NoEncontrado(f"No existe la cita {id_cita}")

    permitidos = TRANSICIONES.get(cita.estado_actual, set())
    if estado_nuevo not in permitidos:
        opciones = ", ".join(sorted(permitidos)) or "ninguno (estado final)"
        raise TransicionInvalida(
            f"No se permite pasar de {cita.estado_actual} a {estado_nuevo}. Permitidos: {opciones}"
        )

    antes = {"estado_actual": cita.estado_actual, "target_no_show": cita.target_no_show}
    cita.estado_actual = estado_nuevo
    if estado_nuevo in ESTADOS_DESENLACE:
        cita.target_no_show = ESTADOS_DESENLACE[estado_nuevo]  # el target nace con el desenlace

    db.add(HistorialEstadoCita(
        id_cita=id_cita, id_usuario_actor=usuario.id_usuario,
        estado_anterior=antes["estado_actual"], estado_nuevo=estado_nuevo, motivo_cambio=motivo,
    ))
    registrar_evento(
        db, modulo="CITAS", accion="UPDATE", entidad_afectada="citas", direccion_ip=ip,
        id_usuario=usuario.id_usuario, id_entidad=id_cita, datos_before=antes,
        datos_after={"estado_actual": cita.estado_actual, "target_no_show": cita.target_no_show},
    )
    db.commit()  # cita + historial + auditoría: todo o nada (RNF-014)
    return detalle_cita(db, id_cita)