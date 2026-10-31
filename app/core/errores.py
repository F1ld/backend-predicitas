"""Excepciones de negocio con código estable (D-017, contratos/comun.json → formato_error).

Cada clase define su código HTTP y su `codigo` por defecto. Al lanzarla se puede
sobrescribir el código y añadir `campos`:

    raise TransicionInvalida("La cita ya fue atendida")
    raise Conflicto("El cupo ya fue asignado", codigo="CUPO_NO_DISPONIBLE")
    raise Validacion("Dato inválido", campos={"sede": "Fuera del piloto"})

main.py convierte cualquiera de ellas en {"error": {"codigo", "mensaje", "campos"}}.
"""


class ErrorDeNegocio(Exception):
    codigo_http = 400
    codigo = "SOLICITUD_INVALIDA"

    def __init__(self, mensaje: str, *, codigo: str | None = None,
                 campos: dict[str, str] | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        if codigo is not None:
            self.codigo = codigo
        self.campos = campos or {}


class SolicitudInvalida(ErrorDeNegocio):
    codigo_http = 400
    codigo = "SOLICITUD_INVALIDA"


class NoAutenticado(ErrorDeNegocio):
    codigo_http = 401
    codigo = "NO_AUTENTICADO"


class SesionInvalida(ErrorDeNegocio):
    codigo_http = 401
    codigo = "SESION_INVALIDA"


class SinPermiso(ErrorDeNegocio):
    codigo_http = 403
    codigo = "SIN_PERMISO"


class NoEncontrado(ErrorDeNegocio):
    codigo_http = 404
    codigo = "NO_ENCONTRADO"


class Conflicto(ErrorDeNegocio):
    """409 genérico: cada endpoint indica su código concreto al lanzarlo."""
    codigo_http = 409
    codigo = "CONFLICTO"


class TransicionInvalida(Conflicto):
    codigo = "TRANSICION_INVALIDA"


class Validacion(ErrorDeNegocio):
    codigo_http = 422
    codigo = "VALIDACION"


class ArchivoInvalido(ErrorDeNegocio):
    codigo_http = 422
    codigo = "ARCHIVO_INVALIDO"


class FueraDePerimetro(ErrorDeNegocio):
    codigo_http = 422
    codigo = "FUERA_DE_PERIMETRO"


class DemasiadosIntentos(ErrorDeNegocio):
    codigo_http = 429
    codigo = "DEMASIADOS_INTENTOS"


class MotorIANoDisponible(ErrorDeNegocio):
    codigo_http = 503
    codigo = "MOTOR_IA_NO_DISPONIBLE"

ConflictoDeNegocio = Conflicto
ReglaDeNegocioInvalida = SolicitudInvalida
