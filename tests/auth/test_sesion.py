"""Token, renovación, cierre e invalidación de sesión (F-02, D-010, RNF-004 · CP-M01-01, -03, -10)."""
import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.modules.auditoria.models import AuditoriaEvento
from app.modules.auth import tokens
from tests.conftest import CLAVE, cabecera


def _codigo(r):
    return r.json()["error"]["codigo"]


def test_token_lleva_sub_iat_con_milisegundos_y_exp(client, usuarios):
    u = usuarios["RECEPCION"]
    r = client.post("/auth/login", data={"username": u.correo_institucional, "password": CLAVE})
    cuerpo = r.json()
    assert cuerpo["token_type"] == "bearer" and cuerpo["expires_in"] == 1800
    carga = jwt.decode(cuerpo["access_token"], options={"verify_signature": False})
    assert carga["sub"] == str(u.id_usuario)
    assert isinstance(carga["iat"], float) and round(carga["iat"], 3) == carga["iat"]
    assert carga["exp"] == carga["iat"] + 1800


def test_me_devuelve_usuario_out_completo(client, usuarios):
    r = client.get("/auth/me", headers=cabecera(client, usuarios["ADMINISTRADOR"]))
    assert set(r.json()) == {"id_usuario", "nombre_completo", "correo_institucional", "rol", "activo",
                             "creado_en", "actualizado_en"}


def test_logout_invalida_el_token(client, usuarios, db, reloj):
    h = cabecera(client, usuarios["RECEPCION"])
    reloj.avanzar(seconds=1)
    assert client.post("/auth/logout", headers=h).status_code == 204
    assert db.scalar(select(AuditoriaEvento).where(AuditoriaEvento.accion == "LOGOUT")) is not None
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 401 and _codigo(r) == "SESION_INVALIDA"
    assert r.headers["WWW-Authenticate"] == "Bearer"
    # Un login posterior vuelve a funcionar.
    reloj.avanzar(seconds=1)
    assert client.get("/auth/me", headers=cabecera(client, usuarios["RECEPCION"])).status_code == 200


def test_logout_de_otro_usuario_no_afecta(client, usuarios, reloj):
    h_rec = cabecera(client, usuarios["RECEPCION"])
    h_adm = cabecera(client, usuarios["ADMINISTRADOR"])
    reloj.avanzar(seconds=1)
    client.post("/auth/logout", headers=h_adm)
    assert client.get("/auth/me", headers=h_rec).status_code == 200


def test_sin_token_es_no_autenticado_y_token_invalido_es_sesion_invalida(client):
    r = client.get("/auth/me")
    assert r.status_code == 401 and _codigo(r) == "NO_AUTENTICADO"
    r = client.get("/auth/me", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401 and _codigo(r) == "SESION_INVALIDA"


def test_token_vencido_es_sesion_invalida(client, usuarios, reloj):
    h = cabecera(client, usuarios["RECEPCION"])
    reloj.avanzar(minutes=31)
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 401 and _codigo(r) == "SESION_INVALIDA"


def test_token_sin_iat_o_de_usuario_inexistente_es_sesion_invalida(client, usuarios):
    s = get_settings()
    sin_iat = jwt.encode({"sub": str(usuarios["RECEPCION"].id_usuario), "exp": 9999999999},
                         s.secret_key, algorithm=s.jwt_algorithm)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {sin_iat}"})
    assert _codigo(r) == "SESION_INVALIDA"
    from app.modules.auth import reloj as reloj_mod
    fantasma, _ = tokens.crear_token(999999999, reloj_mod.ahora())
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {fantasma}"})
    assert r.status_code == 401 and _codigo(r) == "SESION_INVALIDA"


def test_renovar_entrega_token_nuevo_y_el_anterior_sigue_valiendo(client, usuarios, db, reloj):
    h = cabecera(client, usuarios["RECEPCION"])
    eventos_antes = db.scalar(select(AuditoriaEvento.id_log).order_by(AuditoriaEvento.id_log.desc()).limit(1))
    reloj.avanzar(minutes=20)
    r = client.post("/auth/renovar", headers=h)
    assert r.status_code == 200 and r.json()["expires_in"] == 1800
    nuevo = {"Authorization": f"Bearer {r.json()['access_token']}"}
    reloj.avanzar(minutes=15)  # el viejo venció (35 min), el nuevo no (15 min)
    assert client.get("/auth/me", headers=h).status_code == 401
    assert client.get("/auth/me", headers=nuevo).status_code == 200
    # renovar no audita (evita ruido)
    ultimo = db.scalar(select(AuditoriaEvento.id_log).order_by(AuditoriaEvento.id_log.desc()).limit(1))
    assert ultimo == eventos_antes


def test_renovar_con_token_invalidado_es_sesion_invalida(client, usuarios, reloj):
    h = cabecera(client, usuarios["RECEPCION"])
    reloj.avanzar(seconds=1)
    client.post("/auth/logout", headers=h)
    r = client.post("/auth/renovar", headers=h)
    assert r.status_code == 401 and _codigo(r) == "SESION_INVALIDA"


def test_cambiar_clave(client, usuarios, db):
    u = usuarios["TECNICO_IA"]
    h = cabecera(client, u)

    r = client.post("/auth/cambiar-clave", headers=h, json={"clave_actual": "Otra12345", "clave_nueva": "Nueva12345"})
    assert r.status_code == 409 and _codigo(r) == "CLAVE_ACTUAL_INCORRECTA"

    r = client.post("/auth/cambiar-clave", headers=h, json={"clave_actual": CLAVE, "clave_nueva": CLAVE})
    assert r.status_code == 422 and "clave_nueva" in r.json()["error"]["campos"]

    r = client.post("/auth/cambiar-clave", headers=h, json={"clave_actual": CLAVE, "clave_nueva": "sololetras"})
    assert r.status_code == 422 and "clave_nueva" in r.json()["error"]["campos"]

    r = client.post("/auth/cambiar-clave", headers=h, json={"clave_actual": CLAVE, "clave_nueva": "Nueva12345"})
    assert r.status_code == 200
    nuevo = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert u.actualizado_en is not None
    # El token anterior deja de valer; el nuevo vale y la clave nueva entra.
    assert _codigo(client.get("/auth/me", headers=h)) == "SESION_INVALIDA"
    assert client.get("/auth/me", headers=nuevo).status_code == 200
    assert client.post("/auth/renovar", headers=nuevo).status_code == 200
    r = client.post("/auth/login", data={"username": u.correo_institucional, "password": "Nueva12345"})
    assert r.status_code == 200
    evento = db.scalar(select(AuditoriaEvento).where(AuditoriaEvento.accion == "CAMBIO_CLAVE"))
    assert evento.modulo == "USUARIOS" and evento.id_entidad == u.id_usuario


def test_cambiar_clave_sin_token_es_401(client):
    r = client.post("/auth/cambiar-clave", json={"clave_actual": "a", "clave_nueva": "b"})
    assert r.status_code == 401
