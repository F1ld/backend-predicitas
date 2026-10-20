from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.auditoria.service import registrar_evento
from app.modules.citas import repository
from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.citas.reglas import (ESTADOS_DESENLACE, ahora_lima, contar_previos,
                                      derivar_variables, fecha_lima)
from app.modules.citas.schemas import CitaImportIn, RechazoOut, ResultadoImportacionOut


class DesenlaceFuturo(ValueError):
    """Fila con ATENDIDA o NO_SHOW y la cita en una fecha futura (F-04)."""


def _motivos(error: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()]


def validar_fila(bruto: dict, ahora: datetime) -> tuple[CitaImportIn, dict]:
    """Validación común de importación (M02-E04) y registro manual (M02-E03).

    Lanza ValidationError (forma o dominio) o ValueError (fechas). Devuelve la fila
    normalizada y sus variables derivadas (RF-011 a RF-014).
    """
    reg = CitaImportIn.model_validate(bruto)
    derivadas = derivar_variables(reg.fecha_hora_cita, reg.fecha_registro_cita)
    if reg.estado_actual in ESTADOS_DESENLACE and fecha_lima(reg.fecha_hora_cita) > fecha_lima(ahora):
        raise DesenlaceFuturo(f"una cita con fecha futura no puede tener desenlace {reg.estado_actual}")
    return reg, derivadas


def completar_contadores(reg: CitaImportIn, desenlaces: list[tuple[datetime, str]]) -> tuple[int, int]:
    """RN17: respeta los contadores informados y calcula los omitidos (§4.3)."""
    inasistencias, asistencias = contar_previos(desenlaces, reg.fecha_registro_cita)
    return (
        reg.inasistencias_previas if reg.inasistencias_previas is not None else inasistencias,
        reg.asistencias_previas if reg.asistencias_previas is not None else asistencias,
    )


def nueva_cita(reg: CitaImportIn, derivadas: dict, inasistencias: int, asistencias: int) -> Cita:
    return Cita(
        id_cita_externa=reg.id_cita_externa, paciente_anon_id=reg.paciente_anon_id,
        sede=reg.sede, especialidad=reg.especialidad, medico=reg.medico,
        fecha_hora_cita=reg.fecha_hora_cita, fecha_registro_cita=reg.fecha_registro_cita,
        tipo_paciente=reg.tipo_paciente, canal_origen=reg.canal_origen,
        inasistencias_previas=inasistencias, reprogramaciones_prev=reg.reprogramaciones_prev,
        asistencias_previas=asistencias, estado_actual=reg.estado_actual,
        target_no_show=ESTADOS_DESENLACE.get(reg.estado_actual), **derivadas,
    )


def importar_citas(
    db: Session, registros: list[dict], *, id_usuario: int | None, ip: str, origen: str,
    ahora: datetime | None = None,
) -> ResultadoImportacionOut:
    """Valida fila por fila e inserta las válidas en una sola transacción (RF-009, 011, 012, 013)."""
    ahora = ahora or ahora_lima()
    ids_en_archivo = {str(r.get("id_cita_externa", "")).strip() for r in registros if isinstance(r, dict)}
    ya_existentes = repository.ids_existentes(db, ids_en_archivo)

    rechazos: list[RechazoOut] = []
    validos: list[tuple[CitaImportIn, dict]] = []
    vistos: set[str] = set()

    for fila, bruto in enumerate(registros, start=1):
        id_externo = str(bruto.get("id_cita_externa", "")).strip() if isinstance(bruto, dict) else ""
        try:
            reg, derivadas = validar_fila(bruto, ahora)
        except ValidationError as exc:  # debe ir antes que ValueError (es su subclase)
            rechazos.append(RechazoOut(fila=fila, id_cita_externa=id_externo, motivos=_motivos(exc)))
            continue
        except ValueError as exc:
            rechazos.append(RechazoOut(fila=fila, id_cita_externa=id_externo, motivos=[str(exc)]))
            continue

        if reg.id_cita_externa in ya_existentes:
            rechazos.append(RechazoOut(fila=fila, id_cita_externa=id_externo,
                                       motivos=["duplicada: ya existe una cita con ese id_cita_externa"]))
            continue
        if reg.id_cita_externa in vistos:
            rechazos.append(RechazoOut(fila=fila, id_cita_externa=id_externo,
                                       motivos=["duplicada dentro del mismo archivo"]))
            continue
        vistos.add(reg.id_cita_externa)
        validos.append((reg, derivadas))

    # En orden de fecha_hora_cita, para que una cita cuente las anteriores del mismo lote (RN17).
    validos.sort(key=lambda par: par[0].fecha_hora_cita)
    desenlaces = repository.desenlaces_de(db, {reg.paciente_anon_id for reg, _ in validos})
    citas: list[Cita] = []
    for reg, derivadas in validos:
        previos = desenlaces[reg.paciente_anon_id]
        citas.append(nueva_cita(reg, derivadas, *completar_contadores(reg, previos)))
        if reg.estado_actual in ESTADOS_DESENLACE:
            previos.append((reg.fecha_hora_cita, reg.estado_actual))
    db.add_all(citas)
    db.flush()  # asigna id_cita a cada cita

    historial: list[HistorialEstadoCita] = []
    for cita in citas:
        historial.append(HistorialEstadoCita(
            id_cita=cita.id_cita, id_usuario_actor=id_usuario, estado_anterior=None,
            estado_nuevo="RECIBIDA", motivo_cambio="Ingreso al piloto por importación",
        ))
        if cita.estado_actual != "RECIBIDA":
            historial.append(HistorialEstadoCita(
                id_cita=cita.id_cita, id_usuario_actor=id_usuario, estado_anterior="RECIBIDA",
                estado_nuevo=cita.estado_actual, motivo_cambio="Estado informado en la importación",
            ))
    db.add_all(historial)

    registrar_evento(
        db, modulo="CITAS", accion="IMPORT", entidad_afectada="citas", direccion_ip=ip,
        id_usuario=id_usuario,
        datos_after={"origen": origen, "recibidas": len(registros),
                     "aceptadas": len(citas), "rechazadas": len(rechazos)},
    )
    db.commit()
    return ResultadoImportacionOut(
        recibidas=len(registros), aceptadas=len(citas),
        rechazadas=len(rechazos), detalle_rechazos=rechazos,
    )
