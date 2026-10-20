"""Registro automático de routers desde app/modules/*/router.py (contratos/comun.json → ranuras_backend)."""
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.ranuras import registrar_routers
from app.main import app

ROUTER_X = (
    "from fastapi import APIRouter\n"
    "router = APIRouter(prefix='/x')\n"
    "@router.get('')\n"
    "def hola():\n"
    "    return {'modulo': 'x'}\n"
)


def test_la_app_registra_los_modulos_existentes():
    rutas = set(app.openapi()["paths"])
    assert {"/auth/login", "/auth/me", "/citas", "/health"} <= rutas


def test_un_router_nuevo_se_registra_sin_tocar_main(tmp_path, monkeypatch):
    # Paquete falso con la misma forma que app/modules/: x/router.py y b/router.py se registran;
    # una carpeta sin router.py, un router.py sin variable `router` y una carpeta _oculta no.
    raiz = tmp_path / "modulos_falsos"
    archivos = {
        "x": ROUTER_X,
        "b": "from fastapi import APIRouter\nrouter = APIRouter(prefix='/b')\n",
        "sin_variable": "otra_cosa = 1\n",
        "_oculto": "from fastapi import APIRouter\nrouter = APIRouter(prefix='/oculto')\n",
    }
    for nombre, codigo in archivos.items():
        (raiz / nombre).mkdir(parents=True)
        (raiz / nombre / "__init__.py").write_text("")
        (raiz / nombre / "router.py").write_text(codigo)
    (raiz / "sin_router").mkdir()
    (raiz / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))

    nueva = FastAPI()
    try:
        assert registrar_routers(nueva, "modulos_falsos") == ["b", "x"]  # orden alfabético
        assert TestClient(nueva).get("/x").json() == {"modulo": "x"}
    finally:
        for nombre in [m for m in sys.modules if m.startswith("modulos_falsos")]:
            del sys.modules[nombre]
