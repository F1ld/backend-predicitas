from sqlalchemy import select

from app.modules.auditoria.models import AuditoriaEvento
from tests.conftest import CLAVE, cabecera


def test_login_correcto_y_me(client, usuarios):
    h = cabecera(client, usuarios["RECEPCION"])
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 200
    assert r.json()["rol"] == "RECEPCION"
    assert "password_hash" not in r.json()


def test_login_con_clave_incorrecta_responde_401_y_audita(client, usuarios, db):
    r = client.post("/auth/login", data={"username": usuarios["RECEPCION"].correo_institucional, "password": "mala"})
    assert r.status_code == 401
    assert r.json()["error"]["codigo"] == "NO_AUTENTICADO"
    assert r.headers["WWW-Authenticate"] == "Bearer"
    eventos = db.scalars(select(AuditoriaEvento).where(AuditoriaEvento.accion == "LOGIN")).all()
    assert any(e.datos_after.get("resultado") == "FALLIDO" for e in eventos)


def test_endpoint_protegido_sin_token_responde_401(client):
    r = client.get("/citas")
    assert r.status_code == 401
    assert r.json() == {"error": {"codigo": "NO_AUTENTICADO", "mensaje": "Debe iniciar sesión", "campos": {}}}
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_token_invalido_responde_401_sesion_invalida(client):
    r = client.get("/citas", headers={"Authorization": "Bearer no-es-un-jwt"})
    assert r.status_code == 401
    assert r.json()["error"]["codigo"] == "SESION_INVALIDA"  # F-02, D-010


def test_usuario_inactivo_no_puede_entrar(client, usuarios, db):
    usuarios["RECEPCION"].activo = False
    db.flush()
    r = client.post("/auth/login", data={"username": usuarios["RECEPCION"].correo_institucional, "password": CLAVE})
    assert r.status_code == 401