"""Ranura de routers (contratos/comun.json → ranuras_backend.routers).

Recorre los subpaquetes de app/modules/ en orden alfabético y registra la variable
`router` de cada <modulo>/router.py. Un módulo nuevo solo crea su carpeta: no se toca main.py.
"""
import importlib
from pathlib import Path

from fastapi import APIRouter, FastAPI


def registrar_routers(app: FastAPI, paquete: str = "app.modules") -> list[str]:
    """Incluye en `app` cada router encontrado y devuelve los módulos registrados, en orden."""
    raiz = importlib.import_module(paquete)
    carpetas = sorted(
        (sub for base in raiz.__path__ for sub in Path(base).iterdir()
         if sub.is_dir() and not sub.name.startswith(("_", ".")) and (sub / "router.py").is_file()),
        key=lambda sub: sub.name,
    )
    registrados: list[str] = []
    for sub in carpetas:
        router = getattr(importlib.import_module(f"{paquete}.{sub.name}.router"), "router", None)
        if isinstance(router, APIRouter):
            app.include_router(router)
            registrados.append(sub.name)
    return registrados
