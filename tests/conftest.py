import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import engine, get_db
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import Usuario

CLAVE = "ClaveDePrueba123"


@pytest.fixture
def db():
    conexion = engine.connect()
    transaccion = conexion.begin()
    # create_savepoint: los commit() del código bajo prueba no confirman la transacción externa.
    sesion = Session(bind=conexion, join_transaction_mode="create_savepoint",
                     autoflush=False, expire_on_commit=False)
    try:
        yield sesion
    finally:
        sesion.close()
        transaccion.rollback()
        conexion.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def usuarios(db):
    creados = {}
    for rol in ("ADMINISTRADOR", "RECEPCION", "TECNICO_IA"):
        u = Usuario(nombre_completo=f"Test {rol}", correo_institucional=f"test.{rol.lower()}@predicitas.crp",
                    password_hash=hash_password(CLAVE), rol=rol)
        db.add(u)
        creados[rol] = u
    db.flush()
    return creados


def cabecera(client, usuario) -> dict:
    r = client.post("/auth/login", data={"username": usuario.correo_institucional, "password": CLAVE})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}