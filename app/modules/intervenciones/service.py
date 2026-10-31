from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errores import ConflictoDeNegocio, NoEncontrado, TransicionInvalida
from app.modules.auditoria.service import registrar_evento
from app.modules.auth.models import Usuario
from app.modules.citas.models import Cita, HistorialEstadoCita
from app.modules.citas.reglas import TRANSICIONES, puede_transicionar_a_liberada
from app.modules.intervenciones import repository
from app.modules.intervenciones.models import Intervencion
from app.modules.intervenciones.schemas import (
    BandejaIntervencionesOut,
    CitaSugeridaIntervencionOut,
    ElegibleOut,
    IntervencionCreateIn,
    IntervencionOut,
    IntervencionRespuestaIn,
    PaginaElegiblesOut,
    PaginaIntervencionesOut,
    RiesgoResumen,
)
from app.modules.lista_espera.models import CupoLiberado

# Regla normativa RN07 / RF-066 / RNF-032: máximo 1 recordatorio adicional preventivo por cita.
MAX_RECORDATORIOS_ADICIONALES_POR_CITA = 1
ESTADOS_CITA_INTERVENIBLES = {"RECIBIDA", "CONFIRMADA", "REPROGRAMADA"}


def _enriquecer_out(
    intervencion: Intervencion,
    *,
    estado_cita_actual: str | None = None,
    id_cupo_liberado: int | None = None,
) -> IntervencionOut:
    base = IntervencionOut.model_validate(intervencion)
    base.estado_cita_actual = estado_cita_actual
    base.id_cupo_liberado_generado = id_cupo_liberado
    if getattr(intervencion, "cita", None) is not None:
        base.id_cita_externa = intervencion.cita.id_cita_externa

    acciones = []
    if intervencion.estado_intervencion == "PENDIENTE":
        acciones.append("REGISTRAR_ENVIO")
    elif intervencion.estado_intervencion == "ENVIADA":
        acciones.extend(["REGISTRAR_ENTREGA", "REGISTRAR_FALLO", "REGISTRAR_RESPUESTA"])
    elif intervencion.estado_intervencion == "ENTREGADA":
        acciones.extend(["REGISTRAR_RESPUESTA", "REGISTRAR_FALLO"])
    elif intervencion.estado_intervencion == "RESPONDIDA":
        if intervencion.respuesta_paciente == "CONFIRMA":
            acciones.append("CONFIRMAR_CITA")
        elif intervencion.respuesta_paciente == "SOLICITA_LIBERACION":
            acciones.append("LIBERAR_CUPO")
    if not intervencion.consentimiento_optout:
        acciones.append("REGISTRAR_OPTOUT")
    base.acciones_disponibles = acciones
    return base


def listar_citas_elegibles(
    db: Session,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    especialidad: str | None = None,
    nivel_riesgo: str | None = None,
    limite: int = 50,
    desplazamiento: int = 0,
) -> PaginaElegiblesOut:
    pares = repository.listar_citas_riesgo_medio_alto(
        db,
        nivel_riesgo=nivel_riesgo,
        especialidad=especialidad,
    )
    items: list[ElegibleOut] = []
    vistos: set[int] = set()
    for cita, pred in pares:
        if cita.id_cita in vistos:
            continue
        vistos.add(cita.id_cita)

        if desde:
            try:
                if cita.fecha_hora_cita < datetime.fromisoformat(desde):
                    continue
            except ValueError:
                pass
        if hasta:
            try:
                if cita.fecha_hora_cita > datetime.fromisoformat(f"{hasta}T23:59:59"):
                    continue
            except ValueError:
                pass

        enviadas = repository.contar_activas_por_cita(db, cita.id_cita)
        optout = repository.tiene_optout_vigente(db, cita.id_cita, cita.paciente_anon_id)
        if optout:
            continue

        items.append(
            ElegibleOut(
                id_cita=cita.id_cita,
                id_cita_externa=cita.id_cita_externa,
                paciente_anon_id=cita.paciente_anon_id,
                especialidad=cita.especialidad,
                medico=cita.medico,
                fecha_hora_cita=cita.fecha_hora_cita,
                estado_actual=cita.estado_actual,
                riesgo=RiesgoResumen(
                    id_prediccion=pred.id_prediccion,
                    probabilidad_no_show=float(pred.probabilidad_no_show),
                    nivel_riesgo=pred.nivel_riesgo,
                    version_modelo=pred.version_modelo,
                    fecha_hora_inferencia=pred.fecha_hora_inferencia,
                    resultado_simulado=bool(getattr(pred, "resultado_simulado", False)),
                ),
                intervenciones_previas=enviadas,
            )
        )

    total = len(items)
    paginados = items[desplazamiento : desplazamiento + limite]
    return PaginaElegiblesOut(
        total=total,
        limite=limite,
        desplazamiento=desplazamiento,
        items=paginados,
    )


def listar_bandeja_intervenciones(
    db: Session,
    *,
    nivel_riesgo: str | None = None,
    especialidad: str | None = None,
    estado_intervencion: str | None = None,
    canal_contacto: str | None = None,
) -> BandejaIntervencionesOut:
    pares = repository.listar_citas_riesgo_medio_alto(
        db,
        nivel_riesgo=nivel_riesgo,
        especialidad=especialidad,
    )

    sugeridas: list[CitaSugeridaIntervencionOut] = []
    vistos: set[int] = set()
    for cita, pred in pares:
        if cita.id_cita in vistos:
            continue
        vistos.add(cita.id_cita)
        enviadas = repository.contar_activas_por_cita(db, cita.id_cita)
        optout = repository.tiene_optout_vigente(db, cita.id_cita, cita.paciente_anon_id)
        if pred.nivel_riesgo == "ALTO":
            accion_sug = "CONFIRMACION_PREVIA_O_LIBERACION_VOLUNTARIA"
            canal_sug = "LLAMADA_TELEFONICA"
        else:
            accion_sug = "RECORDATORIO_PREVENTIVO_ADICIONAL"
            canal_sug = "WHATSAPP"

        sugeridas.append(
            CitaSugeridaIntervencionOut(
                id_cita=cita.id_cita,
                id_cita_externa=cita.id_cita_externa,
                paciente_anon_id=cita.paciente_anon_id,
                especialidad=cita.especialidad,
                medico=cita.medico,
                fecha_hora_cita=cita.fecha_hora_cita,
                franja_horaria=cita.franja_horaria,
                estado_actual=cita.estado_actual,
                probabilidad_no_show=pred.probabilidad_no_show,
                nivel_riesgo=pred.nivel_riesgo,
                explicabilidad_resumen=pred.explicabilidad_resumen,
                accion_sugerida=accion_sug,
                canal_sugerido=canal_sug,
                intervenciones_enviadas=enviadas,
                tiene_optout=optout,
            )
        )

    historial = repository.listar_historial(
        db,
        estado_intervencion=estado_intervencion,
        canal_contacto=canal_contacto,
    )
    return BandejaIntervencionesOut(
        total_sugeridas=len(sugeridas),
        total_intervenciones=len(historial),
        citas_sugeridas=sugeridas,
        historial_intervenciones=[IntervencionOut.model_validate(i) for i in historial],
    )


def crear_intervencion(
    db: Session,
    id_cita: int,
    datos: IntervencionCreateIn,
    *,
    usuario: Usuario,
    ip: str,
) -> IntervencionOut:
    cita = db.get(Cita, id_cita, with_for_update=True)
    if cita is None:
        raise NoEncontrado(f"No existe la cita {id_cita}")
    if cita.estado_actual not in ESTADOS_CITA_INTERVENIBLES:
        raise ConflictoDeNegocio(
            f"La cita {id_cita} está en estado '{cita.estado_actual}' y no admite nuevas intervenciones"
        )

    # Regla dura 1: Derecho de oposición / Opt-Out (RF-064, RF-065, RN07)
    if datos.consentimiento_optout or repository.tiene_optout_vigente(db, id_cita, cita.paciente_anon_id):
        raise ConflictoDeNegocio(
            "Envío rechazado: el paciente ejerció su derecho de oposición (consentimiento_optout=True) "
            "y no puede recibir intervenciones preventivas (RF-065 / RN07)"
        )

    # Regla dura 2: Máximo 1 recordatorio adicional por cita (RF-066, RNF-032, RN07)
    enviadas_activas = repository.contar_activas_por_cita(db, id_cita)
    if enviadas_activas >= MAX_RECORDATORIOS_ADICIONALES_POR_CITA:
        raise ConflictoDeNegocio(
            f"Envío rechazado: la cita {id_cita} ya alcanzó el límite normativo de máximo "
            f"{MAX_RECORDATORIOS_ADICIONALES_POR_CITA} recordatorio adicional por cita (RF-066 / RN07)"
        )

    intervencion = Intervencion(
        id_cita=cita.id_cita,
        id_operador=usuario.id_usuario,
        canal_contacto=datos.canal_contacto,
        plantilla_mensaje=datos.plantilla_mensaje,
        consentimiento_optout=False,
        estado_intervencion=datos.estado_intervencion,
    )
    db.add(intervencion)
    db.flush()

    registrar_evento(
        db,
        modulo="INTERVENCION",
        accion="CREATE",
        entidad_afectada="intervenciones",
        direccion_ip=ip,
        id_usuario=usuario.id_usuario,
        id_entidad=intervencion.id_intervencion,
        datos_after={
            "id_cita": cita.id_cita,
            "canal_contacto": intervencion.canal_contacto,
            "plantilla_mensaje": intervencion.plantilla_mensaje,
            "estado_intervencion": intervencion.estado_intervencion,
            "consentimiento_optout": intervencion.consentimiento_optout,
        },
    )
    db.commit()
    db.refresh(intervencion)
    return _enriquecer_out(intervencion, estado_cita_actual=cita.estado_actual)


def registrar_respuesta_intervencion(
    db: Session,
    id_intervencion: int,
    datos: IntervencionRespuestaIn,
    *,
    usuario: Usuario,
    ip: str,
) -> IntervencionOut:
    intervencion = db.get(Intervencion, id_intervencion, with_for_update=True)
    if intervencion is None:
        raise NoEncontrado(f"No existe la intervención {id_intervencion}")

    cita = db.get(Cita, intervencion.id_cita, with_for_update=True)
    if cita is None:
        raise NoEncontrado(f"No existe la cita asociada {intervencion.id_cita}")

    antes_intervencion = {
        "estado_intervencion": intervencion.estado_intervencion,
        "respuesta_paciente": intervencion.respuesta_paciente,
        "consentimiento_optout": intervencion.consentimiento_optout,
        "estado_cita": cita.estado_actual,
    }

    intervencion.respuesta_paciente = datos.respuesta_paciente
    intervencion.estado_intervencion = "RESPONDIDA"
    intervencion.fecha_hora_respuesta = datetime.now(timezone.utc)
    if datos.consentimiento_optout is not None:
        intervencion.consentimiento_optout = datos.consentimiento_optout

    id_cupo_generado: int | None = None
    estado_cita_anterior = cita.estado_actual

    # Caso 1: El paciente CONFIRMA su asistencia -> Cita pasa a CONFIRMADA
    if datos.respuesta_paciente == "CONFIRMA":
        if cita.estado_actual != "CONFIRMADA":
            permitidos = TRANSICIONES.get(cita.estado_actual, set())
            if "CONFIRMADA" not in permitidos:
                raise TransicionInvalida(
                    f"La cita {cita.id_cita} en estado '{cita.estado_actual}' no puede pasar a CONFIRMADA"
                )
            cita.estado_actual = "CONFIRMADA"
            db.add(
                HistorialEstadoCita(
                    id_cita=cita.id_cita,
                    id_usuario_actor=usuario.id_usuario,
                    estado_anterior=estado_cita_anterior,
                    estado_nuevo="CONFIRMADA",
                    motivo_cambio=datos.observacion or "Confirmación del paciente mediante intervención preventiva",
                )
            )

    # Caso 2: El paciente SOLICITA_LIBERACION -> Cita pasa a LIBERADA + Crea CupoLiberado (DISPONIBLE) + Audita LIBERAR
    elif datos.respuesta_paciente == "SOLICITA_LIBERACION":
        if not puede_transicionar_a_liberada(cita.estado_actual):
            raise TransicionInvalida(
                f"La cita {cita.id_cita} en estado '{cita.estado_actual}' no puede liberarse"
            )
        cita.estado_actual = "LIBERADA"
        db.add(
            HistorialEstadoCita(
                id_cita=cita.id_cita,
                id_usuario_actor=usuario.id_usuario,
                estado_anterior=estado_cita_anterior,
                estado_nuevo="LIBERADA",
                motivo_cambio=datos.observacion or "Liberación voluntaria del paciente en intervención (RN04)",
            )
        )

        cupo_existente = repository.obtener_cupo_por_cita_origen(db, cita.id_cita)
        if cupo_existente is None:
            nuevo_cupo = CupoLiberado(
                id_cita_origen=cita.id_cita,
                especialidad=cita.especialidad,
                medico=cita.medico,
                fecha_hora_cupo=cita.fecha_hora_cita,
                estado_cupo="DISPONIBLE",
                origen_liberacion="INTERVENCION_VOLUNTARIA",
            )
            db.add(nuevo_cupo)
            db.flush()
            id_cupo_generado = nuevo_cupo.id_cupo_liberado
        else:
            id_cupo_generado = cupo_existente.id_cupo_liberado

        registrar_evento(
            db,
            modulo="INTERVENCION",
            accion="LIBERAR",
            entidad_afectada="cupos_liberados",
            direccion_ip=ip,
            id_usuario=usuario.id_usuario,
            id_entidad=id_cupo_generado,
            datos_before={"estado_cita": estado_cita_anterior},
            datos_after={
                "id_cita_origen": cita.id_cita,
                "id_intervencion": intervencion.id_intervencion,
                "id_cupo_liberado": id_cupo_generado,
                "estado_cita": "LIBERADA",
                "estado_cupo": "DISPONIBLE",
                "origen_liberacion": "INTERVENCION_VOLUNTARIA",
            },
        )

    # Caso 3: SIN_RESPUESTA o SOLICITA_REPROG -> Prohibición estricta de cancelación/liberación unilateral (RN02 / RF-067)
    elif datos.respuesta_paciente in ("SIN_RESPUESTA", "SOLICITA_REPROG"):
        pass

    registrar_evento(
        db,
        modulo="INTERVENCION",
        accion="UPDATE",
        entidad_afectada="intervenciones",
        direccion_ip=ip,
        id_usuario=usuario.id_usuario,
        id_entidad=intervencion.id_intervencion,
        datos_before=antes_intervencion,
        datos_after={
            "estado_intervencion": intervencion.estado_intervencion,
            "respuesta_paciente": intervencion.respuesta_paciente,
            "consentimiento_optout": intervencion.consentimiento_optout,
            "estado_cita": cita.estado_actual,
            "id_cupo_liberado": id_cupo_generado,
        },
    )
    db.commit()
    db.refresh(intervencion)
    return _enriquecer_out(
        intervencion,
        estado_cita_actual=cita.estado_actual,
        id_cupo_liberado=id_cupo_generado,
    )

