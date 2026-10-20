"""Punto de entrada de la API PrediCitas CRP.

- Los routers se registran solos desde app/modules/*/router.py (app/core/ranuras.py).
- Todos los errores salen con la forma {"error": {"codigo", "mensaje", "campos"}} (D-017).
- Cabeceras de seguridad en cada respuesta (app/core/manejadores.py).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.core.models  # noqa: F401  (registra todos los modelos)
from app.core import manejadores
from app.core.config import get_settings
from app.core.ranuras import registrar_routers

app = FastAPI(title="PrediCitas CRP API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().lista_cors_origenes,
    allow_credentials=False,  # el token viaja en el header Authorization, no en cookies
    allow_methods=["*"],
    allow_headers=["*"],
)
manejadores.instalar(app)
registrar_routers(app)


@app.get("/health", tags=["sistema"])
def health():
    return {"estado": "ok"}
