# PrediCitas CRP · Backend

API en FastAPI (Python 3.12, SQLAlchemy 2, Alembic, PostgreSQL 16) del MVP PrediCitas CRP.
Todos los datos de pacientes son sintéticos y seudonimizados (`paciente_anon_id`).

## 1. Arranque con Docker (recomendado)

Desde la **raíz del repositorio**:

```bash
cp .env.example .env            # valores solo para desarrollo local
docker compose up --build       # db + migraciones + api + web
```

- API y Swagger: http://localhost:8000/docs · salud: http://localhost:8000/health → `{"estado": "ok"}`
- Frontend: http://localhost:5173
- Solo el backend: `docker compose up --build -d db migraciones api`
- El simulador de IA (cuando exista `ia-simulador/`): `docker compose --profile ia up --build`

Qué hace cada servicio:

| Servicio | Qué hace |
|---|---|
| `db` | PostgreSQL 16. Al crear el volumen por primera vez ejecuta `backend/db/init/*` (T-011 crea ahí el rol `predicitas_app`). |
| `migraciones` | Corre una vez `alembic upgrade head` con el rol dueño (`DATABASE_URL_MIGRACIONES`) y termina. |
| `api` | Arranca cuando `migraciones` terminó bien. Se conecta con el rol `predicitas_app` (`DATABASE_URL`, D-015). |

Comandos útiles:

```bash
docker compose run --rm api pytest                      # pruebas + cobertura
docker compose run --rm api python -m scripts.seed      # carga los datos sintéticos
docker compose run --rm migraciones alembic current     # revisión aplicada
docker compose down -v                                  # borra todo, incluida la base (empezar de cero)
```

> El script de init de Postgres solo corre cuando el volumen está vacío. Si cambias `APP_DB_PASSWORD`
> o se agrega un script nuevo en `backend/db/init/`, ejecuta `docker compose down -v`.

## 2. Arranque sin Docker (`.venv`)

Requisitos: Python 3.12 y un PostgreSQL 16 local con la base `predicitas`.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows  ·  source .venv/bin/activate en Linux/macOS
pip install -r requirements.txt
cp .env.example .env            # ajusta DATABASE_URL y DATABASE_URL_MIGRACIONES a tu Postgres
alembic upgrade head
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

Si trabajas en una tarjeta con puerto propio, usa `--port <puerto de la tarjeta>`.

## 3. Pruebas

```bash
pytest                          # dentro de backend/ (o docker compose run --rm api pytest)
```

`pytest.ini` ya activa `--cov=app` y falla si la cobertura baja de 75 % (D-002). Las pruebas
usan la base configurada en `DATABASE_URL` y deshacen sus cambios al terminar.

Organización:

- `tests/conftest.py`: fixtures comunes (`db`, `client`, `usuarios`) y la función `cabecera()`.
- `tests/auth/`, `tests/citas/`: pruebas de cada módulo.
- `tests/sistema/`: salud, modelos, integridad de BD, formato de error, cabeceras, ranuras, exportación y configuración.

## 4. Convenciones de la base del backend (T-010)

- **Módulos:** cada `app/modules/<modulo>/router.py` que exponga `router` se registra solo
  (`app/core/ranuras.py`). Un módulo nuevo no toca `main.py`.
- **Errores (D-017):** toda respuesta de error es `{"error": {"codigo", "mensaje", "campos"}}`.
  En el código se lanzan las excepciones de `app/core/errores.py`, por ejemplo
  `raise TransicionInvalida("...")` o `raise Conflicto("...", codigo="CUPO_NO_DISPONIBLE")`.
- **Configuración:** todas las variables están en `app/core/config.py` y documentadas en `.env.example`.
- **Exportación:** `app.core.exportacion.responder(filas, columnas, formato, nombre)` devuelve JSON, CSV
  (UTF-8 con BOM) o XLSX. Quien la llama registra el evento `EXPORT` en auditoría.

## 5. Seguridad

- La API añade `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` y una CSP restrictiva
  (salvo en `/docs` y `/openapi.json`, para que Swagger funcione).
- **RNF-003:** en el ambiente desplegado la API va detrás de HTTPS (proxy inverso con TLS). En local no se
  implementa TLS.
- Los secretos viven en `.env` (ignorado por git). Los valores de `.env.example` son solo de desarrollo.
