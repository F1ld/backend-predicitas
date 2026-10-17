from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.modules.auditoria.service import registrar_evento
from app.modules.citas import repository
from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.citas.reglas import ESTADOS_DESENLACE, derivar_variables
from app.modules.citas.schemas import CitaImportIn, RechazoOut, ResultadoImportacionOut


def _motivos(error: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()]


def importar_citas(
    db: Session, registros: list[dict], *, id_usuario: int | None, ip: str, origen: str
) -> ResultadoImportacionOut:
    """Valida fila por fila e inserta las válidas en una sola transacción (RF-009, 011, 012, 013)."""
    ids_en_archivo = {str(r.get("id_cita_externa", "")).strip() for r in registros if isinstance(r, dict)}
    ya_existentes = repository.ids_existentes(db, ids_en_archivo)

    rechazos: list[RechazoOut] = []
    validos: list[tuple[CitaImportIn, dict]] = []
    vistos: set[str] = set()

    for fila, bruto in enumerate(registros, start=1):
        id_externo = str(bruto.get("id_cita_externa", "")).strip() if isinstance(bruto, dict) else ""
        try:
            reg = CitaImportIn.model_validate(bruto)
            derivadas = derivar_variables(reg.fecha_hora_cita, reg.fecha_registro_cita)
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

    citas = [
        Cita(
            id_cita_externa=reg.id_cita_externa, paciente_anon_id=reg.paciente_anon_id,
            sede=reg.sede, especialidad=reg.especialidad, medico=reg.medico,
            fecha_hora_cita=reg.fecha_hora_cita, fecha_registro_cita=reg.fecha_registro_cita,
            tipo_paciente=reg.tipo_paciente, canal_origen=reg.canal_origen,
            inasistencias_previas=reg.inasistencias_previas,
            reprogramaciones_prev=reg.reprogramaciones_prev,
            asistencias_previas=reg.asistencias_previas,
            estado_actual=reg.estado_actual,
            target_no_show=ESTADOS_DESENLACE.get(reg.estado_actual),
            **derivadas,
        )
        for reg, derivadas in validos
    ]
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