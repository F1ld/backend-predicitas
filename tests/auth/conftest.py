"""Reloj controlable para las pruebas de M01 (sin freezegun: se inyecta el «ahora», D-009)."""
from datetime import timedelta

import pytest

from app.modules.auth import reloj as reloj_mod


class RelojDePrueba:
    def __init__(self, inicio):
        self.momento = inicio

    def __call__(self):
        return self.momento

    def avanzar(self, **delta):
        self.momento += timedelta(**delta)


@pytest.fixture
def reloj(monkeypatch):
    r = RelojDePrueba(reloj_mod.ahora())
    monkeypatch.setattr(reloj_mod, "ahora", r)
    return r
