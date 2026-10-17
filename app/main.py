from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import app.core.models  # noqa: F401  (registra todos los modelos)
from app.core.errores import ErrorDeNegocio
from app.modules.auth.router import router as auth_router
from app.modules.citas.router import router as citas_router

ORIGENES_PERMITIDOS = [
       "http://localhost:5173",
       "http://127.0.0.1:5173",
   ]

app = FastAPI(title="PrediCitas CRP API", version="0.1.0")

app.add_middleware(
       CORSMiddleware,
       allow_origins=ORIGENES_PERMITIDOS,
       allow_credentials=False,   # el token viaja en el header Authorization, no en cookies
       allow_methods=["*"],
       allow_headers=["*"],
   )

@app.exception_handler(ErrorDeNegocio)
async def manejar_error_de_negocio(_: Request, exc: ErrorDeNegocio):
    cabeceras = {"WWW-Authenticate": "Bearer"} if exc.codigo_http == 401 else None
    return JSONResponse(status_code=exc.codigo_http, content={"detalle": exc.mensaje}, headers=cabeceras)


app.include_router(auth_router)
app.include_router(citas_router)


@app.get("/health", tags=["sistema"])
def health():
    return {"estado": "ok"}