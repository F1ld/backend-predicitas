"""Autenticación: login con bloqueo por intentos, sesión e invalidación, cambio de clave.

RF-001, RF-002, RF-090, RNF-002, RNF-004, RNF-005 · flujos F-01 y F-02 · D-009, D-010.
Ningún evento de auditoría guarda contraseñas, hashes ni tokens.
"""
import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errores import Conflicto, DemasiadosIntentos, NoAutenticado, SesionInvalida, Validacion
from app.core.security import HASH_FICTICIO, hash_password, verify_password
from app.modules.auditoria.service import registrar_evento
from app.modules.auth import reloj, repository, tokens
from app.modules.auth.models import Usuario


def auditar(db: Session, momento: datetime, **datos):
    """registrar_evento con creado_en = hora del módulo (misma precisión que el iat del token).

    Se fija a mano porque now() de PostgreSQL es la hora de inicio de la transacción.
    """
    evento = registrar_evento(db, **datos)
    evento.creado_en = momento
    return evento


def _auditar_login(db: Session, momento: datetime, ip: str, usuario: Usuario | None, resultado: str,
                   motivo: str | None = None) -> None:
    datos_after = {"resultado": resultado} | ({"motivo": motivo} if motivo else {})
    id_usuario = usuario.id_usuario if usuario else None
    auditar(db, momento, modulo="AUTENTICACION", accion="LOGIN", entidad_afectada="usuarios",
            direccion_ip=ip, id_usuario=id_usuario, id_entidad=id_usuario, datos_after=datos_after)


def minutos_de_bloqueo(db: Session, usuario: Usuario, momento: datetime) -> int:
    """Minutos que faltan para que la cuenta se desbloquee, o 0 si no está bloqueada (D-009).

    Bloqueada = LOGIN_MAX_INTENTOS fallos (posteriores al último login exitoso) dentro de
    LOGIN_VENTANA_MINUTOS, y aún no pasaron LOGIN_BLOQUEO_MINUTOS desde el último fallo.
    """
    s = get_settings()
    ventana = timedelta(minutes=s.login_ventana_minutos)
    bloqueo = timedelta(minutes=s.login_bloqueo_minutos)
    fallos = repository.fallos_recientes(db, usuario.id_usuario, momento - ventana - bloqueo,
                                         s.login_max_intentos)
    if len(fallos) < s.login_max_intentos or fallos[0] - fallos[-1] > ventana:
        return 0
    restante = fallos[0] + bloqueo - momento
    return max(0, math.ceil(restante.total_seconds() / 60))


def autenticar(db: Session, correo: str, password: str, ip: str) -> tuple[str, int]:
    momento = reloj.ahora()
    usuario = repository.por_correo(db, correo)

    # El bloqueo se mira ANTES de verificar la clave: durante el bloqueo no se revela si era correcta.
    if usuario is not None:
        minutos = minutos_de_bloqueo(db, usuario, momento)
        if minutos:
            _auditar_login(db, momento, ip, usuario, "BLOQUEADO")
            db.commit()
            raise DemasiadosIntentos(
                f"Demasiados intentos fallidos. Vuelve a intentarlo en {minutos} minutos.")

    # Con correo inexistente se verifica contra un hash ficticio para que tarde lo mismo.
    clave_ok = verify_password(password, usuario.password_hash if usuario else HASH_FICTICIO)
    if usuario is None or not clave_ok or not usuario.activo:
        if usuario is None:
            motivo = "usuario_inexistente"
        elif not usuario.activo:
            motivo = "usuario_inactivo"
        else:
            motivo = "clave_incorrecta"
        _auditar_login(db, momento, ip, usuario, "FALLIDO", motivo)
        db.commit()  # el intento fallido debe quedar registrado aunque se responda 401
        raise NoAutenticado("Credenciales inválidas")

    token = tokens.crear_token(usuario.id_usuario, momento)
    _auditar_login(db, momento, ip, usuario, "EXITOSO")
    db.commit()
    return token


def usuario_de_token(db: Session, token: str) -> Usuario:
    """Valida el token y devuelve su usuario; si no vale, 401 SESION_INVALIDA (F-02, D-010).

    No vale si: la firma es inválida o venció; el usuario no existe o está inactivo;
    hay un LOGOUT del usuario en su iat o después; o usuarios.actualizado_en es igual o
    posterior a su iat (cambio de rol, clave, restablecimiento o estado).
    """
    leido = tokens.leer_token(token, reloj.ahora())
    if leido is None:
        raise SesionInvalida("La sesión expiró o no es válida")
    id_usuario, iat = leido
    usuario = repository.por_id(db, id_usuario)
    if usuario is None or not usuario.activo:
        raise SesionInvalida("La sesión expiró o no es válida")
    if usuario.actualizado_en is not None and usuario.actualizado_en >= iat:
        raise SesionInvalida("La sesión expiró o no es válida")
    if repository.hay_logout_desde(db, id_usuario, iat):
        raise SesionInvalida("La sesión expiró o no es válida")
    return usuario


def cerrar_sesion(db: Session, usuario: Usuario, ip: str) -> None:
    auditar(db, reloj.ahora(), modulo="AUTENTICACION", accion="LOGOUT", entidad_afectada="usuarios",
            direccion_ip=ip, id_usuario=usuario.id_usuario, id_entidad=usuario.id_usuario)
    db.commit()


def renovar(usuario: Usuario) -> tuple[str, int]:
    """Token nuevo; el anterior sigue valiendo hasta su exp. Sin auditoría (evita ruido)."""
    return tokens.crear_token(usuario.id_usuario, reloj.ahora())


def cambiar_clave(db: Session, usuario: Usuario, clave_actual: str, clave_nueva: str,
                  ip: str) -> tuple[str, int]:
    if not verify_password(clave_actual, usuario.password_hash):
        raise Conflicto("La clave actual no es correcta", codigo="CLAVE_ACTUAL_INCORRECTA")
    if clave_nueva == clave_actual:
        raise Validacion("Los datos enviados no son válidos",
                         campos={"clave_nueva": "Debe ser distinta de la clave actual"})

    momento = reloj.ahora()
    usuario.password_hash = hash_password(clave_nueva)
    usuario.actualizado_en = momento  # invalida los tokens anteriores
    auditar(db, momento, modulo="USUARIOS", accion="CAMBIO_CLAVE", entidad_afectada="usuarios",
            direccion_ip=ip, id_usuario=usuario.id_usuario, id_entidad=usuario.id_usuario,
            datos_after={"actualizado_en": momento.isoformat()})
    db.commit()
    # El token nuevo se emite 1 ms después del cambio para que no caiga en la invalidación.
    return tokens.crear_token(usuario.id_usuario, tokens.mas_un_milisegundo(momento))
