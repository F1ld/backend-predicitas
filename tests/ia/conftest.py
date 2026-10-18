"""Utilidades de las pruebas de M09: servicio de inferencia falso (httpx.MockTransport), reloj fijo
y el simulador real levantado en el puerto de la tarjeta (8191) para medir RNF-012."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.main import app
from app.modules.ia.cliente import ClienteIA, get_cliente
from app.modules.ia.router import reloj_ia
from tests.citas.conftest import HOY

VERSION = "SIM_TEST_v1"
CARPETA_SIMULADOR = Path(__file__).resolve().parents[3] / "ia-simulador"
PUERTO_SIMULADOR = 8191


class ServicioFalso:
    """Cumple contratos/servicio-inferencia.json y deja configurar fallos."""

    def __init__(self):
        self.habilitado = True
        self.probabilidad = 0.512
        self.umbral = 0.45
        self.version = VERSION
        self.version_prediccion = None   # para simular que cambia el modelo entre llamadas
        self.fallar_modelo = None        # None | "conexion" | "timeout" | 500 | "basura"
        self.fallar_prediccion = None
        self.fallar_ids: set[int] = set()
        self.peticiones: list[dict] = []
        self.cabeceras: list[httpx.Headers] = []

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.cabeceras.append(peticion.headers)
        if peticion.url.path == "/v1/modelo":
            return self._responder(peticion, self.fallar_modelo, {
                "version_modelo": self.version, "umbral": self.umbral, "habilitado_piloto": self.habilitado,
                "resultado_simulado": True, "version_dataset": "SINT_v0", "fecha_aprobacion": None,
                "variables": ["especialidad"]})
        cuerpo = json.loads(peticion.content)
        self.peticiones.append(cuerpo)
        fallo = "conexion" if cuerpo["id_cita"] in self.fallar_ids else self.fallar_prediccion
        return self._responder(peticion, fallo, {
            "id_cita": cuerpo["id_cita"], "probabilidad_no_show": self.probabilidad,
            "version_modelo": self.version_prediccion or self.version, "umbral": self.umbral,
            "explicabilidad_resumen": "Antelación alta", "resultado_simulado": True})

    @staticmethod
    def _responder(peticion, fallo, datos):
        if fallo == "conexion":
            raise httpx.ConnectError("conexión rechazada", request=peticion)
        if fallo == "timeout":
            raise httpx.ReadTimeout("tiempo agotado", request=peticion)
        if isinstance(fallo, int):
            return httpx.Response(fallo, json={"error": "x"})
        if fallo == "basura":
            return httpx.Response(200, text="<html>no es json</html>")
        if fallo == "incompleto":
            return httpx.Response(200, json={"version_modelo": "x"})
        return httpx.Response(200, json=datos)


@pytest.fixture
def servicio():
    return ServicioFalso()


@pytest.fixture
def api_ia(client, servicio):
    """Cliente de la API con el servicio falso y el reloj fijo en HOY (24/10/2026 08:00 Lima).
    El fixture `client` limpia los overrides al terminar."""
    app.dependency_overrides[get_cliente] = lambda: ClienteIA(transporte=httpx.MockTransport(servicio))
    app.dependency_overrides[reloj_ia] = lambda: HOY
    return client


def _puerto_libre(puerto: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", puerto)) != 0


@pytest.fixture(scope="session")
def simulador_real():
    """Levanta ia-simulador/ con uvicorn en 127.0.0.1:8191. Se omite si la carpeta no está
    (p. ej. dentro de la imagen del backend, que solo copia backend/)."""
    if not (CARPETA_SIMULADOR / "main.py").is_file():
        pytest.skip("ia-simulador/ no está disponible en este entorno")
    if not _puerto_libre(PUERTO_SIMULADOR):
        pytest.skip(f"el puerto {PUERTO_SIMULADOR} está ocupado")
    entorno = {**os.environ, "SIMULADOR_LATENCIA_MS": "0", "SIMULADOR_FALLAR": "false"}
    entorno.pop("IA_API_KEY", None)
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(CARPETA_SIMULADOR),
         "--host", "127.0.0.1", "--port", str(PUERTO_SIMULADOR), "--log-level", "warning"],
        env=entorno)
    url = f"http://127.0.0.1:{PUERTO_SIMULADOR}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{url}/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            pytest.fail("el simulador no arrancó")
        yield url
    finally:
        proceso.terminate()
        proceso.wait(timeout=10)
