"""Cliente del servicio de inferencia con httpx.MockTransport (contratos/modulo-09.json →
cliente_del_servicio; RF-103, RNF-015)."""
import httpx
import pytest

from app.core.config import get_settings
from app.core.errores import MotorIANoDisponible
from app.modules.ia.cliente import ClienteIA, Variables

VARIABLES = Variables(especialidad="CARDIOLOGIA", tipo_paciente="NUEVO", antelacion_dias=10,
                      canal_origen="WEB", franja_horaria="MANANA", dia_semana="LUNES",
                      inasistencias_previas=0, reprogramaciones_prev=0, asistencias_previas=0,
                      confirmada=False)


def _cliente(servicio):
    return ClienteIA(transporte=httpx.MockTransport(servicio))


def test_obtiene_modelo_y_prediccion(servicio):
    c = _cliente(servicio)
    m = c.obtener_modelo()
    assert m.version_modelo == "SIM_TEST_v1" and m.habilitado_piloto and c.ultima_latencia_ms is not None
    p = c.predecir(7, VARIABLES)
    assert p.id_cita == 7 and p.probabilidad_no_show == 0.512
    assert servicio.peticiones[0] == {"id_cita": 7, "variables": VARIABLES.model_dump()}


@pytest.mark.parametrize("fallo", ["conexion", "timeout", 500, 503, 404, "basura", "incompleto"])
def test_cualquier_fallo_del_modelo_es_motor_no_disponible(servicio, fallo):
    servicio.fallar_modelo = fallo
    with pytest.raises(MotorIANoDisponible) as exc:
        _cliente(servicio).obtener_modelo()
    assert exc.value.codigo == "MOTOR_IA_NO_DISPONIBLE" and exc.value.codigo_http == 503


@pytest.mark.parametrize("fallo", ["conexion", "timeout", 500, "basura", "incompleto"])
def test_cualquier_fallo_de_prediccion_es_motor_no_disponible(servicio, fallo):
    servicio.fallar_prediccion = fallo
    with pytest.raises(MotorIANoDisponible):
        _cliente(servicio).predecir(1, VARIABLES)


def test_eco_de_id_cita_distinto_es_fuera_de_contrato():
    def handler(peticion):
        return httpx.Response(200, json={"id_cita": 999, "probabilidad_no_show": 0.1, "version_modelo": "v",
                                         "umbral": 0.45, "explicabilidad_resumen": None,
                                         "resultado_simulado": True})
    with pytest.raises(MotorIANoDisponible):
        ClienteIA(transporte=httpx.MockTransport(handler)).predecir(1, VARIABLES)


def test_probabilidad_fuera_de_rango_es_fuera_de_contrato():
    def handler(peticion):
        return httpx.Response(200, json={"id_cita": 1, "probabilidad_no_show": 1.7, "version_modelo": "v",
                                         "umbral": 0.45, "explicabilidad_resumen": None,
                                         "resultado_simulado": True})
    with pytest.raises(MotorIANoDisponible):
        ClienteIA(transporte=httpx.MockTransport(handler)).predecir(1, VARIABLES)


def test_envia_x_api_key_si_esta_configurada(servicio, monkeypatch):
    monkeypatch.setattr(get_settings(), "ia_api_key", "clave-interna")
    _cliente(servicio).obtener_modelo()
    assert servicio.cabeceras[-1]["X-API-Key"] == "clave-interna"
    monkeypatch.setattr(get_settings(), "ia_api_key", None)
    _cliente(servicio).obtener_modelo()
    assert "X-API-Key" not in servicio.cabeceras[-1]


def test_usa_ia_url_y_timeout_de_la_configuracion():
    s = get_settings()
    c = ClienteIA()
    assert str(c._http.base_url).rstrip("/") == s.ia_url.rstrip("/")
    assert c._http.timeout.read == s.ia_timeout_segundos
    c.close()
