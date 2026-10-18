"""Permisos del rol operativo predicitas_app (RNF-009, D-015, Diseño de BD §5).

Se conectan con DATABASE_URL, que debe apuntar al rol predicitas_app. Si no hay
conexión o el rol es otro, las pruebas se omiten con el motivo: nunca dan falso verde.
Cada prueba corre en una transacción que se revierte al final.
"""
import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

ROL_APP = "predicitas_app"


def _url() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if url is None:
        try:
            from app.core.config import get_settings
            url = get_settings().database_url
        except Exception:
            return None
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def conexion():
    url = _url()
    if not url:
        pytest.skip("Sin DATABASE_URL: no hay conexión de prueba con el rol predicitas_app.")
    try:
        conn = psycopg.connect(url)
    except psycopg.OperationalError as e:
        pytest.skip(f"No se pudo conectar con DATABASE_URL ({type(e).__name__}).")
    usuario = conn.execute("SELECT current_user").fetchone()[0]
    if usuario != ROL_APP:
        conn.close()
        pytest.skip(f"DATABASE_URL usa el rol '{usuario}', no '{ROL_APP}'.")
    conn.rollback()
    yield conn
    conn.close()


@pytest.fixture
def cur(conexion):
    with conexion.cursor() as c:
        yield c
    conexion.rollback()


def _insertar_cita(cur) -> int:
    ahora = datetime.now(timezone.utc)
    cur.execute(
        """INSERT INTO citas (id_cita_externa, paciente_anon_id, sede, especialidad, medico,
               fecha_hora_cita, fecha_registro_cita, antelacion_dias, tipo_paciente,
               canal_origen, franja_horaria, dia_semana, estado_actual)
           VALUES ('CIT-BD-0001', 'PAC-BD-0001', 'SAN_ISIDRO', 'CARDIOLOGIA', 'Dr. Sintético',
               %s, %s, 7, 'NUEVO', 'WEB', 'MANANA', 'LUNES', 'RECIBIDA')
           RETURNING id_cita""",
        (ahora + timedelta(days=7), ahora),
    )
    return cur.fetchone()[0]


def _insertar_auditoria(cur, id_entidad=None) -> int:
    cur.execute(
        """INSERT INTO auditoria_eventos (modulo, accion, entidad_afectada, id_entidad,
               datos_before, datos_after, direccion_ip)
           VALUES ('citas', 'CREAR', 'citas', %s, NULL, %s, '127.0.0.1') RETURNING id_log""",
        (id_entidad, Jsonb({"estado_actual": "RECIBIDA"})),
    )
    return cur.fetchone()[0]


def _insertar_historial(cur, id_cita: int) -> int:
    cur.execute(
        """INSERT INTO historial_estados_cita (id_cita, estado_anterior, estado_nuevo, motivo_cambio)
           VALUES (%s, NULL, 'RECIBIDA', 'Registro sintético') RETURNING id_historial""",
        (id_cita,),
    )
    return cur.fetchone()[0]


@pytest.mark.parametrize(("tabla", "privilegio", "esperado"), [
    ("auditoria_eventos", "INSERT", True),
    ("auditoria_eventos", "SELECT", True),
    ("auditoria_eventos", "UPDATE", False),
    ("auditoria_eventos", "DELETE", False),
    ("auditoria_eventos", "TRUNCATE", False),
    ("historial_estados_cita", "INSERT", True),
    ("historial_estados_cita", "UPDATE", False),
    ("historial_estados_cita", "DELETE", False),
    ("citas", "UPDATE", True),
    ("citas", "DELETE", False),
])
def test_privilegios_del_rol(cur, tabla, privilegio, esperado):
    cur.execute("SELECT has_table_privilege(%s, %s)", (tabla, privilegio))
    assert cur.fetchone()[0] is esperado


def test_insert_y_select_en_auditoria(cur):
    id_log = _insertar_auditoria(cur)
    cur.execute("SELECT accion FROM auditoria_eventos WHERE id_log = %s", (id_log,))
    assert cur.fetchone() == ("CREAR",)


@pytest.mark.parametrize("sentencia", [
    "UPDATE auditoria_eventos SET accion = 'X' WHERE id_log = %s",
    "DELETE FROM auditoria_eventos WHERE id_log = %s",
])
def test_auditoria_no_se_modifica_ni_borra(cur, sentencia):
    id_log = _insertar_auditoria(cur)
    with pytest.raises(errors.InsufficientPrivilege):
        cur.execute(sentencia, (id_log,))


@pytest.mark.parametrize("sentencia", [
    "UPDATE historial_estados_cita SET estado_nuevo = 'CANCELADA' WHERE id_historial = %s",
    "DELETE FROM historial_estados_cita WHERE id_historial = %s",
])
def test_historial_no_se_modifica_ni_borra(cur, sentencia):
    id_historial = _insertar_historial(cur, _insertar_cita(cur))
    with pytest.raises(errors.InsufficientPrivilege):
        cur.execute(sentencia, (id_historial,))


def test_citas_no_se_borran(cur):
    id_cita = _insertar_cita(cur)
    with pytest.raises(errors.InsufficientPrivilege):
        cur.execute("DELETE FROM citas WHERE id_cita = %s", (id_cita,))


def test_operacion_normal_cita_historial_auditoria(cur):
    """Flujo atómico de la app (RNF-014): cita + historial + auditoría, y un UPDATE de estado."""
    id_cita = _insertar_cita(cur)
    _insertar_historial(cur, id_cita)
    _insertar_auditoria(cur, id_entidad=id_cita)
    cur.execute("UPDATE citas SET estado_actual = 'CONFIRMADA' WHERE id_cita = %s", (id_cita,))
    assert cur.rowcount == 1
    cur.execute(
        """SELECT (SELECT count(*) FROM historial_estados_cita WHERE id_cita = %s),
                  (SELECT count(*) FROM auditoria_eventos WHERE id_entidad = %s)""",
        (id_cita, id_cita),
    )
    assert cur.fetchone() == (1, 1)
