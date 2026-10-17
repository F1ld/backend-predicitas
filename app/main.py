from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import app.core.models  # noqa: F401  (registra todos los modelos)
from app.core.errores import ErrorDeNegocio
from app.modules.auth.router import router as auth_router
from app.modules.citas.router import router as citas_router

app = FastAPI(title="PrediCitas CRP API", version="0.1.0")


@app.exception_handler(ErrorDeNegocio)
async def manejar_error_de_negocio(_: Request, exc: ErrorDeNegocio):
    cabeceras = {"WWW-Authenticate": "Bearer"} if exc.codigo_http == 401 else None
    return JSONResponse(status_code=exc.codigo_http, content={"detalle": exc.mensaje}, headers=cabeceras)


app.include_router(auth_router)
app.include_router(citas_router)


@app.get("/health", tags=["sistema"])
def health():
    return {"estado": "ok"}