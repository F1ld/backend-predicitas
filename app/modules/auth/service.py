from sqlalchemy.orm import Session

from app.core.errores import NoAutenticado
from app.core.security import HASH_FICTICIO, crear_token, verify_password
from app.modules.auditoria.service import registrar_evento
from app.modules.auth import repository


def autenticar(db: Session, correo: str, password: str, ip: str) -> tuple[str, int]:
    usuario = repository.por_correo(db, correo)
    clave_ok = verify_password(password, usuario.password_hash if usuario else HASH_FICTICIO)

    if usuario is None or not clave_ok or not usuario.activo:
        if usuario is None:
            motivo = "usuario_inexistente"
        elif not usuario.activo:
            motivo = "usuario_inactivo"
        else:
            motivo = "clave_incorrecta"
        registrar_evento(
            db, modulo="AUTENTICACION", accion="LOGIN", entidad_afectada="usuarios",
            direccion_ip=ip, id_usuario=usuario.id_usuario if usuario else None,
            id_entidad=usuario.id_usuario if usuario else None,
            datos_after={"resultado": "FALLIDO", "motivo": motivo},
        )
        db.commit()  # el intento fallido debe quedar registrado aunque se responda 401
        raise NoAutenticado("Credenciales inválidas")

    token, segundos = crear_token(str(usuario.id_usuario))
    registrar_evento(
        db, modulo="AUTENTICACION", accion="LOGIN", entidad_afectada="usuarios",
        direccion_ip=ip, id_usuario=usuario.id_usuario, id_entidad=usuario.id_usuario,
        datos_after={"resultado": "EXITOSO"},
    )
    db.commit()
    return token, segundos