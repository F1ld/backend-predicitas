from sqlalchemy import select

from app.modules.auditoria.models import AuditoriaEvento
from app.modules.citas.importer import importar_citas
from app.modules.citas.models import Cita
from app.modules.lista_espera.models import CupoLiberado, ListaEspera, Reasignacion
from tests.conftest import cabecera


def _liberar_cita_y_obtener_cupo(client, db, id_usuario: int, headers: dict) -> int:
    importar_citas(
        db,
        [
            {
                "id_cita_externa": "CIT-REA-001",
                "paciente_anon_id": "PAC-REA-ORIG",
                "sede": "SAN_ISIDRO",
                "especialidad": "PEDIATRIA",
                "medico": "Dra. Morales",
                "fecha_hora_cita": "2026-11-06T15:00:00-05:00",  # Franja TARDE
                "fecha_registro_cita": "2026-10-10T10:00:00-05:00",
                "tipo_paciente": "NUEVO",
                "canal_origen": "WEB",
                "estado_actual": "RECIBIDA",
            }
        ],
        id_usuario=id_usuario,
        ip="127.0.0.1",
        origen="test_reasignacion",
    )
    cita = db.scalar(select(Cita).where(Cita.id_cita_externa == "CIT-REA-001"))
    interv = client.post(
        f"/citas/{cita.id_cita}/intervenciones",
        headers=headers,
        json={"canal_contacto": "WHATSAPP"},
    ).json()
    resp = client.patch(
        f"/intervenciones/{interv['id_intervencion']}",
        headers=headers,
        json={"respuesta_paciente": "SOLICITA_LIBERACION"},
    ).json()
    return resp["id_cupo_liberado_generado"]


def test_flujo_completo_lista_espera_matching_y_reasignacion_con_confirmacion_humana(client, usuarios, db):
    h = cabecera(client, usuarios["RECEPCION"])
    id_cupo = _liberar_cita_y_obtener_cupo(client, db, usuarios["ADMINISTRADOR"].id_usuario, h)

    # 1. Verificar que el cupo figure como DISPONIBLE en GET /cupos-liberados
    r_cupos = client.get("/cupos-liberados", headers=h)
    assert r_cupos.status_code == 200
    assert any(c["id_cupo_liberado"] == id_cupo for c in r_cupos.json())

    # 2. Registrar candidatos en lista de espera (distintas prioridades, franjas y especialidades)
    c_incomp_esp = client.post(
        "/lista-espera",
        headers=h,
        json={"paciente_anon_id": "PAC-ESP-CARDIO", "especialidad_req": "CARDIOLOGIA", "franja_preferida": "TARDE", "prioridad_registro": 1},
    ).json()
    c_incomp_franja = client.post(
        "/lista-espera",
        headers=h,
        json={"paciente_anon_id": "PAC-ESP-MANANA", "especialidad_req": "PEDIATRIA", "franja_preferida": "MANANA", "prioridad_registro": 1},
    ).json()
    c_prio2 = client.post(
        "/lista-espera",
        headers=h,
        json={"paciente_anon_id": "PAC-ESP-PRIO2", "especialidad_req": "PEDIATRIA", "franja_preferida": "TARDE", "prioridad_registro": 2},
    ).json()
    c_prio1_indif = client.post(
        "/lista-espera",
        headers=h,
        json={"paciente_anon_id": "PAC-ESP-PRIO1-IND", "especialidad_req": "PEDIATRIA", "franja_preferida": "INDIFERENTE", "prioridad_registro": 1},
    ).json()
    c_prio1_exacto = client.post(
        "/lista-espera",
        headers=h,
        json={"paciente_anon_id": "PAC-ESP-PRIO1-TARDE", "especialidad_req": "PEDIATRIA", "franja_preferida": "TARDE", "prioridad_registro": 1},
    ).json()

    # 3. Algoritmo de emparejamiento GET /cupos-liberados/{id_cupo}/candidatos
    r_prop = client.get(f"/cupos-liberados/{id_cupo}/candidatos", headers=h)
    assert r_prop.status_code == 200, r_prop.text
    prop = r_prop.json()
    ids_compatibles = [c["id_candidato"] for c in prop["candidatos"]]

    # Excluye incompatibles por especialidad o franja
    assert c_incomp_esp["id_candidato"] not in ids_compatibles
    assert c_incomp_franja["id_candidato"] not in ids_compatibles
    # Ordena primero prioridad 1 con franja exacta TARDE, luego prioridad 1 INDIFERENTE, luego prioridad 2
    assert ids_compatibles[:3] == [
        c_prio1_exacto["id_candidato"],
        c_prio1_indif["id_candidato"],
        c_prio2["id_candidato"],
    ]

    # 4. Rechaza reasignación si confirmacion_humana == False (HTTP 422 — RN11 / RF-079)
    r_sin_humano = client.post(
        f"/cupos-liberados/{id_cupo}/reasignar",
        headers=h,
        json={
            "id_candidato": c_prio1_exacto["id_candidato"],
            "confirmacion_humana": False,
            "medio_confirmacion": "LLAMADA_CONFIRMADA",
        },
    )
    assert r_sin_humano.status_code == 422

    # 5. Ejecuta reasignación asistida con confirmacion_humana == True
    r_reasig = client.post(
        f"/cupos-liberados/{id_cupo}/reasignar",
        headers=h,
        json={
            "id_candidato": c_prio1_exacto["id_candidato"],
            "confirmacion_humana": True,
            "medio_confirmacion": "LLAMADA_CONFIRMADA",
            "observaciones": "Madre del paciente confirma asistencia telefónicamente",
        },
    )
    assert r_reasig.status_code == 200, r_reasig.text
    datos_reasig = r_reasig.json()
    assert datos_reasig["confirmacion_humana"] is True
    assert datos_reasig["estado_cupo_final"] == "REASIGNADO"
    assert datos_reasig["estado_candidato_final"] == "ASIGNADO"

    # 6. Impedir doble reasignación del mismo cupo (HTTP 409 — RF-081)
    r_doble = client.post(
        f"/cupos-liberados/{id_cupo}/reasignar",
        headers=h,
        json={
            "id_candidato": c_prio1_indif["id_candidato"],
            "confirmacion_humana": True,
            "medio_confirmacion": "PRESENCIAL",
        },
    )
    assert r_doble.status_code == 409

    # 7. Verificar persistencia en tablas reasignaciones, cupos_liberados, lista_espera y auditoria_eventos
    db.expire_all()
    cupo_bd = db.get(CupoLiberado, id_cupo)
    cand_bd = db.get(ListaEspera, c_prio1_exacto["id_candidato"])
    reasig_bd = db.get(Reasignacion, datos_reasig["id_reasignacion"])
    assert cupo_bd.estado_cupo == "REASIGNADO"
    assert cand_bd.estado_candidato == "ASIGNADO"
    assert reasig_bd is not None and reasig_bd.confirmacion_humana is True

    ev_rea = db.scalar(
        select(AuditoriaEvento).where(
            AuditoriaEvento.modulo == "REASIGNACION",
            AuditoriaEvento.accion == "REASIGNAR",
            AuditoriaEvento.id_entidad == reasig_bd.id_reasignacion,
        )
    )
    assert ev_rea is not None

