"""JWT de sesión con `iat` en milisegundos (F-02, D-010, contratos/comun.json → auth.token).

El token lleva `sub` (id_usuario como texto), `iat` (NumericDate con 3 decimales) y
`exp` (= iat + ACCESS_TOKEN_EXPIRE_MINUTES). El `iat` es lo que permite invalidar la
sesión tras un LOGOUT o un cambio en usuarios.actualizado_en sin tabla de sesiones.
"""
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings

EPOCA = datetime(1970, 1, 1, tzinfo=timezone.utc)


def crear_token(id_usuario: int, emitido_en: datetime) -> tuple[str, int]:
    s = get_settings()
    segundos = s.access_token_expire_minutes * 60
    iat = round(emitido_en.timestamp(), 3)
    carga = {"sub": str(id_usuario), "iat": iat, "exp": iat + segundos}
    return jwt.encode(carga, s.secret_key, algorithm=s.jwt_algorithm), segundos


def leer_token(token: str, momento: datetime) -> tuple[int, datetime] | None:
    """Devuelve (id_usuario, iat) si la firma es válida y el token no venció en `momento`; si no, None.

    El vencimiento se comprueba contra el reloj del módulo (no contra el de PyJWT) para
    que las pruebas puedan mover la hora.
    """
    s = get_settings()
    try:
        carga = jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm],
                           options={"require": ["sub", "iat", "exp"], "verify_exp": False,
                                    "verify_iat": False})
        if float(carga["exp"]) <= momento.timestamp():
            return None
        milisegundos = round(float(carga["iat"]) * 1000)  # evita el error de redondeo del float
        return int(carga["sub"]), EPOCA + timedelta(milliseconds=milisegundos)
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None


def mas_un_milisegundo(momento: datetime) -> datetime:
    return momento + timedelta(milliseconds=1)
