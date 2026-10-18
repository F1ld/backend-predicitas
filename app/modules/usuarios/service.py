"""Gestión de usuarios (F-03 · RF-004 a RF-008, RF-090).

Cada cambio y su evento de auditoría (modulo=USUARIOS) se confirman en la misma transacción.
Cambiar rol, clave o estado fija actualizado_en = ahora, lo que invalida los tokens
anteriores de ese usuario (D-010). La auditoría nunca guarda contraseñas ni hashes.
"""
import secrets
import string

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, NoEncontrado
from app.core.security import hash_password
from app.modules.auth import reloj
from app.modules.auth import repository as auth_repo
from app.modules.auth.models import Usuario
from app.modules.auth.schemas import validar_clave
from app.modules.auth.service import auditar
from app.modules.usuarios import repository
from app.modules.usuarios.schemas import (
    EstadoIn, FiltrosUsuarios, UsuarioCrearIn, UsuarioEditarIn,
)

ALFABETO_CLAVE = string.ascii_letters + string.digits
LARGO_CLAVE_TEMPORAL = 12


def foto(u: Usuario) -> dict:
    """Datos de auditoría del usuario: sin password_hash."""
    return {
        "id_usuario": u.id_usuario, "nombre_completo": u.nombre_completo,
        "correo_institucional": u.correo_institucional, "rol": u.rol, "activo": u.activo,
    }


def _auditar(db, actor: Usuario, ip: str, accion: str, objetivo: Usuario, momento,
             antes: dict | None = None, despues: dict | None = None) -> None:
    auditar(db, momento, modulo="USUARIOS", accion=accion, entidad_afectada="usuarios",
            direccion_ip=ip, id_usuario=actor.id_usuario, id_entidad=objetivo.id_usuario,
            datos_before=antes, datos_after=despues)


def _obtener(db: Session, id_usuario: int, *, bloquear: bool = False) -> Usuario:
    usuario = (repository.por_id_para_actualizar(db, id_usuario) if bloquear
               else auth_repo.por_id(db, id_usuario))
    if usuario is None:
        raise NoEncontrado(f"No existe el usuario {id_usuario}")
    return usuario


def _exigir_otro_administrador(db: Session, objetivo: Usuario) -> None:
    if repository.otros_administradores_activos(db, objetivo.id_usuario) == 0:
        raise Conflicto("Debe quedar al menos un ADMINISTRADOR activo", codigo="ULTIMO_ADMINISTRADOR")


def listar(db: Session, filtros: FiltrosUsuarios) -> dict:
    total, items = repository.listar(db, filtros)
    return {"total": total, "limite": filtros.limite, "desplazamiento": filtros.desplazamiento,
            "items": items}


def obtener(db: Session, id_usuario: int) -> Usuario:
    return _obtener(db, id_usuario)


def crear(db: Session, datos: UsuarioCrearIn, actor: Usuario, ip: str) -> Usuario:
    """RF-004: queda activo; correo en minúsculas y único sin distinguir mayúsculas."""
    duplicado = Conflicto("Ya existe un usuario con ese correo institucional", codigo="CORREO_DUPLICADO")
    if auth_repo.por_correo(db, datos.correo_institucional) is not None:
        raise duplicado
    momento = reloj.ahora()
    usuario = Usuario(nombre_completo=datos.nombre_completo, correo_institucional=datos.correo_institucional,
                      rol=datos.rol, password_hash=hash_password(datos.clave_inicial), activo=True,
                      creado_en=momento)
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError:  # carrera con otra alta del mismo correo
        db.rollback()
        raise duplicado from None
    _auditar(db, actor, ip, "CREATE", usuario, momento, despues=foto(usuario))
    db.commit()
    return usuario


def editar(db: Session, id_usuario: int, datos: UsuarioEditarIn, actor: Usuario, ip: str) -> Usuario:
    """RF-005: nombre y rol. Cambiar el rol invalida las sesiones del usuario."""
    usuario = _obtener(db, id_usuario, bloquear=True)
    antes = foto(usuario)
    cambia_rol = datos.rol is not None and datos.rol != usuario.rol
    if cambia_rol:
        if usuario.id_usuario == actor.id_usuario:
            raise Conflicto("No puede cambiar su propio rol", codigo="AUTOMODIFICACION_ROL")
        if usuario.rol == "ADMINISTRADOR" and usuario.activo:
            _exigir_otro_administrador(db, usuario)

    momento = reloj.ahora()
    if datos.nombre_completo is not None:
        usuario.nombre_completo = datos.nombre_completo
    if cambia_rol:
        usuario.rol = datos.rol
        usuario.actualizado_en = momento
    if foto(usuario) != antes:
        _auditar(db, actor, ip, "UPDATE", usuario, momento, antes, foto(usuario))
    db.commit()
    return usuario


def cambiar_estado(db: Session, id_usuario: int, datos: EstadoIn, actor: Usuario, ip: str) -> Usuario:
    """RF-006: baja lógica. Nunca uno mismo ni el último ADMINISTRADOR activo."""
    usuario = _obtener(db, id_usuario, bloquear=True)
    if usuario.activo == datos.activo:
        return usuario  # sin cambios: no se audita ni se invalidan sesiones
    if not datos.activo:
        if usuario.id_usuario == actor.id_usuario:
            raise Conflicto("No puede desactivarse a sí mismo", codigo="AUTODESACTIVACION")
        if usuario.rol == "ADMINISTRADOR":
            _exigir_otro_administrador(db, usuario)

    momento = reloj.ahora()
    antes = foto(usuario)
    usuario.activo = datos.activo
    usuario.actualizado_en = momento
    _auditar(db, actor, ip, "ACTIVAR" if datos.activo else "DESACTIVAR", usuario, momento, antes, foto(usuario))
    db.commit()
    return usuario


def generar_clave_temporal() -> str:
    """12 caracteres aleatorios (secrets) que cumplen la política de contraseña."""
    while True:
        clave = "".join(secrets.choice(ALFABETO_CLAVE) for _ in range(LARGO_CLAVE_TEMPORAL))
        try:
            return validar_clave(clave)
        except ValueError:
            continue


def restablecer_acceso(db: Session, id_usuario: int, actor: Usuario, ip: str) -> dict:
    """RF-008: la clave temporal se devuelve una sola vez; se guarda solo su hash."""
    usuario = _obtener(db, id_usuario, bloquear=True)
    clave = generar_clave_temporal()
    momento = reloj.ahora()
    usuario.password_hash = hash_password(clave)
    usuario.actualizado_en = momento
    _auditar(db, actor, ip, "RESET_CLAVE", usuario, momento,
             despues={"actualizado_en": momento.isoformat()})
    db.commit()
    return {"id_usuario": usuario.id_usuario, "clave_temporal": clave}
