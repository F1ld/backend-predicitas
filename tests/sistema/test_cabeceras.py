"""Cabeceras de seguridad en las respuestas de la API; Swagger sigue funcionando."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_respuestas_de_la_api_llevan_cabeceras_de_seguridad():
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_los_errores_tambien_llevan_cabeceras():
    r = client.get("/citas")
    assert r.status_code == 401
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in r.headers


def test_docs_y_openapi_siguen_funcionando_sin_csp_restrictiva():
    docs = client.get("/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    assert "Content-Security-Policy" not in docs.headers
    esquema = client.get("/openapi.json")
    assert esquema.status_code == 200 and "/health" in esquema.json()["paths"]
    assert "Content-Security-Policy" not in esquema.headers


def test_cors_permite_el_origen_del_frontend():
    r = client.options("/health", headers={"Origin": "http://localhost:5173",
                                           "Access-Control-Request-Method": "GET"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
