"""Servicio de M05 · Intervención inteligente (F-09, D-013, RF-057 a RF-068, REP-02).

Toda operación confirma en una sola transacción la intervención (o la cita y el cupo)
junto con su auditoría (RNF-014). La auditoría solo guarda IDs y paciente_anon_id.
"""
from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import Response
from sqlalchemy.orm import Session

from app.core.dominio import CANALES_CONTACTO
from app.core.errores import Conflicto, NoEncontrado, TransicionInvalida, Validacion
from app.core.exportacion import FORMATOS, responder
from app.modules.auditoria.service import registrar_evento
from app.modules.auth.models import Usuario
from app.modules.citas.models import Cita
from app.modules.citas.reglas import ESTADOS_ACTIVOS, fecha_lima, franja_de
from app.modules.citas.service import transicionar
from app.modules.intervenciones import repository
from app.modules.intervenciones.models import Intervencion
from app.modules.intervenciones.reglas import (CONTENIDO_PENDIENTE, NIVELES_ELEGIBLES, PLANTILLAS,
                                               TRANSICIONES_ENVIO, acciones_disponibles,
                                               admite_respuesta, canales_de, puede_crear_otra)
from app.modules.intervenciones.schemas import (CupoOut, ElegibleOut, IntervencionIn, IntervencionOut,
                                                PaginaElegiblesOut, PaginaIntervencionesOut, PlantillaOut,
                                                Rep02Fila, Rep02Out, Rep02PorCanal, Rep02Resumen,
                                                RiesgoResumen)
from app.modules.lista_espera.models import CupoLiberado

MODULO = "INTERVENCION"
# Los envíos son simulados y el riesgo sale de un modelo con datos sintéticos (RF-056, RN16).
RESULTADO_SIMULADO = True
COLUMNAS_REP02 = list(Rep02Fila.model_fields)


def _out(inter: Intervencion, cita: Cita) -> IntervencionOut:
    return IntervencionOut(
        id_intervencion=inter.id_intervencion, id_cita=inter.id_cita, id_cita_externa=cita.id_cita_externa,
        id_operador=inter.id_operador, canal_contacto=inter.canal_contacto,
        plantilla_mensaje=inter.plantilla_mensaje, consentimiento_optout=inter.consentimiento_optout,
        estado_intervencion=inter.estado_intervencion, respuesta_paciente=inter.respuesta_paciente,
        fecha_hora_envio=inter.fecha_hora_envio, fecha_hora_respuesta=inter.fecha_hora_respuesta,
        acciones_disponibles=acciones_disponibles(
            inter.estado_intervencion, inter.canal_contacto, inter.respuesta_paciente,
            inter.consentimiento_optout, cita.estado_actual),
    )


def _foto(inter: Intervencion) -> dict:
    return {"estado_intervencion": inter.estado_intervencion, "respuesta_paciente": inter.respuesta_paciente,
            "consentimiento_optout": inter.consentimiento_optout}


def _buscar(db: Session, id_intervencion: int, *, bloquear: bool = False) -> tuple[Intervencion, Cita]:
    fila = repository.con_cita(db, id_intervencion, bloquear=bloquear)
    if fila is None:
        raise NoEncontrado(f"No existe la intervención {id_intervencion}")
    return fila


def _auditar(db, accion, inter, usuario, ip, antes=None, despues=None, **extra):
    registrar_evento(
        db, modulo=MODULO, accion=accion, entidad_afectada="intervenciones", direccion_ip=ip,
        id_usuario=usuario.id_usuario, id_entidad=inter.id_intervencion,
        datos_before=antes, datos_after={**(despues or _foto(inter)), **extra},
    )


# ---------------------------------------------------------------- lectura

def elegibles(
    db: Session, *, ahora: datetime, desde: date | None, hasta: date | None, especialidad: str | None,
    nivel_riesgo: str | None, limite: int, desplazamiento: int,
) -> PaginaElegiblesOut:
    """M05-E01 (RF-057). Por defecto, de hoy a hoy + 7 (en Lima)."""
    desde = desde or fecha_lima(ahora)
    hasta = hasta or desde + timedelta(days=7)
    total, filas = repository.elegibles(
        db, ahora=ahora, desde=desde, hasta=hasta, especialidad=especialidad, nivel_riesgo=nivel_riesgo,
        limite=limite, desplazamiento=desplazamiento,
    )
    items = [
        ElegibleOut(
            id_cita=cita.id_cita, id_cita_externa=cita.id_cita_externa, paciente_anon_id=cita.paciente_anon_id,
            especialidad=cita.especialidad, medico=cita.medico, fecha_hora_cita=cita.fecha_hora_cita,
            estado_actual=cita.estado_actual, intervenciones_previas=previas,
            riesgo=RiesgoResumen(id_prediccion=id_pred, probabilidad_no_show=float(prob), nivel_riesgo=nivel,
                                 version_modelo=version, fecha_hora_inferencia=fecha,
                                 resultado_simulado=RESULTADO_SIMULADO),
        )
        for cita, id_pred, prob, nivel, version, fecha, previas in filas
    ]
    return PaginaElegiblesOut(total=total, limite=limite, desplazamiento=desplazamiento, items=items)


def listar(db: Session, **filtros) -> PaginaIntervencionesOut:
    """M05-E03."""
    total, filas = repository.listar(db, **filtros)
    return PaginaIntervencionesOut(total=total, limite=filtros["limite"], desplazamiento=filtros["desplazamiento"],
                                   items=[_out(i, c) for i, c in filas])


def detalle(db: Session, id_intervencion: int) -> IntervencionOut:
    """M05-E04."""
    return _out(*_buscar(db, id_intervencion))


def plantillas() -> list[PlantillaOut]:
    """M05-E09: catálogo fijo; el texto aún no está aprobado."""
    return [PlantillaOut(id=nombre, canal_contacto=canal, descripcion=descripcion, contenido=CONTENIDO_PENDIENTE)
            for nombre, canales, descripcion in PLANTILLAS for canal in canales]


# ---------------------------------------------------------------- creación

def crear(db: Session, datos: IntervencionIn, usuario: Usuario, ip: str, ahora: datetime,
          modo_sombra: bool) -> IntervencionOut:
    """M05-E02 (RF-058, RF-063, RF-066, RN07, RN13)."""
    if datos.consentimiento_confirmado is not True:
        raise Validacion("Debe confirmar que el paciente tiene consentimiento para comunicaciones",
                         codigo="CONSENTIMIENTO_REQUERIDO",
                         campos={"consentimiento_confirmado": "Debe ser true"})
    if datos.canal_contacto not in canales_de(datos.plantilla_mensaje):
        raise Validacion("La plantilla no existe o no corresponde al canal",
                         campos={"plantilla_mensaje": "Plantilla no válida para el canal"})

    cita = db.get(Cita, datos.id_cita, with_for_update=True)  # serializa creaciones sobre la misma cita
    if cita is None:
        raise NoEncontrado(f"No existe la cita {datos.id_cita}")
    if modo_sombra:
        raise Conflicto("Modo sombra activo: las intervenciones no se envían", codigo="MODO_SOMBRA")

    prediccion = repository.ultima_prediccion_de(db, cita.id_cita)
    if (cita.estado_actual not in ESTADOS_ACTIVOS or cita.fecha_hora_cita <= ahora
            or prediccion is None or prediccion.nivel_riesgo not in NIVELES_ELEGIBLES):
        raise Conflicto("La cita no es elegible: debe ser futura, no final y con riesgo ALTO o MEDIO",
                        codigo="NO_ELEGIBLE")
    if repository.optout_vigente(db, cita.paciente_anon_id):
        raise Conflicto("El paciente pidió no recibir comunicaciones", codigo="OPTOUT_VIGENTE")
    if not puede_crear_otra(repository.estados_previos(db, cita.id_cita)):
        raise Conflicto("La cita ya tiene su intervención (o su único reintento tras un fallo)",
                        codigo="LIMITE_INTERVENCION")

    inter = Intervencion(
        id_cita=cita.id_cita, id_operador=usuario.id_usuario, canal_contacto=datos.canal_contacto,
        plantilla_mensaje=datos.plantilla_mensaje, consentimiento_optout=False, estado_intervencion="PENDIENTE",
    )
    db.add(inter)
    db.flush()
    _auditar(db, "CREATE", inter, usuario, ip, despues={
        **_foto(inter), "id_cita": cita.id_cita, "canal_contacto": inter.canal_contacto,
        "plantilla_mensaje": inter.plantilla_mensaje, "id_prediccion": prediccion.id_prediccion,
        "consentimiento_confirmado": True,
    })
    db.commit()
    db.refresh(inter)  # fecha_hora_envio la pone la base
    return _out(inter, cita)


# ---------------------------------------------------------------- envío, respuesta y opt-out

def cambiar_estado(db: Session, id_intervencion: int, estado_nuevo: str, usuario: Usuario, ip: str,
                   ahora: datetime) -> IntervencionOut:
    """M05-E05 (RF-059, RF-061): envío simulado."""
    inter, cita = _buscar(db, id_intervencion, bloquear=True)
    permitidos = TRANSICIONES_ENVIO.get(inter.estado_intervencion, set())
    if estado_nuevo not in permitidos:
        opciones = ", ".join(sorted(permitidos)) or "ninguno"
        raise TransicionInvalida(
            f"No se permite pasar de {inter.estado_intervencion} a {estado_nuevo}. Permitidos: {opciones}")
    antes = _foto(inter)
    inter.estado_intervencion = estado_nuevo
    if estado_nuevo == "ENVIADA":
        inter.fecha_hora_envio = ahora  # momento real del envío
    _auditar(db, "UPDATE", inter, usuario, ip, antes=antes)
    db.commit()
    return _out(inter, cita)


def _marcar_optout(db, inter, usuario, ip) -> None:
    antes = _foto(inter)
    inter.consentimiento_optout = True
    _auditar(db, "OPTOUT", inter, usuario, ip, antes=antes)


def responder_intervencion(db: Session, id_intervencion: int, respuesta: str, optout: bool, usuario: Usuario,
                           ip: str, ahora: datetime) -> IntervencionOut:
    """M05-E06 (RF-062, RF-064). Nunca cambia la cita (RF-067, RN02)."""
    inter, cita = _buscar(db, id_intervencion, bloquear=True)
    if not admite_respuesta(inter.estado_intervencion, inter.canal_contacto):
        raise TransicionInvalida(
            f"No se registra una respuesta en estado {inter.estado_intervencion} por {inter.canal_contacto}")
    antes = _foto(inter)
    inter.estado_intervencion = "RESPONDIDA"
    inter.respuesta_paciente = respuesta
    inter.fecha_hora_respuesta = ahora
    _auditar(db, "RESPUESTA", inter, usuario, ip, antes=antes)
    if optout and not inter.consentimiento_optout:
        _marcar_optout(db, inter, usuario, ip)
    db.commit()
    return _out(inter, cita)


def registrar_optout(db: Session, id_intervencion: int, usuario: Usuario, ip: str) -> IntervencionOut:
    """M05-E07 (RF-064). Idempotente: un segundo opt-out no duplica el evento."""
    inter, cita = _buscar(db, id_intervencion, bloquear=True)
    if not inter.consentimiento_optout:
        _marcar_optout(db, inter, usuario, ip)
        db.commit()
    return _out(inter, cita)


# ---------------------------------------------------------------- liberación voluntaria

def liberar_cupo(db: Session, id_intervencion: int, motivo: str | None, usuario: Usuario, ip: str,
                 ahora: datetime) -> CupoOut:
    """M05-E08 (RF-068, RN04): cita LIBERADA + historial + cupo DISPONIBLE + auditoría, todo o nada."""
    inter, cita = _buscar(db, id_intervencion, bloquear=True)
    if inter.respuesta_paciente != "SOLICITA_LIBERACION":
        raise Conflicto("El paciente no solicitó liberar el cupo", codigo="SIN_SOLICITUD_LIBERACION")
    if repository.cupo_de(db, cita.id_cita) is not None:
        raise Conflicto("El cupo de esta cita ya fue liberado", codigo="CUPO_YA_LIBERADO")
    if cita.estado_actual in ESTADOS_ACTIVOS and cita.fecha_hora_cita <= ahora:
        raise Conflicto("Solo se libera el cupo de una cita futura", codigo="CITA_PASADA")

    try:
        transicionar(db, cita, "LIBERADA", usuario=usuario, ip=ip,
                     motivo=motivo or "Liberación voluntaria solicitada por el paciente")  # 409 si es final
        cupo = CupoLiberado(
            id_cita_origen=cita.id_cita, especialidad=cita.especialidad, medico=cita.medico,
            fecha_hora_cupo=cita.fecha_hora_cita, estado_cupo="DISPONIBLE", origen_liberacion="INTERVENCION_VOLUNTARIA",
        )
        db.add(cupo)
        db.flush()
        registrar_evento(
            db, modulo=MODULO, accion="LIBERAR", entidad_afectada="cupos_liberados", direccion_ip=ip,
            id_usuario=usuario.id_usuario, id_entidad=cupo.id_cupo_liberado,
            datos_after={"id_cupo_liberado": cupo.id_cupo_liberado, "id_cita_origen": cita.id_cita,
                         "id_intervencion": inter.id_intervencion, "estado_cupo": cupo.estado_cupo,
                         "origen_liberacion": cupo.origen_liberacion},
        )
        db.commit()  # RNF-014
    except Exception:
        db.rollback()  # nada queda a medias: ni cita LIBERADA sin cupo ni cupo sin cita
        raise
    db.refresh(cupo)
    return CupoOut(
        id_cupo_liberado=cupo.id_cupo_liberado, id_cita_origen=cita.id_cita, id_cita_externa_origen=cita.id_cita_externa,
        especialidad=cupo.especialidad, medico=cupo.medico, fecha_hora_cupo=cupo.fecha_hora_cupo,
        franja_horaria=franja_de(cupo.fecha_hora_cupo), estado_cupo=cupo.estado_cupo,
        origen_liberacion=cupo.origen_liberacion, liberado_en=cupo.liberado_en, oferta_vigente=None,
    )


# ---------------------------------------------------------------- REP-02

def _minutos(inter: Intervencion) -> int | None:
    if inter.fecha_hora_respuesta is None:
        return None
    return max(0, int((inter.fecha_hora_respuesta - inter.fecha_hora_envio).total_seconds() // 60))


def rep02(db: Session, *, desde, hasta, canal, nivel_riesgo, especialidad) -> Rep02Out:
    filas = [
        Rep02Fila(
            id_intervencion=i.id_intervencion, id_cita_externa=id_ext, especialidad=esp, nivel_riesgo=nivel,
            canal_contacto=i.canal_contacto, estado_intervencion=i.estado_intervencion,
            respuesta_paciente=i.respuesta_paciente, tiempo_respuesta_minutos=_minutos(i), cupo_liberado=bool(cupo),
        )
        for i, id_ext, esp, nivel, cupo in repository.filas_rep02(
            db, desde=desde, hasta=hasta, canal=canal, nivel_riesgo=nivel_riesgo, especialidad=especialidad)
    ]
    estados = Counter(f.estado_intervencion for f in filas)
    entregadas = estados["ENTREGADA"] + estados["RESPONDIDA"]
    resumen = Rep02Resumen(
        enviadas=len(filas) - estados["PENDIENTE"], entregadas=entregadas, respondidas=estados["RESPONDIDA"],
        confirmaciones=sum(f.respuesta_paciente == "CONFIRMA" for f in filas),
        liberaciones=sum(f.cupo_liberado for f in filas),
        tasa_respuesta=round(estados["RESPONDIDA"] / entregadas, 3) if entregadas else 0.0,
    )
    grupos = Counter((f.canal_contacto, f.respuesta_paciente) for f in filas)
    por_canal = [Rep02PorCanal(canal_contacto=c, respuesta_paciente=r, cantidad=n)
                 for (c, r), n in sorted(grupos.items(), key=lambda g: (CANALES_CONTACTO.index(g[0][0]), g[0][1] or "~"))]
    return Rep02Out(resumen=resumen, por_canal=por_canal, filas=filas, resultado_simulado=RESULTADO_SIMULADO)


def exportar_rep02(db: Session, formato: str, usuario: Usuario, ip: str, **filtros) -> Rep02Out | Response:
    """M05-E10: json → Rep02Out; csv/xlsx → archivo con las filas y evento EXPORT (comun.json)."""
    formato = (formato or "json").lower()
    if formato not in FORMATOS:
        raise Validacion("Formato no disponible: use json, csv o xlsx", codigo="FORMATO_NO_DISPONIBLE",
                         campos={"formato": "Debe ser json, csv o xlsx"})
    reporte = rep02(db, **filtros)
    if formato == "json":
        return reporte
    respuesta = responder([f.model_dump() for f in reporte.filas], COLUMNAS_REP02, formato, "rep02_intervenciones")
    registrar_evento(
        db, modulo="REPORTES", accion="EXPORT", entidad_afectada="intervenciones", direccion_ip=ip,
        id_usuario=usuario.id_usuario,
        datos_after={"reporte": "REP-02", "formato": formato, "filas": len(reporte.filas),
                     "filtros": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in filtros.items()}},
    )
    db.commit()
    return respuesta
