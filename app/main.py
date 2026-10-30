"""Punto de entrada de la API PrediCitas CRP.

- Los routers principales y modulares se registran de forma explícita y estructurada.
- Todos los errores salen con la forma {"error": {"codigo", "mensaje", "campos"}} (D-017).
- Cabeceras de seguridad en cada respuesta (app/core/manejadores.py).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.core.models  # noqa: F401  (registra todos los modelos)
from app.core import manejadores
from app.core.config import get_settings
from app.modules.auth.router import router as auth_router
from app.modules.citas.router import router as citas_router
from app.modules.ia.router import router as ia_router
from app.modules.intervenciones.router import router as intervenciones_router
from app.modules.lista_espera.router import router as lista_espera_router
from app.modules.usuarios.router import router as usuarios_router

app = FastAPI(title="PrediCitas CRP API", version="0.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().lista_cors_origenes,
    allow_credentials=False,  # el token viaja en el header Authorization, no en cookies
    allow_methods=["*"],
    allow_headers=["*"],
)
manejadores.instalar(app)

# Montaje limpio y ordenado de routers
app.include_router(auth_router)
app.include_router(citas_router)
app.include_router(usuarios_router)
app.include_router(ia_router)
app.include_router(intervenciones_router)
app.include_router(lista_espera_router)


@app.get("/health", tags=["sistema"])
def health():
    return {"estado": "ok"}
