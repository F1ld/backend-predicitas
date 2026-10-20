"""Formato de error único {"error": {"codigo", "mensaje", "campos"}} (D-017, contratos/comun.json)."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core import manejadores
from app.core.errores import ArchivoInvalido, Conflicto, ErrorDeNegocio, TransicionInvalida, Validacion
from app.main import app


class Entrada(BaseModel):
    sede: str
    edad: int = Field(ge=0)
    filas: list[dict[str, int]] = []


def _app_de_prueba() -> FastAPI:
    prueba = FastAPI()
    manejadores.instalar(prueba)

    @prueba.get("/conflicto")
    def conflicto():
        raise Conflicto("El cupo ya fue asignado", codigo="CUPO_NO_DISPONIBLE")

    @prueba.get("/transicion")
    def transicion():
        raise TransicionInvalida("La cita ya fue atendida")

    @prueba.get("/http")
    def http():
        raise HTTPException(status_code=400, detail="Bad thing")

    @prueba.get("/http-raro")
    def http_raro():
        raise HTTPException(status_code=418)

    @prueba.post("/validar")
    def validar(entrada: Entrada):
        return entrada

    @prueba.get("/falla")
    def falla():
        raise RuntimeError("detalle interno secreto")

    return prueba


@pytest.fixture
def cliente():
    return TestClient(_app_de_prueba(), raise_server_exceptions=False)


def _forma_valida(cuerpo: dict) -> dict:
    assert set(cuerpo) == {"error"}
    assert set(cuerpo["error"]) == {"codigo", "mensaje", "campos"}
    return cuerpo["error"]


def test_error_de_negocio_409_con_codigo_propio(cliente):
    r = cliente.get("/conflicto")
    assert r.status_code == 409
    assert _forma_valida(r.json()) == {"codigo": "CUPO_NO_DISPONIBLE",
                                       "mensaje": "El cupo ya fue asignado", "campos": {}}


def test_cada_excepcion_lleva_su_codigo_por_defecto(cliente):
    assert cliente.get("/transicion").json()["error"]["codigo"] == "TRANSICION_INVALIDA"
    assert ArchivoInvalido("x").codigo == "ARCHIVO_INVALIDO" and ArchivoInvalido.codigo_http == 422
    assert ErrorDeNegocio("x").codigo == "SOLICITUD_INVALIDA"
    assert Validacion("x", campos={"a": "b"}).campos == {"a": "b"}


def test_http_exception_se_traduce_al_formato_unico(cliente):
    r = cliente.get("/http")
    assert r.status_code == 400
    assert _forma_valida(r.json())["codigo"] == "SOLICITUD_INVALIDA"
    assert "Bad thing" not in r.text
    assert cliente.get("/http-raro").json()["error"]["codigo"] == "SOLICITUD_INVALIDA"


def test_validacion_422_con_campos_en_notacion_de_puntos(cliente):
    r = cliente.post("/validar", json={"edad": -1, "filas": [{"n": 1}, {"n": 1}, {"n": 1}, {"n": "x"}]})
    assert r.status_code == 422
    error = _forma_valida(r.json())
    assert error["codigo"] == "VALIDACION"
    assert error["campos"] == {"sede": "Campo obligatorio", "edad": "Valor demasiado pequeño",
                               "filas.3.n": "Debe ser un número entero"}


def test_cuerpo_json_invalido_es_422(cliente):
    r = cliente.post("/validar", content="{no json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert _forma_valida(r.json())["codigo"] == "VALIDACION"


def test_excepcion_no_controlada_es_500_sin_traza(cliente):
    r = cliente.get("/falla")
    assert r.status_code == 500
    assert _forma_valida(r.json()) == {"codigo": "ERROR_INTERNO", "mensaje": "Ocurrió un error interno",
                                       "campos": {}}
    assert "secreto" not in r.text and "Traceback" not in r.text


def test_ruta_inexistente_de_la_api_es_404_con_formato_unico():
    r = TestClient(app).get("/no-existe")
    assert r.status_code == 404
    assert _forma_valida(r.json())["codigo"] == "NO_ENCONTRADO"


def test_sin_token_es_401_con_cabecera_bearer():
    r = TestClient(app).get("/auth/me")
    assert r.status_code == 401
    assert _forma_valida(r.json())["codigo"] == "NO_AUTENTICADO"
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_ruta_campo():
    assert manejadores.ruta_campo(("body", "filas", 3, "sede")) == "filas.3.sede"
    assert manejadores.ruta_campo(("query", "limite")) == "limite"
    assert manejadores.ruta_campo(("body",)) == "body"
