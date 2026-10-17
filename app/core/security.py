from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()
# Hash ficticio: se verifica contra él cuando el usuario no existe, para que
# la respuesta tarde lo mismo y no revele qué correos están registrados.
HASH_FICTICIO = _hasher.hash("contrasena-ficticia")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def crear_token(id_usuario: str) -> tuple[str, int]:
    s = get_settings()
    expira = datetime.now(timezone.utc) + timedelta(minutes=s.access_token_expire_minutes)
    token = jwt.encode({"sub": id_usuario, "exp": expira}, s.secret_key, algorithm=s.jwt_algorithm)
    return token, s.access_token_expire_minutes * 60


def decodificar_token(token: str) -> dict | None:
    s = get_settings()
    try:
        return jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
    except jwt.PyJWTError:
        return None