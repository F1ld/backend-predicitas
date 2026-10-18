"""app.core.config: variables de contratos/comun.json → variables_entorno_backend."""
from app.core.config import Settings

URL_APP = "postgresql+psycopg://app@db/x"


def test_valores_por_defecto_del_contrato(monkeypatch):
    for nombre in ("DATABASE_URL_MIGRACIONES", "CORS_ORIGENES", "IA_URL", "IA_CORTE_MEDIO",
                   "LOGIN_MAX_INTENTOS", "INTERVENCION_MODO_SOMBRA", "ACCESS_TOKEN_EXPIRE_MINUTES"):
        monkeypatch.delenv(nombre, raising=False)
    s = Settings(_env_file=None, database_url=URL_APP, secret_key="k")
    assert s.access_token_expire_minutes == 30 and s.login_max_intentos == 5
    assert s.ia_url == "http://ia:8100" and s.ia_corte_medio == 0.30
    assert s.intervencion_modo_sombra is False
    assert s.lista_cors_origenes == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert s.url_migraciones == URL_APP


def test_migraciones_usan_su_propia_url_si_existe(monkeypatch):
    monkeypatch.setenv("CORS_ORIGENES", "http://a.test, http://b.test,")
    s = Settings(_env_file=None, database_url=URL_APP,
                 database_url_migraciones="postgresql+psycopg://owner@db/x", secret_key="k")
    assert s.url_migraciones == "postgresql+psycopg://owner@db/x"
    assert s.lista_cors_origenes == ["http://a.test", "http://b.test"]
