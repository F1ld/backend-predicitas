class ErrorDeNegocio(Exception):
    codigo_http = 400

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje


class NoAutenticado(ErrorDeNegocio):
    codigo_http = 401


class SinPermiso(ErrorDeNegocio):
    codigo_http = 403


class NoEncontrado(ErrorDeNegocio):
    codigo_http = 404


class TransicionInvalida(ErrorDeNegocio):
    codigo_http = 409


class ArchivoInvalido(ErrorDeNegocio):
    codigo_http = 422