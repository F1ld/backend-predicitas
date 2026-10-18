"""Servicio de citas (M02): bandeja, detalle, registro, cambio de estado y check-in.

`transicionar` es el servicio interno que usan otros módulos (contratos/comun.json →
servicios_internos). No hace commit: lo hace quien llama (RNF-014).
"""
from datetime import date, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.dominio import (CANALES_ORIGEN, ESPECIALIDADES, ESTADOS_CITA, NIVELES_RIESGO,
                              TIPOS_PACIENTE)
from app.core.errores import (Conflicto, FueraDePerimetro, NoEncontrado, TransicionInvalida,
                              Validacion)
from app.modules.auditoria.service import registrar_evento
from app.modules.auth.models import Usuario
from app.modules.citas import repository
from app.modules.citas.importer import completar_contadores, nueva_cita, validar_fila
from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.citas.reglas import (ACCION_CHECK_IN, ESTADOS_ACTIVOS, ESTADOS_DESENLACE,
                                      TRANSICIONES, FechaEnDomingo, FechasInconsistentes,
                                      derivar_variables, fecha_lima, franja_de)
from app.modules.citas.schemas import (CambioEstadoIn, CatalogosOut, CheckInOut, CitaDetalleOut,
                                       CitaOut, CitaRegistroIn, CitaResumenOut, CupoOut,
                                       HistorialOut, IntervencionOut, OfertaOut, PaginaCitasOut,
                                       PrediccionOut, ReasignacionOut, RiesgoResumen)
from app.modules.intervenciones.models import Intervencion
from app.modules.lista_espera.models import CupoLiberado

# Mientras el modelo esté entrenado con datos sintéticos, todo score es simulado (RF-056, RN16).
RESULTADO_SIMULADO = True


# ---------------------------------------------------------------- lectura

def listar_citas(
    db: Session, *, desde: date | None, hasta: date | None, especialidad: str | None,
    medico: str | None, estado: str | None, nivel_riesgo: str | None,
    con_intervencion: bool | None, texto: str | None, limite: int, desplazamiento: int,
) -> PaginaCitasOut:
    """M02-E01 (RF-016, RF-017)."""
    total, filas = repository.listar(
        db, desde=desde, hasta=hasta, especialidad=especialidad, medico=medico, estado=estado,
        nivel_riesgo=nivel_riesgo, con_intervencion=con_intervencion, texto=texto,
        limite=limite, desplazamiento=desplazamiento,
    )
    items = []
    for cita, id_pred, prob, nivel, version, fecha_inf, est_int, resp, check_in in filas:
        riesgo = None if id_pred is None else RiesgoResumen(
            id_prediccion=id_pred, probabilidad_no_show=float(prob), nivel_riesgo=nivel,
            version_modelo=version, fecha_hora_inferencia=fecha_inf, resultado_simulado=RESULTADO_SIMULADO,
        )
        items.append(CitaResumenOut(
            **CitaOut.model_validate(cita).model_dump(), riesgo=riesgo,
            estado_intervencion=est_int, respuesta_paciente=resp, tiene_check_in=bool(check_in),
        ))
    return PaginaCitasOut(total=total, limite=limite, desplazamiento=desplazamiento, items=items)


def _acciones_intervencion(inter: Intervencion, cita: Cita) -> list[str]:
    """Acciones de M05 según el estado (reglas-de-negocio F-09). Las ejecuta M05."""
    estado, acciones = inter.estado_intervencion, []
    if estado == "PENDIENTE":
        acciones += ["REGISTRAR_ENVIO", "REGISTRAR_FALLO"]
    elif estado == "ENVIADA":
        acciones += ["REGISTRAR_ENTREGA", "REGISTRAR_FALLO"]
        if inter.canal_contacto == "LLAMADA_TELEFONICA":
            acciones.append("REGISTRAR_RESPUESTA")
    elif estado == "ENTREGADA":
        acciones.append("REGISTRAR_RESPUESTA")
    if estado == "RESPONDIDA" and not inter.consentimiento_optout:
        acciones.append("REGISTRAR_OPTOUT")
    if estado == "RESPONDIDA" and cita.estado_actual in ESTADOS_ACTIVOS:
        if inter.respuesta_paciente == "CONFIRMA" and cita.estado_actual != "CONFIRMADA":
            acciones.append("CONFIRMAR_CITA")
        if inter.respuesta_paciente == "SOLICITA_LIBERACION":
            acciones.append("LIBERAR_CUPO")
    return acciones


def _cupo_out(db: Session, cupo: CupoLiberado, cita: Cita) -> CupoOut:
    oferta = None
    if cupo.estado_cupo == "EN_OFERTA":  # D-014: la vigente es el último OFERTAR
        ultima = repository.ultima_oferta(db, cupo.id_cupo_liberado)
        if ultima and ultima[1] is not None:
            evento, candidato = ultima
            oferta = OfertaOut(id_candidato=candidato.id_candidato, paciente_anon_id=candidato.paciente_anon_id,
                               id_operador=evento.id_usuario, fecha_hora_oferta=evento.creado_en)
    return CupoOut(
        id_cupo_liberado=cupo.id_cupo_liberado, id_cita_origen=cupo.id_cita_origen,
        id_cita_externa_origen=cita.id_cita_externa, especialidad=cupo.especialidad, medico=cupo.medico,
        fecha_hora_cupo=cupo.fecha_hora_cupo, franja_horaria=franja_de(cupo.fecha_hora_cupo),
        estado_cupo=cupo.estado_cupo, origen_liberacion=cupo.origen_liberacion,
        liberado_en=cupo.liberado_en, oferta_vigente=oferta,
    )


def detalle_cita(db: Session, id_cita: int) -> CitaDetalleOut:
    """M02-E02 (RF-018)."""
    cita = db.get(Cita, id_cita)
    if cita is None:
        raise NoEncontrado(f"No existe la cita {id_cita}")
    evento = repository.check_in_de(db, id_cita)
    cupo = repository.cupo_de(db, id_cita)
    reasignacion = repository.reasignacion_de(db, cupo.id_cupo_liberado) if cupo else None
    return CitaDetalleOut(
        **CitaOut.model_validate(cita).model_dump(),
        historial=[HistorialOut.model_validate(h) for h in repository.historial_de(db, id_cita)],
        check_in=CheckInOut(fecha_hora_check_in=evento.creado_en, id_usuario=evento.id_usuario) if evento else None,
        predicciones=[
            PrediccionOut(
                id_prediccion=p.id_prediccion, id_cita=p.id_cita, version_modelo=p.version_modelo,
                probabilidad_no_show=float(p.probabilidad_no_show), nivel_riesgo=p.nivel_riesgo,
                umbral_aplicado=float(p.umbral_aplicado), features_snapshot=p.features_snapshot,
                explicabilidad_resumen=p.explicabilidad_resumen, fecha_hora_inferencia=p.fecha_hora_inferencia,
                resultado_simulado=RESULTADO_SIMULADO, ya_existia=True,
            )
            for p in repository.predicciones_de(db, id_cita)
        ],
        intervenciones=[
            IntervencionOut(
                id_intervencion=i.id_intervencion, id_cita=i.id_cita, id_cita_externa=cita.id_cita_externa,
                id_operador=i.id_operador, canal_contacto=i.canal_contacto, plantilla_mensaje=i.plantilla_mensaje,
                consentimiento_optout=i.consentimiento_optout, estado_intervencion=i.estado_intervencion,
                respuesta_paciente=i.respuesta_paciente, fecha_hora_envio=i.fecha_hora_envio,
                fecha_hora_respuesta=i.fecha_hora_respuesta, acciones_disponibles=_acciones_intervencion(i, cita),
            )
            for i in repository.intervenciones_de(db, id_cita)
        ],
        cupo_liberado=_cupo_out(db, cupo, cita) if cupo else None,
        reasignacion=None if reasignacion is None else ReasignacionOut(
            id_reasignacion=reasignacion[0].id_reasignacion, id_cupo_liberado=reasignacion[0].id_cupo_liberado,
            id_candidato=reasignacion[0].id_candidato, paciente_anon_id=reasignacion[1].paciente_anon_id,
            id_operador_confirma=reasignacion[0].id_operador_confirma,
            confirmacion_humana=reasignacion[0].confirmacion_humana,
            medio_confirmacion=reasignacion[0].medio_confirmacion, observaciones=reasignacion[0].observaciones,
            fecha_hora_reasigna=reasignacion[0].fecha_hora_reasigna,
        ),
    )


def catalogos(db: Session) -> CatalogosOut:
    """M02-E07."""
    return CatalogosOut(
        especialidades=list(ESPECIALIDADES), estados=list(ESTADOS_CITA), niveles_riesgo=list(NIVELES_RIESGO),
        medicos=repository.medicos(db), canales_origen=list(CANALES_ORIGEN), tipos_paciente=list(TIPOS_PACIENTE),
    )


# ---------------------------------------------------------------- registro manual

_PERIMETRO = {"sede", "especialidad"}


def registrar_cita(db: Session, datos: CitaRegistroIn, usuario: Usuario, ip: str, ahora: datetime) -> CitaDetalleOut:
    """M02-E03 (RF-010, F-05): incorpora una cita existente en RECIBIDA. No agenda (RN03)."""
    try:
        reg, derivadas = validar_fila(datos.model_dump(), ahora)
    except ValidationError as exc:
        campos = {".".join(str(p) for p in e["loc"]): e["msg"] for e in exc.errors()}
        if set(campos) & _PERIMETRO:
            raise FueraDePerimetro("La cita está fuera del perímetro del piloto", campos=campos)
        raise Validacion("Los datos enviados no son válidos", campos=campos)
    except FechaEnDomingo as exc:
        raise FueraDePerimetro(str(exc), campos={"fecha_hora_cita": str(exc)})
    except FechasInconsistentes as exc:
        raise Validacion(str(exc), codigo="FECHAS_INCONSISTENTES", campos={"fecha_registro_cita": str(exc)})

    if repository.ids_existentes(db, {reg.id_cita_externa}):
        raise Conflicto(f"Ya existe una cita con id_cita_externa {reg.id_cita_externa}", codigo="CITA_DUPLICADA")

    desenlaces = repository.desenlaces_de(db, {reg.paciente_anon_id})[reg.paciente_anon_id]
    cita = nueva_cita(reg, derivadas, *completar_contadores(reg, desenlaces))
    db.add(cita)
    db.flush()
    db.add(HistorialEstadoCita(
        id_cita=cita.id_cita, id_usuario_actor=usuario.id_usuario, estado_anterior=None,
        estado_nuevo="RECIBIDA", motivo_cambio="Registro manual de una cita existente",
    ))
    registrar_evento(
        db, modulo="CITAS", accion="CREATE", entidad_afectada="citas", direccion_ip=ip,
        id_usuario=usuario.id_usuario, id_entidad=cita.id_cita,
        datos_after=CitaOut.model_validate(cita).model_dump(mode="json"),
    )
    db.commit()  # cita + historial + auditoría (RNF-014)
    return detalle_cita(db, cita.id_cita)


# ---------------------------------------------------------------- cambios de estado

def _foto(cita: Cita) -> dict:
    return {"estado_actual": cita.estado_actual, "target_no_show": cita.target_no_show}


def _validar_transicion(cita: Cita, estado_nuevo: str) -> None:
    permitidos = TRANSICIONES.get(cita.estado_actual, set())
    if estado_nuevo not in permitidos:
        opciones = ", ".join(sorted(permitidos)) or "ninguno (estado final)"
        raise TransicionInvalida(
            f"No se permite pasar de {cita.estado_actual} a {estado_nuevo}. Permitidos: {opciones}"
        )


def _aplicar_transicion(
    db: Session, cita: Cita, estado_nuevo: str, *, usuario: Usuario, ip: str, motivo: str | None,
    antes: dict, extra_despues: dict | None = None,
) -> None:
    _validar_transicion(cita, estado_nuevo)
    estado_anterior = cita.estado_actual
    cita.estado_actual = estado_nuevo
    if estado_nuevo in ESTADOS_DESENLACE:
        cita.target_no_show = ESTADOS_DESENLACE[estado_nuevo]  # el target nace con el desenlace
    db.add(HistorialEstadoCita(
        id_cita=cita.id_cita, id_usuario_actor=usuario.id_usuario,
        estado_anterior=estado_anterior, estado_nuevo=estado_nuevo, motivo_cambio=motivo,
    ))
    registrar_evento(
        db, modulo="CITAS", accion="UPDATE", entidad_afectada="citas", direccion_ip=ip,
        id_usuario=usuario.id_usuario, id_entidad=cita.id_cita, datos_before=antes,
        datos_after={**_foto(cita), **(extra_despues or {})},
    )


def transicionar(db, cita: Cita, estado_nuevo: str, *, usuario: Usuario, ip: str, motivo: str | None = None) -> None:
    """Servicio interno (contratos/comun.json). Valida la transición —LIBERADA solo desde
    RECIBIDA, CONFIRMADA o REPROGRAMADA—, actualiza la cita y target_no_show, e inserta
    historial y auditoría. NO hace commit. Quien llama debe haber bloqueado la fila.
    REPROGRAMADA necesita la nueva fecha: solo por el endpoint M02-E05 (D-011)."""
    if estado_nuevo == "REPROGRAMADA":
        raise TransicionInvalida("REPROGRAMADA exige nueva_fecha_hora_cita: use POST /citas/{id_cita}/estado")
    _aplicar_transicion(db, cita, estado_nuevo, usuario=usuario, ip=ip, motivo=motivo, antes=_foto(cita))


def _validar_campos(cambio: CambioEstadoIn) -> None:
    campos = {}
    estado = cambio.estado_nuevo
    if estado == "REPROGRAMADA" and cambio.nueva_fecha_hora_cita is None:
        campos["nueva_fecha_hora_cita"] = "Obligatoria para REPROGRAMADA"
    if estado != "REPROGRAMADA" and cambio.nueva_fecha_hora_cita is not None:
        campos["nueva_fecha_hora_cita"] = "Solo se admite con REPROGRAMADA"
    if cambio.liberar_cupo and estado != "CANCELADA":
        campos["liberar_cupo"] = "Solo se admite con CANCELADA"
    if cambio.id_intervencion is not None and estado != "CONFIRMADA":
        campos["id_intervencion"] = "Solo se admite con CONFIRMADA"
    if campos:
        raise Validacion("Los datos enviados no son válidos", campos=campos)


def cambiar_estado(
    db: Session, id_cita: int, cambio: CambioEstadoIn, usuario: Usuario, ip: str, ahora: datetime
) -> CitaDetalleOut:
    """M02-E05 (F-06, RF-019 a RF-026, D-011)."""
    _validar_campos(cambio)
    cita = db.get(Cita, id_cita, with_for_update=True)  # bloquea la fila: evita cambios concurrentes
    if cita is None:
        raise NoEncontrado(f"No existe la cita {id_cita}")

    estado = cambio.estado_nuevo
    _validar_transicion(cita, estado)

    antes, extra = _foto(cita), {}
    if estado in ESTADOS_DESENLACE:
        if fecha_lima(cita.fecha_hora_cita) > fecha_lima(ahora):
            raise Conflicto("No se registra un desenlace antes del día de la cita", codigo="DESENLACE_ANTICIPADO")
        if estado == "NO_SHOW" and repository.check_in_de(db, id_cita) is not None:
            raise Conflicto("La cita tiene check-in: no puede ser NO_SHOW", codigo="CHECK_IN_REGISTRADO")

    if estado == "CONFIRMADA" and cambio.id_intervencion is not None:
        inter = db.get(Intervencion, cambio.id_intervencion)
        if inter is None or inter.id_cita != id_cita:
            raise Validacion("La intervención no pertenece a esta cita",
                             campos={"id_intervencion": "No existe o es de otra cita"})
        extra["id_intervencion"] = inter.id_intervencion

    if estado == "REPROGRAMADA":
        nueva = cambio.nueva_fecha_hora_cita
        try:
            derivadas = derivar_variables(nueva, cita.fecha_registro_cita)
        except FechaEnDomingo as exc:
            raise FueraDePerimetro(str(exc), campos={"nueva_fecha_hora_cita": str(exc)})
        except FechasInconsistentes as exc:
            raise Validacion(str(exc), campos={"nueva_fecha_hora_cita": "Anterior a fecha_registro_cita"})
        campos_fecha = ("fecha_hora_cita", "antelacion_dias", "franja_horaria", "dia_semana", "reprogramaciones_prev")
        antes.update({c: getattr(cita, c) for c in campos_fecha})
        antes["fecha_hora_cita"] = cita.fecha_hora_cita.isoformat()
        cita.fecha_hora_cita = nueva
        for clave, valor in derivadas.items():
            setattr(cita, clave, valor)
        cita.reprogramaciones_prev += 1  # D-011
        extra = {c: getattr(cita, c) for c in campos_fecha}
        extra["fecha_hora_cita"] = nueva.isoformat()

    cupo = None
    if estado == "CANCELADA" and cambio.liberar_cupo:
        if cita.fecha_hora_cita <= ahora:
            raise Conflicto("Solo se libera el cupo de una cita futura", codigo="CITA_PASADA")
        cupo = CupoLiberado(
            id_cita_origen=cita.id_cita, especialidad=cita.especialidad, medico=cita.medico,
            fecha_hora_cupo=cita.fecha_hora_cita, estado_cupo="DISPONIBLE", origen_liberacion="CANCELACION_EXTERNA",
        )

    _aplicar_transicion(db, cita, estado, usuario=usuario, ip=ip, motivo=cambio.motivo, antes=antes,
                        extra_despues=extra)
    if cupo is not None:
        db.add(cupo)
        db.flush()
        registrar_evento(
            db, modulo="REASIGNACION", accion="LIBERAR", entidad_afectada="cupos_liberados", direccion_ip=ip,
            id_usuario=usuario.id_usuario, id_entidad=cupo.id_cupo_liberado,
            datos_after={"id_cita_origen": cita.id_cita, "estado_cupo": cupo.estado_cupo,
                         "origen_liberacion": cupo.origen_liberacion,
                         "fecha_hora_cupo": cupo.fecha_hora_cupo.isoformat()},
        )
    db.commit()  # cita + historial + cupo + auditoría: todo o nada (RNF-014)
    return detalle_cita(db, id_cita)


# ---------------------------------------------------------------- check-in

def registrar_check_in(
    db: Session, id_cita: int, observacion: str | None, usuario: Usuario, ip: str, ahora: datetime
) -> CheckInOut:
    """M02-E06 (RF-104, D-012): evento CHECK_IN en auditoria_eventos, sin cambiar el estado."""
    cita = db.get(Cita, id_cita, with_for_update=True)  # serializa check-ins simultáneos
    if cita is None:
        raise NoEncontrado(f"No existe la cita {id_cita}")
    if cita.estado_actual not in ESTADOS_ACTIVOS:
        raise Conflicto(f"La cita está en un estado final ({cita.estado_actual})", codigo="ESTADO_FINAL")
    if fecha_lima(cita.fecha_hora_cita) != fecha_lima(ahora):
        raise Conflicto("El check-in solo se registra el día de la cita", codigo="FUERA_DE_FECHA")
    if repository.check_in_de(db, id_cita) is not None:
        raise Conflicto("La cita ya tiene check-in", codigo="CHECK_IN_DUPLICADO")

    evento = registrar_evento(
        db, modulo="CITAS", accion=ACCION_CHECK_IN, entidad_afectada="citas", direccion_ip=ip,
        id_usuario=usuario.id_usuario, id_entidad=id_cita,
        datos_after={"estado_actual": cita.estado_actual, "observacion": observacion},
    )
    db.flush()
    db.refresh(evento)  # creado_en lo pone la base
    db.commit()
    return CheckInOut(fecha_hora_check_in=evento.creado_en, id_usuario=usuario.id_usuario)
