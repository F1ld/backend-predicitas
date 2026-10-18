"""Reloj inyectable del módulo (D-009, D-010).

Todo el módulo de autenticación y usuarios pide la hora a `ahora()`, así las pruebas
pueden moverla (monkeypatch de `app.modules.auth.reloj.ahora`) sin dependencias nuevas.
La hora se trunca a milisegundos: es la misma precisión que el `iat` del token, de modo
que comparar `iat` con `creado_en` de un LOGOUT o con `actualizado_en` es exacto.
"""
from datetime import datetime, timezone


def ahora() -> datetime:
    momento = datetime.now(timezone.utc)
    return momento.replace(microsecond=momento.microsecond // 1000 * 1000)
