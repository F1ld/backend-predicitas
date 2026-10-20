"""Manejadores de error y cabeceras de seguridad de la API (D-017).

Todas las respuestas de error tienen la forma {"error": {"codigo", "mensaje", "campos"}}.
`campos` solo trae contenido en 422 VALIDACION; en el resto es un objeto vacío.
Nunca se devuelven trazas ni detalles internos.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errores import ErrorDeNegocio

log = logging.getLogger("predicitas.errores")

# Código y mensaje por estado HTTP (contratos/comun.json → codigos_transversales).
_POR_ESTADO = {
    400: ("SOLICITUD_INVALIDA", "La solicitud no es válida"),
    401: ("NO_AUTENTICADO", "Debe iniciar sesión"),
    403: ("SIN_PERMISO", "No tiene permisos para esta operación"),
    404: ("NO_ENCONTRADO", "El recurso no existe"),
    405: ("SOLICITUD_INVALIDA", "Método no permitido para este recurso"),
    409: ("CONFLICTO", "La operación entra en conflicto con el estado actual"),
    422: ("VALIDACION", "Los datos enviados no son válidos"),
    429: ("DEMASIADOS_INTENTOS", "Demasiados intentos; espere y vuelva a intentarlo"),
    500: ("ERROR_INTERNO", "Ocurrió un error interno"),
    503: ("MOTOR_IA_NO_DISPONIBLE", "El servicio no está disponible"),
}

# Mensajes en español para los tipos de error de validación más comunes de Pydantic.
_MENSAJES_VALIDACION = {
    "missing": "Campo obligatorio",
    "extra_forbidden": "Campo no permitido",
    "string_type": "Debe ser texto",
    "string_too_short": "Texto demasiado corto",
    "string_too_long": "Texto demasiado largo",
    "string_pattern_mismatch": "Formato inválido",
    "int_type": "Debe ser un número entero",
    "int_parsing": "Debe ser un número entero",
    "float_type": "Debe ser un número",
    "float_parsing": "Debe ser un número",
    "bool_type": "Debe ser verdadero o falso",
    "bool_parsing": "Debe ser verdadero o falso",
    "greater_than": "Valor demasiado pequeño",
    "greater_than_equal": "Valor demasiado pequeño",
    "less_than": "Valor demasiado grande",
    "less_than_equal": "Valor demasiado grande",
    "literal_error": "Valor no permitido",
    "enum": "Valor no permitido",
    "datetime_type": "Debe ser una fecha y hora ISO 8601",
    "datetime_parsing": "Debe ser una fecha y hora ISO 8601",
    "datetime_from_date_parsing": "Debe ser una fecha y hora ISO 8601",
    "timezone_aware": "La fecha y hora debe incluir zona horaria",
    "date_type": "Debe ser una fecha YYYY-MM-DD",
    "date_parsing": "Debe ser una fecha YYYY-MM-DD",
    "date_from_datetime_parsing": "Debe ser una fecha YYYY-MM-DD",
    "value_error": "Valor inválido",
    "json_invalid": "JSON inválido",
    "dict_type": "Debe ser un objeto",
    "list_type": "Debe ser una lista",
}

_ORIGENES = {"body", "query", "path", "header", "cookie"}


def cuerpo_error(codigo: str, mensaje: str, campos: dict | None = None) -> dict:
    return {"error": {"codigo": codigo, "mensaje": mensaje, "campos": campos or {}}}


def ruta_campo(loc) -> str:
    """('body', 'filas', 3, 'sede') → 'filas.3.sede'."""
    partes = list(loc)
    if len(partes) > 1 and partes[0] in _ORIGENES:
        partes = partes[1:]
    return ".".join(str(p) for p in partes)


def _cabeceras_401(estado: int, cabeceras: dict | None = None) -> dict | None:
    if estado != 401:
        return cabeceras
    return {**(cabeceras or {}), "WWW-Authenticate": "Bearer"}


async def manejar_error_de_negocio(_: Request, exc: ErrorDeNegocio) -> JSONResponse:
    return JSONResponse(status_code=exc.codigo_http,
                        content=cuerpo_error(exc.codigo, exc.mensaje, exc.campos),
                        headers=_cabeceras_401(exc.codigo_http))


async def manejar_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    # El mensaje sale siempre de la tabla en español: el `detail` de las librerías viene en inglés.
    por_defecto = (("ERROR_INTERNO", "Ocurrió un error interno") if exc.status_code >= 500
                   else ("SOLICITUD_INVALIDA", "La solicitud no es válida"))
    codigo, mensaje = _POR_ESTADO.get(exc.status_code, por_defecto)
    return JSONResponse(status_code=exc.status_code, content=cuerpo_error(codigo, mensaje),
                        headers=_cabeceras_401(exc.status_code, getattr(exc, "headers", None)))


async def manejar_validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
    campos: dict[str, str] = {}
    for error in exc.errors():
        clave = ruta_campo(error.get("loc", ())) or "solicitud"
        campos.setdefault(clave, _MENSAJES_VALIDACION.get(error.get("type", ""), "Valor inválido"))
    return JSONResponse(status_code=422,
                        content=cuerpo_error("VALIDACION", "Los datos enviados no son válidos", campos))


async def manejar_no_controlado(request: Request, exc: Exception) -> JSONResponse:
    # Solo se registra el tipo de excepción y la ruta: nada de datos de la petición.
    log.error("Error no controlado %s en %s %s", type(exc).__name__, request.method, request.url.path)
    return JSONResponse(status_code=500, content=cuerpo_error("ERROR_INTERNO", "Ocurrió un error interno"))


# Cabeceras de seguridad. La CSP restrictiva no se aplica a Swagger, que necesita scripts y estilos.
CABECERAS_SEGURIDAD = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
CSP_API = "default-src 'none'; frame-ancestors 'none'"
RUTAS_DOCUMENTACION = ("/docs", "/redoc", "/openapi.json")


async def cabeceras_de_seguridad(request: Request, call_next):
    respuesta = await call_next(request)
    for nombre, valor in CABECERAS_SEGURIDAD.items():
        respuesta.headers.setdefault(nombre, valor)
    if not request.url.path.startswith(RUTAS_DOCUMENTACION):
        respuesta.headers.setdefault("Content-Security-Policy", CSP_API)
    return respuesta


def instalar(app: FastAPI) -> None:
    """Registra los cuatro manejadores de error y el middleware de cabeceras."""
    app.add_exception_handler(ErrorDeNegocio, manejar_error_de_negocio)
    app.add_exception_handler(StarletteHTTPException, manejar_http)
    app.add_exception_handler(RequestValidationError, manejar_validacion)
    app.add_exception_handler(Exception, manejar_no_controlado)
    app.middleware("http")(cabeceras_de_seguridad)
