"""Inferencia de riesgo (F-08 · RF-051 a RF-056, RF-092, RF-098 a RF-101, RF-103, RNF-010,
RNF-012, RNF-015, RNF-023, RN06, RN09, RN16, RN17).

- El snapshot lleva solo las variables de reglas-de-negocio §4.2, tomadas de la cita en el
  momento de inferir: nunca target_no_show, desenlace, check-in ni datos posteriores (RN17).
- La clasificación la hace el backend (§4.4): ALTO si p > umbral; MEDIO si corte ≤ p ≤ umbral;
  BAJO si p < corte (IA_CORTE_MEDIO).
- UNIQUE (id_cita, version_modelo): si ya existe, se devuelve la existente sin volver a inferir.
- La cita nunca se modifica aquí. Un fallo del servicio responde 503 y se audita PREDICT FALLIDO.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errores import Conflicto, MotorIANoDisponible, NoEncontrado
from app.modules.auditoria.service import registrar_evento
from app.modules.auth.models import Usuario
from app.modules.citas.models import Cita
from app.modules.citas.reglas import ESTADOS_ACTIVOS, LIMA
from app.modules.ia import repository
from app.modules.ia.cliente import ClienteIA, ModeloServicio, Variables
from app.modules.ia.models import PrediccionIA
from app.modules.ia.schemas import FallaLote, LoteIn, LoteOut, ModeloActivoOut, PrediccionOut

# Variables autorizadas del snapshot (reglas-de-negocio §4.2). Nada más sale de la cita.
VARIABLES_SNAPSHOT = (
    "especialidad", "tipo_paciente", "antelacion_dias", "canal_origen", "franja_horaria",
    "dia_semana", "inasistencias_previas", "reprogramaciones_prev", "asistencias_previas", "confirmada",
)
MAX_DETALLE_FALLAS = 50
TRES = Decimal("0.001")


def construir_snapshot(cita: Cita) -> dict:
    """Variables disponibles al momento de inferir (RN17, RNF-023). `confirmada` refleja el
    estado actual (RF-032); el resto son datos de registro de la cita."""
    return {
        "especialidad": cita.especialidad,
        "tipo_paciente": cita.tipo_paciente,
        "antelacion_dias": cita.antelacion_dias,
        "canal_origen": cita.canal_origen,
        "franja_horaria": cita.franja_horaria,
        "dia_semana": cita.dia_semana,
        "inasistencias_previas": cita.inasistencias_previas or 0,
        "reprogramaciones_prev": cita.reprogramaciones_prev or 0,
        "asistencias_previas": cita.asistencias_previas or 0,
        "confirmada": cita.estado_actual == "CONFIRMADA",
    }


def es_elegible(cita: Cita, ahora: datetime) -> bool:
    """F-08: estado RECIBIDA, CONFIRMADA o REPROGRAMADA y fecha futura."""
    return cita.estado_actual in ESTADOS_ACTIVOS and cita.fecha_hora_cita > ahora


def clasificar(probabilidad: Decimal, umbral: Decimal, corte_medio: Decimal) -> str:
    """reglas-de-negocio §4.4."""
    if probabilidad > umbral:
        return "ALTO"
    if probabilidad >= corte_medio:
        return "MEDIO"
    return "BAJO"


def a_salida(p: PrediccionIA, ya_existia: bool, resultado_simulado: bool = True) -> PrediccionOut:
    # predicciones_ia no guarda resultado_simulado: mientras el modelo sea sintético todo score
    # se rotula como simulado (RF-056, RN16).
    columnas = {c: getattr(p, c) for c in PrediccionOut.model_fields if hasattr(p, c)}
    return PrediccionOut(**columnas, ya_existia=ya_existia, resultado_simulado=resultado_simulado)


def _auditar_fallo(db: Session, *, id_cita: int, usuario: Usuario, ip: str, motivo: str) -> None:
    """Se confirma aparte: el error se responde, pero el intento queda registrado (RF-103)."""
    registrar_evento(db, modulo="IA", accion="PREDICT", entidad_afectada="citas", direccion_ip=ip,
                     id_usuario=usuario.id_usuario, id_entidad=id_cita,
                     datos_after={"resultado": "FALLIDO", "motivo": motivo})
    db.commit()


def _modelo_habilitado(cliente: ClienteIA) -> ModeloServicio:
    modelo = cliente.obtener_modelo()
    if not modelo.habilitado_piloto:
        raise Conflicto(f"El modelo {modelo.version_modelo} no está habilitado para el piloto",
                        codigo="MODELO_NO_HABILITADO")
    return modelo


def _inferir(db: Session, cliente: ClienteIA, cita: Cita, modelo: ModeloServicio, usuario: Usuario,
             ip: str) -> tuple[PrediccionIA, bool]:
    """Devuelve (predicción, ya_existia). Confirma la predicción y su auditoría juntas.
    Lanza MotorIANoDisponible si el servicio falla (sin haber escrito nada)."""
    existente = repository.por_cita_y_version(db, cita.id_cita, modelo.version_modelo)
    if existente is not None:
        return existente, True

    snapshot = construir_snapshot(cita)
    respuesta = cliente.predecir(cita.id_cita, Variables(**snapshot))
    if respuesta.version_modelo != modelo.version_modelo:  # cambió el modelo entre llamadas
        raise MotorIANoDisponible("El servicio de inferencia respondió con otra versión del modelo.")

    probabilidad = Decimal(str(respuesta.probabilidad_no_show)).quantize(TRES, ROUND_HALF_UP)
    umbral = Decimal(str(respuesta.umbral)).quantize(TRES, ROUND_HALF_UP)
    corte = Decimal(str(get_settings().ia_corte_medio)).quantize(TRES, ROUND_HALF_UP)
    prediccion = PrediccionIA(
        id_cita=cita.id_cita, version_modelo=respuesta.version_modelo, probabilidad_no_show=probabilidad,
        nivel_riesgo=clasificar(probabilidad, umbral, corte), umbral_aplicado=umbral,
        features_snapshot=snapshot, explicabilidad_resumen=respuesta.explicabilidad_resumen,
        fecha_hora_inferencia=datetime.now(timezone.utc),
    )
    db.add(prediccion)
    try:
        db.flush()
    except IntegrityError:  # otra petición guardó la misma (cita, versión) a la vez
        db.rollback()
        return repository.por_cita_y_version(db, cita.id_cita, modelo.version_modelo), True

    registrar_evento(db, modulo="IA", accion="PREDICT", entidad_afectada="predicciones_ia",
                     direccion_ip=ip, id_usuario=usuario.id_usuario, id_entidad=prediccion.id_prediccion,
                     datos_after={"resultado": "EXITOSO", "id_cita": cita.id_cita,
                                  "version_modelo": prediccion.version_modelo,
                                  "probabilidad_no_show": float(probabilidad),
                                  "nivel_riesgo": prediccion.nivel_riesgo})
    db.commit()
    return prediccion, False


def predecir_cita(db: Session, cliente: ClienteIA, id_cita: int, usuario: Usuario, ip: str,
                  ahora: datetime) -> PrediccionOut:
    """M09-E01."""
    cita = db.get(Cita, id_cita)
    if cita is None:
        raise NoEncontrado(f"No existe la cita {id_cita}")
    if not es_elegible(cita, ahora):
        raise Conflicto("Solo se predicen citas futuras en RECIBIDA, CONFIRMADA o REPROGRAMADA",
                        codigo="CITA_NO_ELEGIBLE")
    try:
        modelo = _modelo_habilitado(cliente)
        prediccion, ya_existia = _inferir(db, cliente, cita, modelo, usuario, ip)
    except MotorIANoDisponible:
        db.rollback()
        _auditar_fallo(db, id_cita=id_cita, usuario=usuario, ip=ip, motivo="MOTOR_IA_NO_DISPONIBLE")
        raise
    return a_salida(prediccion, ya_existia, modelo.resultado_simulado)


def predecir_lote(db: Session, cliente: ClienteIA, datos: LoteIn, usuario: Usuario, ip: str,
                  ahora: datetime) -> LoteOut:
    """M09-E02 (RF-100): cada cita en su propia transacción; un fallo no deshace las demás."""
    modelo = _modelo_habilitado(cliente)  # aquí sí: si falla, 503 y no se evalúa nada
    inicio = datetime.combine(datos.desde, time.min, tzinfo=LIMA)
    fin = datetime.combine(datos.hasta + timedelta(days=1), time.min, tzinfo=LIMA)
    ids = repository.citas_en_rango(db, inicio, fin, datos.especialidad)

    resultado = LoteOut(version_modelo=modelo.version_modelo, resultado_simulado=modelo.resultado_simulado)
    for id_cita in ids:
        resultado.evaluadas += 1
        cita = db.get(Cita, id_cita)
        if not es_elegible(cita, ahora):
            resultado.no_elegibles += 1
            continue
        try:
            _, ya_existia = _inferir(db, cliente, cita, modelo, usuario, ip)
        except MotorIANoDisponible:
            db.rollback()
            _auditar_fallo(db, id_cita=id_cita, usuario=usuario, ip=ip, motivo="MOTOR_IA_NO_DISPONIBLE")
            resultado.fallidas += 1
            if len(resultado.detalle_fallas) < MAX_DETALLE_FALLAS:
                resultado.detalle_fallas.append(FallaLote(id_cita=id_cita, codigo="MOTOR_IA_NO_DISPONIBLE"))
            continue
        if ya_existia:
            resultado.existentes += 1
        else:
            resultado.nuevas += 1
    return resultado


def modelo_activo(cliente: ClienteIA) -> ModeloActivoOut:
    """M09-E03: nunca 503; si el servicio no responde, disponible=false."""
    corte = get_settings().ia_corte_medio
    try:
        modelo = cliente.obtener_modelo()
    except MotorIANoDisponible:
        return ModeloActivoOut(disponible=False, latencia_ms=None, corte_medio=corte)
    return ModeloActivoOut(**modelo.model_dump(), disponible=True, latencia_ms=cliente.ultima_latencia_ms,
                           corte_medio=corte)


def listar(db: Session, *, id_cita: int | None, version_modelo: str | None, nivel_riesgo: str | None,
           desde: date | None, hasta: date | None, limite: int, desplazamiento: int) -> dict:
    """M09-E04 (RF-092): orden descendente de fecha_hora_inferencia; desde/hasta en hora de Lima."""
    inicio = datetime.combine(desde, time.min, tzinfo=LIMA) if desde else None
    fin = datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=LIMA) if hasta else None
    total, filas = repository.listar(db, id_cita=id_cita, version_modelo=version_modelo,
                                     nivel_riesgo=nivel_riesgo, inicio=inicio, fin=fin,
                                     limite=limite, desplazamiento=desplazamiento)
    return {"total": total, "limite": limite, "desplazamiento": desplazamiento,
            "items": [a_salida(p, ya_existia=False) for p in filas]}
