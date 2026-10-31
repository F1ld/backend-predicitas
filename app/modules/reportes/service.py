import csv
import io
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.citas.models import Cita
from app.modules.ia.models import PrediccionIA
from app.modules.intervenciones.models import Intervencion
from app.modules.lista_espera.models import CupoLiberado, Reasignacion, ListaEspera
from app.modules.reportes.schemas import (
    PorCanalRep02,
    PorEspecialidadRep03,
    Rep02Fila,
    Rep02Out,
    Rep03Fila,
    Rep03Out,
    ResumenRep02,
    ResumenRep03,
)


def generar_rep02(
    db: Session,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    canal_contacto: str | None = None,
    nivel_riesgo: str | None = None,
    especialidad: str | None = None,
) -> Rep02Out:
    stmt = (
        select(Intervencion, Cita, PrediccionIA, CupoLiberado)
        .join(Cita, Cita.id_cita == Intervencion.id_cita)
        .outerjoin(PrediccionIA, PrediccionIA.id_cita == Cita.id_cita)
        .outerjoin(CupoLiberado, CupoLiberado.id_cita_origen == Cita.id_cita)
        .order_by(Intervencion.fecha_hora_envio.desc())
    )

    if desde:
        try:
            d_dt = datetime.fromisoformat(desde)
            stmt = stmt.where(Intervencion.fecha_hora_envio >= d_dt)
        except ValueError:
            pass
    if hasta:
        try:
            h_dt = datetime.fromisoformat(f"{hasta}T23:59:59")
            stmt = stmt.where(Intervencion.fecha_hora_envio <= h_dt)
        except ValueError:
            pass
    if canal_contacto:
        stmt = stmt.where(Intervencion.canal_contacto == canal_contacto.upper())
    if especialidad:
        stmt = stmt.where(Cita.especialidad == especialidad.upper())
    if nivel_riesgo:
        stmt = stmt.where(PrediccionIA.nivel_riesgo == nivel_riesgo.upper())

    resultados = db.execute(stmt).all()

    filas: list[Rep02Fila] = []
    conteo_canal_resp: dict[tuple[str, str | None], int] = {}
    enviadas = 0
    entregadas = 0
    respondidas = 0
    confirmaciones = 0
    liberaciones = 0

    for intervencion, cita, pred, cupo in resultados:
        estado = intervencion.estado_intervencion
        resp = intervencion.respuesta_paciente
        canal = intervencion.canal_contacto

        if estado in ("ENVIADA", "ENTREGADA", "RESPONDIDA"):
            enviadas += 1
        if estado in ("ENTREGADA", "RESPONDIDA"):
            entregadas += 1
        if estado == "RESPONDIDA":
            respondidas += 1
        if resp == "CONFIRMA":
            confirmaciones += 1
        if resp == "SOLICITA_LIBERACION" or cupo is not None:
            liberaciones += 1

        par = (canal, resp)
        conteo_canal_resp[par] = conteo_canal_resp.get(par, 0) + 1

        t_min = None
        if intervencion.fecha_hora_respuesta and intervencion.fecha_hora_envio:
            delta = intervencion.fecha_hora_respuesta - intervencion.fecha_hora_envio
            t_min = max(0, int(delta.total_seconds() // 60))

        filas.append(
            Rep02Fila(
                id_intervencion=intervencion.id_intervencion,
                id_cita_externa=cita.id_cita_externa,
                especialidad=cita.especialidad,
                nivel_riesgo=pred.nivel_riesgo if pred else None,
                canal_contacto=canal,
                estado_intervencion=estado,
                respuesta_paciente=resp,
                tiempo_respuesta_minutos=t_min,
                cupo_liberado=cupo is not None or resp == "SOLICITA_LIBERACION",
            )
        )

    tasa_resp = (respondidas / enviadas) if enviadas > 0 else 0.0

    por_canal: list[PorCanalRep02] = [
        PorCanalRep02(canal_contacto=c, respuesta_paciente=r, cantidad=cnt)
        for (c, r), cnt in conteo_canal_resp.items()
    ]

    return Rep02Out(
        resumen=ResumenRep02(
            enviadas=enviadas,
            entregadas=entregadas,
            respondidas=respondidas,
            confirmaciones=confirmaciones,
            liberaciones=liberaciones,
            tasa_respuesta=round(tasa_resp, 3),
        ),
        por_canal=por_canal,
        filas=filas,
        resultado_simulado=False,
    )


def generar_rep02_csv(reporte: Rep02Out) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID Intervencion",
        "ID Cita Externa",
        "Especialidad",
        "Nivel Riesgo",
        "Canal Contacto",
        "Estado Intervencion",
        "Respuesta Paciente",
        "Tiempo Respuesta (min)",
        "Cupo Liberado",
    ])
    for f in reporte.filas:
        writer.writerow([
            f.id_intervencion,
            f.id_cita_externa,
            f.especialidad,
            f.nivel_riesgo or "Sin predicción",
            f.canal_contacto,
            f.estado_intervencion,
            f.respuesta_paciente or "Sin respuesta",
            f.tiempo_respuesta_minutos if f.tiempo_respuesta_minutos is not None else "",
            "Sí" if f.cupo_liberado else "No",
        ])
    return output.getvalue()


def generar_rep03(
    db: Session,
    *,
    desde: str | None = None,
    hasta: str | None = None,
    especialidad: str | None = None,
    id_operador: int | None = None,
) -> Rep03Out:
    stmt = (
        select(CupoLiberado, Reasignacion, ListaEspera)
        .outerjoin(Reasignacion, Reasignacion.id_cupo_liberado == CupoLiberado.id_cupo_liberado)
        .outerjoin(ListaEspera, ListaEspera.id_candidato == Reasignacion.id_candidato)
        .order_by(CupoLiberado.fecha_hora_cupo.asc())
    )

    if desde:
        try:
            d_dt = datetime.fromisoformat(desde)
            stmt = stmt.where(CupoLiberado.fecha_hora_cupo >= d_dt)
        except ValueError:
            pass
    if hasta:
        try:
            h_dt = datetime.fromisoformat(f"{hasta}T23:59:59")
            stmt = stmt.where(CupoLiberado.fecha_hora_cupo <= h_dt)
        except ValueError:
            pass
    if especialidad:
        stmt = stmt.where(CupoLiberado.especialidad == especialidad.upper())
    if id_operador:
        stmt = stmt.where(Reasignacion.id_operador_confirma == id_operador)

    resultados = db.execute(stmt).all()

    filas: list[Rep03Fila] = []
    especialidades_dict: dict[str, dict[str, int]] = {
        "CARDIOLOGIA": {"liberados": 0, "reasignados": 0},
        "TRAUMATOLOGIA": {"liberados": 0, "reasignados": 0},
        "PEDIATRIA": {"liberados": 0, "reasignados": 0},
    }

    total_liberados = len(resultados)
    total_reasignados = 0
    tiempos_matching_horas: list[float] = []

    for cupo, reasig, cand in resultados:
        esp = cupo.especialidad
        if esp not in especialidades_dict:
            especialidades_dict[esp] = {"liberados": 0, "reasignados": 0}
        especialidades_dict[esp]["liberados"] += 1

        horas_disp = 0.0
        if reasig and reasig.fecha_hora_reasigna and cupo.liberado_en:
            delta = reasig.fecha_hora_reasigna - cupo.liberado_en
            horas_disp = round(max(0.0, delta.total_seconds() / 3600.0), 2)
            tiempos_matching_horas.append(horas_disp)
            total_reasignados += 1
            especialidades_dict[esp]["reasignados"] += 1
        elif cupo.liberado_en:
            delta = datetime.now(timezone.utc) - cupo.liberado_en.replace(tzinfo=timezone.utc if cupo.liberado_en.tzinfo is None else cupo.liberado_en.tzinfo)
            horas_disp = round(max(0.0, delta.total_seconds() / 3600.0), 2)

        filas.append(
            Rep03Fila(
                id_cupo_liberado=cupo.id_cupo_liberado,
                fecha_hora_cupo=cupo.fecha_hora_cupo.isoformat(),
                especialidad=cupo.especialidad,
                medico=cupo.medico,
                horas_disponible=horas_disp,
                paciente_anon_id_asignado=cand.paciente_anon_id if cand else (reasig.paciente_anon_id if hasattr(reasig, 'paciente_anon_id') else None),
                id_operador_confirma=reasig.id_operador_confirma if reasig else None,
                estado_cupo=cupo.estado_cupo,
            )
        )

    tasa_recup = (total_reasignados / total_liberados) if total_liberados > 0 else 0.0
    prom_horas = (sum(tiempos_matching_horas) / len(tiempos_matching_horas)) if tiempos_matching_horas else None

    por_especialidad: list[PorEspecialidadRep03] = [
        PorEspecialidadRep03(especialidad=esp, liberados=datos["liberados"], reasignados=datos["reasignados"])
        for esp, datos in especialidades_dict.items()
        if datos["liberados"] > 0 or datos["reasignados"] > 0
    ]
    if not por_especialidad:
        por_especialidad = [
            PorEspecialidadRep03(especialidad="CARDIOLOGIA", liberados=0, reasignados=0),
            PorEspecialidadRep03(especialidad="TRAUMATOLOGIA", liberados=0, reasignados=0),
            PorEspecialidadRep03(especialidad="PEDIATRIA", liberados=0, reasignados=0),
        ]

    return Rep03Out(
        resumen=ResumenRep03(
            cupos_liberados=total_liberados,
            cupos_reasignados=total_reasignados,
            tasa_recuperacion=round(tasa_recup, 3),
            horas_promedio_matching=round(prom_horas, 2) if prom_horas is not None else None,
        ),
        por_especialidad=por_especialidad,
        filas=filas,
    )


def generar_rep03_csv(reporte: Rep03Out) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID Cupo Liberado",
        "Fecha Hora Cupo",
        "Especialidad",
        "Medico",
        "Horas Disponible",
        "Paciente Asignado",
        "Operador Confirma",
        "Estado Cupo",
    ])
    for f in reporte.filas:
        writer.writerow([
            f.id_cupo_liberado,
            f.fecha_hora_cupo,
            f.especialidad,
            f.medico,
            f.horas_disponible,
            f.paciente_anon_id_asignado or "Sin asignar",
            f.id_operador_confirma if f.id_operador_confirma is not None else "Sin confirmación",
            f.estado_cupo,
        ])
    return output.getvalue()
