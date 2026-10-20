"""Bloqueo por intentos fallidos (F-01, D-009, RNF-005 · CP-M01-02)."""
from sqlalchemy import select

from app.modules.auditoria.models import AuditoriaEvento
from tests.conftest import CLAVE


def _login(client, correo, clave):
    return client.post("/auth/login", data={"username": correo, "password": clave})


def _resultados(db, usuario):
    eventos = db.scalars(select(AuditoriaEvento).where(
        AuditoriaEvento.accion == "LOGIN", AuditoriaEvento.id_usuario == usuario.id_usuario
    ).order_by(AuditoriaEvento.id_log))
    return [e.datos_after["resultado"] for e in eventos]


def test_sexto_intento_da_429_aunque_la_clave_sea_buena_y_se_libera(client, usuarios, db, reloj):
    u = usuarios["RECEPCION"]
    for _ in range(5):
        r = _login(client, u.correo_institucional, "ClaveMala999")
        assert r.status_code == 401 and r.json()["error"]["mensaje"] == "Credenciales inválidas"
        reloj.avanzar(seconds=30)

    r = _login(client, u.correo_institucional, CLAVE)
    assert r.status_code == 429
    error = r.json()["error"]
    assert error["codigo"] == "DEMASIADOS_INTENTOS"
    # último fallo hace 30 s → faltan 14 min 30 s → se redondea a 15
    assert error["mensaje"] == "Demasiados intentos fallidos. Vuelve a intentarlo en 15 minutos."
    assert "access_token" not in r.text

    # Con la clave mala durante el bloqueo, la respuesta es la misma: no revela nada.
    r_mala = _login(client, u.correo_institucional, "ClaveMala999")
    assert r_mala.status_code == 429 and r_mala.json() == r.json()

    reloj.avanzar(minutes=10)
    assert "en 5 minutos" in _login(client, u.correo_institucional, CLAVE).json()["error"]["mensaje"]

    reloj.avanzar(minutes=5)  # pasan 15 min desde el último fallo
    assert _login(client, u.correo_institucional, CLAVE).status_code == 200
    assert _resultados(db, u) == ["FALLIDO"] * 5 + ["BLOQUEADO"] * 3 + ["EXITOSO"]


def test_cuatro_fallos_no_bloquean(client, usuarios, reloj):
    u = usuarios["TECNICO_IA"]
    for _ in range(4):
        _login(client, u.correo_institucional, "ClaveMala999")
    assert _login(client, u.correo_institucional, CLAVE).status_code == 200


def test_fallos_fuera_de_la_ventana_no_se_suman(client, usuarios, reloj):
    u = usuarios["TECNICO_IA"]
    for _ in range(5):
        _login(client, u.correo_institucional, "ClaveMala999")
        reloj.avanzar(minutes=4)  # 5 fallos repartidos en 16 minutos (> ventana de 15)
    assert _login(client, u.correo_institucional, CLAVE).status_code == 200


def test_un_login_exitoso_reinicia_el_conteo(client, usuarios, reloj):
    u = usuarios["TECNICO_IA"]
    for _ in range(4):
        _login(client, u.correo_institucional, "ClaveMala999")
    assert _login(client, u.correo_institucional, CLAVE).status_code == 200
    reloj.avanzar(seconds=1)
    for _ in range(4):
        _login(client, u.correo_institucional, "ClaveMala999")
    assert _login(client, u.correo_institucional, CLAVE).status_code == 200


def test_correo_inexistente_responde_401_generico(client, db):
    r = _login(client, "nadie@predicitas.crp", "ClaveMala999")
    assert r.status_code == 401
    assert r.json()["error"] == {"codigo": "NO_AUTENTICADO", "mensaje": "Credenciales inválidas", "campos": {}}


def test_login_sin_campos_es_422(client):
    r = client.post("/auth/login", data={})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "VALIDACION"
