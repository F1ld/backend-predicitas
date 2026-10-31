from sqlalchemy.orm import Session

from app.core.errores import ConflictoDeNegocio, NoEncontrado, ReglaDeNegocioInvalida
from app.modules.auditoria.service import registrar_evento
from app.modules.auth.models import Usuario
from app.modules.citas.models import Cita
from app.modules.citas.reglas import LIMA
from app.modules.lista_espera import repository
from app.modules.lista_espera.models import CupoLiberado, ListaEspera, Reasignacion
from sqlalchemy import select
from app.modules.lista_espera.schemas import (
    CandidatoCreateIn,
    CandidatoOut,
    CandidatoUpdateIn,
    CupoDetalleOut,
    CupoLiberadoOut,
    PropuestaCandidatosOut,
    ReasignacionIn,
    ReasignacionOut,
)


def _franja_de_cupo(db: Session, cupo: CupoLiberado) -> str:
    cita_origen = db.get(Cita, cupo.id_cita_origen)
    if cita_origen is not None:
        return cita_origen.franja_horaria
    hora_lima = cupo.fecha_hora_cupo.astimezone(LIMA).hour
    return "MANANA" if hora_lima < 13 else "TARDE"


def _cupo_a_out(db: Session, cupo: CupoLiberado) -> CupoLiberadoOut:
    out = CupoLiberadoOut.model_validate(cupo)
    cita_origen = db.get(Cita, cupo.id_cita_origen)
    if cita_origen is not None:
        out.id_cita_externa_origen = cita_origen.id_cita_externa
        out.franja_horaria = cita_origen.franja_horaria
    else:
        out.id_cita_externa_origen = f"CIT-{cupo.id_cita_origen}"
        hora_lima = cupo.fecha_hora_cupo.astimezone(LIMA).hour
        out.franja_horaria = "MANANA" if hora_lima < 13 else "TARDE"
    return out


def obtener_detalle_cupo(db: Session, id_cupo: int) -> CupoDetalleOut:
    cupo = db.get(CupoLiberado, id_cupo)
    if cupo is None:
        raise NoEncontrado(f"No existe el cupo liberado {id_cupo}")

    cupo_out = _cupo_a_out(db, cupo)
    reasig = db.execute(
        select(Reasignacion).where(Reasignacion.id_cupo_liberado == id_cupo)
    ).scalar_one_or_none()

    reasig_out = None
    if reasig:
        reasig_out = ReasignacionOut(
            id_reasignacion=reasig.id_reasignacion,
            id_cupo_liberado=reasig.id_cupo_liberado,
            id_candidato=reasig.id_candidato,
            id_operador_confirma=reasig.id_operador_confirma,
            confirmacion_humana=reasig.confirmacion_humana,
            medio_confirmacion=reasig.medio_confirmacion,
            observaciones=reasig.observaciones,
            fecha_hora_reasigna=reasig.fecha_hora_reasigna,
            estado_cupo_final=cupo.estado_cupo,
            estado_candidato_final="ASIGNADO",
        )

    return CupoDetalleOut(
        **cupo_out.model_dump(),
        reasignacion=reasig_out,
        historial_ofertas=[],
    )


def crear_candidato(
    db: Session,
    datos: CandidatoCreateIn,
    *,
    usuario: Usuario,
    ip: str,
) -> CandidatoOut:
    candidato = ListaEspera(
        paciente_anon_id=datos.paciente_anon_id,
        especialidad_req=datos.especialidad_req,
        franja_preferida=datos.franja_preferida,
        estado_candidato="ACTIVO",
        prioridad_registro=datos.prioridad_registro,
    )
    db.add(candidato)
    db.flush()

    registrar_evento(
        db,
        modulo="REASIGNACION",
        accion="CREATE",
        entidad_afectada="lista_espera",
        direccion_ip=ip,
        id_usuario=usuario.id_usuario,
        id_entidad=candidato.id_candidato,
        datos_after={
            "paciente_anon_id": candidato.paciente_anon_id,
            "especialidad_req": candidato.especialidad_req,
            "franja_preferida": candidato.franja_preferida,
            "prioridad_registro": candidato.prioridad_registro,
            "estado_candidato": candidato.estado_candidato,
        },
    )
    db.commit()
    db.refresh(candidato)
    return CandidatoOut.model_validate(candidato)


def actualizar_candidato(
    db: Session,
    id_candidato: int,
    datos: CandidatoUpdateIn,
    *,
    usuario: Usuario,
    ip: str,
) -> CandidatoOut:
    candidato = db.get(ListaEspera, id_candidato, with_for_update=True)
    if candidato is None:
        raise NoEncontrado(f"No existe el candidato {id_candidato} en lista de espera")

    antes = {
        "franja_preferida": candidato.franja_preferida,
        "estado_candidato": candidato.estado_candidato,
        "prioridad_registro": candidato.prioridad_registro,
    }
    if datos.franja_preferida is not None:
        candidato.franja_preferida = datos.franja_preferida
    if datos.estado_candidato is not None:
        candidato.estado_candidato = datos.estado_candidato
    if datos.prioridad_registro is not None:
        candidato.prioridad_registro = datos.prioridad_registro

    registrar_evento(
        db,
        modulo="REASIGNACION",
        accion="UPDATE",
        entidad_afectada="lista_espera",
        direccion_ip=ip,
        id_usuario=usuario.id_usuario,
        id_entidad=candidato.id_candidato,
        datos_before=antes,
        datos_after={
            "franja_preferida": candidato.franja_preferida,
            "estado_candidato": candidato.estado_candidato,
            "prioridad_registro": candidato.prioridad_registro,
        },
    )
    db.commit()
    db.refresh(candidato)
    return CandidatoOut.model_validate(candidato)


def listar_cupos(
    db: Session,
    *,
    estado_cupo: str | None = "DISPONIBLE",
    especialidad: str | None = None,
) -> list[CupoLiberadoOut]:
    cupos = repository.listar_cupos_liberados(db, estado_cupo=estado_cupo, especialidad=especialidad)
    return [_cupo_a_out(db, c) for c in cupos]


def proponer_candidatos_para_cupo(db: Session, id_cupo: int) -> PropuestaCandidatosOut:
    cupo = db.get(CupoLiberado, id_cupo)
    if cupo is None:
        raise NoEncontrado(f"No existe el cupo liberado {id_cupo}")

    franja_cupo = _franja_de_cupo(db, cupo)
    compatibles = repository.buscar_candidatos_compatibles(
        db,
        especialidad=cupo.especialidad,
        franja_cupo=franja_cupo,
    )

    candidatos_out: list[CandidatoOut] = []
    for c in compatibles:
        c_out = CandidatoOut.model_validate(c)
        tipo_match_franja = (
            f"Coincidencia exacta de franja ({franja_cupo})"
            if c.franja_preferida == franja_cupo
            else f"Franja INDIFERENTE compatible con {franja_cupo}"
        )
        c_out.criterio_compatibilidad = (
            f"Especialidad {c.especialidad_req} | {tipo_match_franja} | Prioridad {c.prioridad_registro} (FIFO)"
        )
        candidatos_out.append(c_out)

    return PropuestaCandidatosOut(
        cupo=_cupo_a_out(db, cupo),
        total_compatibles=len(candidatos_out),
        candidatos=candidatos_out,
    )


def reasignar_cupo(
    db: Session,
    id_cupo: int,
    datos: ReasignacionIn,
    *,
    usuario: Usuario,
    ip: str,
) -> ReasignacionOut:
    # Regla dura Human-in-the-Loop (RF-079, RNF-029, RN11)
    if datos.confirmacion_humana is not True:
        raise ReglaDeNegocioInvalida(
            "La reasignación asistida exige confirmación humana explícita (confirmacion_humana=True) (RF-079 / RN11)"
        )

    # Bloqueo pesimista sobre el cupo liberado para impedir doble reasignación concurrente (RF-081)
    cupo = db.get(CupoLiberado, id_cupo, with_for_update=True)
    if cupo is None:
        raise NoEncontrado(f"No existe el cupo liberado {id_cupo}")
    if cupo.estado_cupo not in ("DISPONIBLE", "EN_OFERTA"):
        raise ConflictoDeNegocio(
            f"El cupo {id_cupo} no está disponible para reasignación (estado actual: '{cupo.estado_cupo}')"
        )

    # Bloqueo pesimista sobre el candidato en lista de espera
    candidato = db.get(ListaEspera, datos.id_candidato, with_for_update=True)
    if candidato is None:
        raise NoEncontrado(f"No existe el candidato {datos.id_candidato} en lista de espera")
    if candidato.estado_candidato not in ("ACTIVO", "CONTACTADO"):
        raise ConflictoDeNegocio(
            f"El candidato {datos.id_candidato} no está disponible (estado actual: '{candidato.estado_candidato}')"
        )

    # Validación de compatibilidad de especialidad y franja (RF-074, RF-075)
    franja_cupo = _franja_de_cupo(db, cupo)
    if candidato.especialidad_req != cupo.especialidad:
        raise ConflictoDeNegocio(
            f"Incompatibilidad de especialidad: el cupo es de '{cupo.especialidad}' "
            f"y el candidato requiere '{candidato.especialidad_req}'"
        )
    if candidato.franja_preferida not in (franja_cupo, "INDIFERENTE"):
        raise ConflictoDeNegocio(
            f"Incompatibilidad de franja horaria: el cupo es en turno '{franja_cupo}' "
            f"y el candidato prefiere '{candidato.franja_preferida}'"
        )

    estado_cupo_antes = cupo.estado_cupo
    estado_candidato_antes = candidato.estado_candidato

    cupo.estado_cupo = "REASIGNADO"
    candidato.estado_candidato = "ASIGNADO"

    reasignacion = Reasignacion(
        id_cupo_liberado=cupo.id_cupo_liberado,
        id_candidato=candidato.id_candidato,
        id_operador_confirma=usuario.id_usuario,
        confirmacion_humana=True,
        medio_confirmacion=datos.medio_confirmacion,
        observaciones=datos.observaciones,
    )
    db.add(reasignacion)
    db.flush()

    registrar_evento(
        db,
        modulo="REASIGNACION",
        accion="REASIGNAR",
        entidad_afectada="reasignaciones",
        direccion_ip=ip,
        id_usuario=usuario.id_usuario,
        id_entidad=reasignacion.id_reasignacion,
        datos_before={
            "estado_cupo": estado_cupo_antes,
            "estado_candidato": estado_candidato_antes,
        },
        datos_after={
            "id_reasignacion": reasignacion.id_reasignacion,
            "id_cupo_liberado": cupo.id_cupo_liberado,
            "id_cita_origen": cupo.id_cita_origen,
            "id_candidato": candidato.id_candidato,
            "paciente_anon_id": candidato.paciente_anon_id,
            "confirmacion_humana": True,
            "medio_confirmacion": reasignacion.medio_confirmacion,
            "estado_cupo": "REASIGNADO",
            "estado_candidato": "ASIGNADO",
        },
    )
    db.commit()
    db.refresh(reasignacion)

    return ReasignacionOut(
        id_reasignacion=reasignacion.id_reasignacion,
        id_cupo_liberado=reasignacion.id_cupo_liberado,
        id_candidato=reasignacion.id_candidato,
        id_operador_confirma=reasignacion.id_operador_confirma,
        confirmacion_humana=reasignacion.confirmacion_humana,
        medio_confirmacion=reasignacion.medio_confirmacion,
        observaciones=reasignacion.observaciones,
        fecha_hora_reasigna=reasignacion.fecha_hora_reasigna,
        estado_cupo_final=cupo.estado_cupo,
        estado_candidato_final=candidato.estado_candidato,
    )

