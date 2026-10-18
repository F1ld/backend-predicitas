"""Gestión de usuarios M01-E06 a M01-E11 (F-03, RF-003 a RF-008, RF-090 · CP-M01-04 y CP-M01-06 a -09)."""
import json

import pytest
from sqlalchemy import select, update

from app.core.errores import Conflicto
from app.modules.auditoria.models import AuditoriaEvento
from app.modules.auth.models import Usuario
from app.modules.usuarios import service
from app.modules.usuarios.schemas import EstadoIn, UsuarioEditarIn
from tests.conftest import CLAVE, cabecera

NUEVO = {"nombre_completo": "Carlos Recepcionista", "correo_institucional": "Carlos.Rec@PrediCitas.crp",
         "rol": "RECEPCION", "clave_inicial": "ClaveSegura2026"}


@pytest.fixture
def admin(client, usuarios, reloj):
    h = cabecera(client, usuarios["ADMINISTRADOR"])
    reloj.avanzar(seconds=1)
    return h


def _codigo(r):
    return r.json()["error"]["codigo"]


def _eventos(db, accion):
    return list(db.scalars(select(AuditoriaEvento).where(
        AuditoriaEvento.modulo == "USUARIOS", AuditoriaEvento.accion == accion)))


# ---------- permisos (RF-003, RNF-001) ----------

@pytest.mark.parametrize("rol", ["RECEPCION", "TECNICO_IA"])
def test_quien_no_es_administrador_recibe_403_en_todo(client, usuarios, rol):
    h = cabecera(client, usuarios[rol])
    otro = usuarios["ADMINISTRADOR"].id_usuario
    peticiones = [
        client.get("/usuarios", headers=h),
        client.post("/usuarios", headers=h, json=NUEVO),
        client.get(f"/usuarios/{otro}", headers=h),
        client.patch(f"/usuarios/{otro}", headers=h, json={"nombre_completo": "X Y"}),
        client.post(f"/usuarios/{otro}/estado", headers=h, json={"activo": False}),
        client.post(f"/usuarios/{otro}/restablecer-acceso", headers=h),
    ]
    for r in peticiones:
        assert r.status_code == 403 and _codigo(r) == "SIN_PERMISO"


def test_sin_token_es_401(client):
    assert client.get("/usuarios").status_code == 401


# ---------- listar (M01-E06) ----------

def test_listar_paginado_ordenado_y_filtrado(client, usuarios, admin):
    r = client.get("/usuarios", headers=admin)
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == {"total", "limite", "desplazamiento", "items"}
    assert cuerpo["limite"] == 50 and cuerpo["desplazamiento"] == 0
    nombres = [u["nombre_completo"] for u in cuerpo["items"]]
    assert nombres == sorted(nombres)
    assert "password_hash" not in r.text

    r = client.get("/usuarios", headers=admin, params={"q": "TEST.RECEP", "rol": "RECEPCION", "activo": True})
    assert [u["rol"] for u in r.json()["items"]] == ["RECEPCION"]
    r = client.get("/usuarios", headers=admin, params={"q": "100%_raro"})
    assert r.json()["total"] == 0

    r = client.get("/usuarios", headers=admin, params={"limite": 1, "desplazamiento": 1})
    assert r.json()["limite"] == 1 and len(r.json()["items"]) == 1 and r.json()["total"] >= 3


@pytest.mark.parametrize("params", [{"limite": 0}, {"limite": 201}, {"desplazamiento": -1}, {"rol": "JEFE"}])
def test_listar_parametros_invalidos_son_422(client, admin, params):
    r = client.get("/usuarios", headers=admin, params=params)
    assert r.status_code == 422 and _codigo(r) == "VALIDACION"


# ---------- crear (M01-E07) ----------

def test_crear_usuario_y_correo_duplicado(client, admin, db):
    r = client.post("/usuarios", headers=admin, json=NUEVO)
    assert r.status_code == 201
    u = r.json()
    assert u["correo_institucional"] == "carlos.rec@predicitas.crp"
    assert u["activo"] is True and u["actualizado_en"] is None and u["creado_en"]
    evento = _eventos(db, "CREATE")[0]
    assert evento.id_entidad == u["id_usuario"] and evento.datos_after["rol"] == "RECEPCION"

    otra = NUEVO | {"correo_institucional": "CARLOS.REC@predicitas.crp", "clave_inicial": "OtraClave99"}
    r = client.post("/usuarios", headers=admin, json=otra)
    assert r.status_code == 409 and _codigo(r) == "CORREO_DUPLICADO"

    # el usuario creado puede entrar
    r = client.post("/auth/login", data={"username": "carlos.rec@predicitas.crp", "password": "ClaveSegura2026"})
    assert r.status_code == 200


@pytest.mark.parametrize("campo,valor", [
    ("correo_institucional", "no-es-correo"),
    ("correo_institucional", "a" * 95 + "@x.crp"),
    ("nombre_completo", " A "),
    ("nombre_completo", "N" * 121),
    ("rol", "JEFE"),
    ("clave_inicial", "corta1"),
    ("clave_inicial", "sinnumeros"),
    ("clave_inicial", "12345678"),
    ("clave_inicial", "A1" * 65),
])
def test_crear_con_datos_invalidos_es_422_con_campo(client, admin, campo, valor):
    r = client.post("/usuarios", headers=admin, json=NUEVO | {campo: valor})
    assert r.status_code == 422 and campo in r.json()["error"]["campos"]


def test_crear_quita_espacios_al_borde_del_nombre(client, admin):
    r = client.post("/usuarios", headers=admin, json=NUEVO | {"nombre_completo": "  Ana Pérez  "})
    assert r.status_code == 201 and r.json()["nombre_completo"] == "Ana Pérez"


# ---------- obtener (M01-E08) ----------

def test_obtener_usuario_y_404(client, usuarios, admin):
    u = usuarios["RECEPCION"]
    r = client.get(f"/usuarios/{u.id_usuario}", headers=admin)
    assert r.status_code == 200 and r.json()["correo_institucional"] == u.correo_institucional
    r = client.get("/usuarios/999999999", headers=admin)
    assert r.status_code == 404 and _codigo(r) == "NO_ENCONTRADO"


# ---------- editar (M01-E09) ----------

def test_editar_nombre_no_invalida_sesion_y_audita(client, usuarios, admin, db):
    u = usuarios["RECEPCION"]
    h_rec = cabecera(client, u)
    r = client.patch(f"/usuarios/{u.id_usuario}", headers=admin, json={"nombre_completo": "Juan Perez"})
    assert r.status_code == 200 and r.json()["nombre_completo"] == "Juan Perez"
    assert r.json()["actualizado_en"] is None
    evento = _eventos(db, "UPDATE")[0]
    assert evento.datos_before["nombre_completo"] == "Test RECEPCION"
    assert evento.datos_after["nombre_completo"] == "Juan Perez"
    assert client.get("/auth/me", headers=h_rec).status_code == 200


def test_editar_rol_invalida_las_sesiones_del_usuario(client, usuarios, admin, reloj):
    u = usuarios["RECEPCION"]
    h_rec = cabecera(client, u)
    reloj.avanzar(seconds=1)
    r = client.patch(f"/usuarios/{u.id_usuario}", headers=admin, json={"rol": "TECNICO_IA"})
    assert r.status_code == 200 and r.json()["rol"] == "TECNICO_IA" and r.json()["actualizado_en"]
    r = client.get("/auth/me", headers=h_rec)
    assert r.status_code == 401 and _codigo(r) == "SESION_INVALIDA"


def test_editar_sin_cambios_no_audita(client, usuarios, admin, db):
    u = usuarios["RECEPCION"]
    r = client.patch(f"/usuarios/{u.id_usuario}", headers=admin, json={"rol": "RECEPCION"})
    assert r.status_code == 200 and _eventos(db, "UPDATE") == []


def test_no_puede_cambiar_su_propio_rol(client, usuarios, admin):
    yo = usuarios["ADMINISTRADOR"]
    r = client.patch(f"/usuarios/{yo.id_usuario}", headers=admin, json={"rol": "RECEPCION"})
    assert r.status_code == 409 and _codigo(r) == "AUTOMODIFICACION_ROL"


def test_editar_404_y_422(client, admin, usuarios):
    assert _codigo(client.patch("/usuarios/999999999", headers=admin, json={"rol": "RECEPCION"})) == "NO_ENCONTRADO"
    r = client.patch(f"/usuarios/{usuarios['RECEPCION'].id_usuario}", headers=admin, json={"activo": False})
    assert r.status_code == 422


def test_quitar_rol_a_otro_administrador_si_queda_uno(client, usuarios, admin, db):
    otro = Usuario(nombre_completo="Otro Admin", correo_institucional="otro.admin@predicitas.crp",
                   password_hash="x", rol="ADMINISTRADOR")
    db.add(otro)
    db.flush()
    r = client.patch(f"/usuarios/{otro.id_usuario}", headers=admin, json={"rol": "RECEPCION"})
    assert r.status_code == 200


# ---------- estado (M01-E10) ----------

def test_desactivar_invalida_sesion_y_bloquea_login_y_reactivar(client, usuarios, admin, db, reloj):
    u = usuarios["RECEPCION"]
    h_rec = cabecera(client, u)
    reloj.avanzar(seconds=1)
    r = client.post(f"/usuarios/{u.id_usuario}/estado", headers=admin, json={"activo": False})
    assert r.status_code == 200 and r.json()["activo"] is False and r.json()["actualizado_en"]
    assert _codigo(client.get("/auth/me", headers=h_rec)) == "SESION_INVALIDA"
    r = client.post("/auth/login", data={"username": u.correo_institucional, "password": CLAVE})
    assert r.status_code == 401 and r.json()["error"]["mensaje"] == "Credenciales inválidas"
    ev = _eventos(db, "DESACTIVAR")[0]
    assert ev.datos_before["activo"] is True and ev.datos_after["activo"] is False

    reloj.avanzar(seconds=1)
    r = client.post(f"/usuarios/{u.id_usuario}/estado", headers=admin, json={"activo": True})
    assert r.status_code == 200 and r.json()["activo"] is True
    assert len(_eventos(db, "ACTIVAR")) == 1
    # repetir el mismo estado no audita de nuevo
    client.post(f"/usuarios/{u.id_usuario}/estado", headers=admin, json={"activo": True})
    assert len(_eventos(db, "ACTIVAR")) == 1


def test_no_puede_desactivarse_a_si_mismo(client, usuarios, admin):
    yo = usuarios["ADMINISTRADOR"]
    r = client.post(f"/usuarios/{yo.id_usuario}/estado", headers=admin, json={"activo": False})
    assert r.status_code == 409 and _codigo(r) == "AUTODESACTIVACION"


def test_estado_404_y_422(client, admin, usuarios):
    assert client.post("/usuarios/999999999/estado", headers=admin, json={"activo": False}).status_code == 404
    r = client.post(f"/usuarios/{usuarios['RECEPCION'].id_usuario}/estado", headers=admin, json={})
    assert r.status_code == 422 and "activo" in r.json()["error"]["campos"]


def test_ultimo_administrador_no_se_desactiva_ni_pierde_el_rol(db, usuarios, reloj):
    # Por la API es inalcanzable (quien actúa ya es otro ADMINISTRADOR activo), pero el servicio
    # lo protege igual (p. ej. ante operaciones simultáneas). Se deja un único admin activo.
    unico = usuarios["ADMINISTRADOR"]
    db.execute(update(Usuario).where(Usuario.rol == "ADMINISTRADOR", Usuario.id_usuario != unico.id_usuario)
               .values(activo=False))
    actor = usuarios["RECEPCION"]  # el servicio no repite el chequeo de permisos del router
    with pytest.raises(Conflicto) as exc:
        service.cambiar_estado(db, unico.id_usuario, EstadoIn(activo=False), actor, "127.0.0.1")
    assert exc.value.codigo == "ULTIMO_ADMINISTRADOR"
    with pytest.raises(Conflicto) as exc:
        service.editar(db, unico.id_usuario, UsuarioEditarIn(rol="RECEPCION"), actor, "127.0.0.1")
    assert exc.value.codigo == "ULTIMO_ADMINISTRADOR"


# ---------- restablecer acceso (M01-E11) ----------

def test_restablecer_acceso(client, usuarios, admin, db, reloj):
    u = usuarios["TECNICO_IA"]
    h_tec = cabecera(client, u)
    reloj.avanzar(seconds=1)
    r = client.post(f"/usuarios/{u.id_usuario}/restablecer-acceso", headers=admin)
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == {"id_usuario", "clave_temporal"} and cuerpo["id_usuario"] == u.id_usuario
    clave = cuerpo["clave_temporal"]
    assert len(clave) == 12 and any(c.isalpha() for c in clave) and any(c.isdigit() for c in clave)
    assert _codigo(client.get("/auth/me", headers=h_tec)) == "SESION_INVALIDA"
    reloj.avanzar(seconds=1)
    assert client.post("/auth/login", data={"username": u.correo_institucional, "password": clave}).status_code == 200
    assert client.post("/auth/login", data={"username": u.correo_institucional, "password": CLAVE}).status_code == 401
    evento = _eventos(db, "RESET_CLAVE")[0]
    assert clave not in json.dumps([evento.datos_before, evento.datos_after])
    assert client.post("/usuarios/999999999/restablecer-acceso", headers=admin).status_code == 404


def test_clave_temporal_siempre_cumple_la_politica():
    for _ in range(200):
        clave = service.generar_clave_temporal()
        assert len(clave) == 12 and any(c.isalpha() for c in clave) and any(c.isdigit() for c in clave)


# ---------- privacidad de la auditoría (RF-090, RNF-002) ----------

def test_ninguna_auditoria_ni_respuesta_contiene_claves_hashes_ni_tokens(client, usuarios, admin, db, reloj):
    respuestas = []
    r = client.post("/usuarios", headers=admin, json=NUEVO)
    respuestas.append(r.text)
    nuevo_id = r.json()["id_usuario"]
    respuestas.append(client.patch(f"/usuarios/{nuevo_id}", headers=admin, json={"rol": "TECNICO_IA"}).text)
    respuestas.append(client.post(f"/usuarios/{nuevo_id}/estado", headers=admin, json={"activo": False}).text)
    respuestas.append(client.post(f"/usuarios/{nuevo_id}/estado", headers=admin, json={"activo": True}).text)
    temporal = client.post(f"/usuarios/{nuevo_id}/restablecer-acceso", headers=admin).json()["clave_temporal"]
    respuestas.append(client.get("/usuarios", headers=admin).text)
    respuestas.append(client.get("/auth/me", headers=admin).text)
    h_tec = cabecera(client, usuarios["TECNICO_IA"])
    r = client.post("/auth/cambiar-clave", headers=h_tec, json={"clave_actual": CLAVE, "clave_nueva": "Nueva12345"})
    token = r.json()["access_token"]
    client.post("/auth/login", data={"username": usuarios["RECEPCION"].correo_institucional, "password": "MalaClave1"})
    reloj.avanzar(seconds=1)
    client.post("/auth/logout", headers=admin)

    hashes = [u.password_hash for u in db.scalars(select(Usuario))]
    textos_auditoria = [json.dumps([e.datos_before, e.datos_after], default=str)
                        for e in db.scalars(select(AuditoriaEvento))]
    secretos = ["ClaveSegura2026", temporal, CLAVE, "Nueva12345", "MalaClave1", token, *hashes]
    for texto in textos_auditoria + respuestas:
        assert "password" not in texto
        for secreto in secretos:
            assert secreto not in texto
