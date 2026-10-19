# Base de datos: roles, permisos y respaldo

Requisitos: RNF-009 (bitácoras inmutables), D-015, Diseño de BD §5 «Inmutabilidad de Bitácoras».

## 1. Qué rol usa cada conexión

| Conexión | Variable | Rol | Para qué |
|---|---|---|---|
| Migraciones (Alembic) | `DATABASE_URL_MIGRACIONES` | `predicitas_owner` (dueño de las tablas) | Crear y cambiar el esquema. |
| Aplicación (FastAPI) | `DATABASE_URL` | `predicitas_app` | Operación diaria, con permisos mínimos. |

Permisos de `predicitas_app` (los concede la migración `m00_002_rol_operativo`):

| Tablas | Privilegios |
|---|---|
| `usuarios`, `citas`, `predicciones_ia`, `intervenciones`, `lista_espera`, `cupos_liberados`, `reasignaciones` | `SELECT, INSERT, UPDATE` (sin `DELETE`: el diseño no borra filas) |
| `auditoria_eventos`, `historial_estados_cita` | solo `SELECT, INSERT` |
| Secuencias del esquema `public` | `USAGE, SELECT` |

Hay **dos barreras**: los privilegios (lo que el rol puede pedir) y los triggers de solo inserción de la migración inicial (que bloquean `UPDATE`, `DELETE` y `TRUNCATE` incluso al dueño). RLS sigue activo en las 9 tablas con una política `pol_<tabla>_predicitas_app` (`FOR ALL ... USING (true) WITH CHECK (true)`); sin ella, RLS bloquearía a la app.

## 2. Cómo se crea el rol

La contraseña nunca va en el repo: sale de `APP_DB_PASSWORD` en tu `.env`.

- **Con Docker:** `db/init/01_rol_app.sh` se monta en `/docker-entrypoint-initdb.d` y crea el rol la **primera vez** que se inicia el volumen de PostgreSQL. Si el volumen ya existía, no se ejecuta: usa la opción sin Docker o borra el volumen (`docker compose down -v`, pierdes los datos locales).
- **Sin Docker (con `.venv`), desde la carpeta raíz del backend:**
  ```bash
  python -m scripts.crear_rol_app
  ```
  Lee `DATABASE_URL_MIGRACIONES` y `APP_DB_PASSWORD`. Si el rol existe, solo actualiza su contraseña. El rol dueño necesita `CREATEROLE` (o ser superusuario).

Después, `alembic upgrade head`. Si el rol no existe, la migración falla y explica cómo crearlo. `alembic downgrade -1` quita políticas y privilegios, pero no borra el rol.

## 3. Cómo comprobar los permisos

Conéctate **como `predicitas_app`** (`psql "$DATABASE_URL"`, sin el `+psycopg`) y ejecuta:

```sql
SELECT current_user,
       has_table_privilege('auditoria_eventos', 'INSERT')      AS audit_insert,  -- true
       has_table_privilege('auditoria_eventos', 'UPDATE')      AS audit_update,  -- false
       has_table_privilege('historial_estados_cita', 'DELETE') AS hist_delete,   -- false
       has_table_privilege('citas', 'DELETE')                  AS citas_delete;  -- false
SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public';    -- 9 políticas
```

Las pruebas automáticas: `pytest tests/bd` con `DATABASE_URL` apuntando a `predicitas_app`. Si la conexión usa otro rol o no hay base, se marcan como omitidas (no pasan en falso).

## 4. Respaldo y restauración local

Se hacen con el rol **dueño**. Formato personalizado (`-Fc`), comprimido y restaurable por partes.

```bash
# Respaldo (con Docker: anteponer «docker compose exec -T db»)
pg_dump -U predicitas_owner -d predicitas -Fc -f respaldo_predicitas_AAAA-MM-DD.dump

# Restauración en una base vacía
createdb -U predicitas_owner predicitas_restaurada
pg_restore -U predicitas_owner -d predicitas_restaurada --no-owner --role=predicitas_owner respaldo_predicitas_AAAA-MM-DD.dump
```

- El volcado incluye datos, triggers, RLS, políticas y `GRANT`; los **roles no** (son del clúster). En un servidor nuevo crea primero `predicitas_app` (§2) y luego restaura.
- Comprueba la restauración: `alembic current` debe mostrar `m00_002_rol_operativo (head)` y las consultas de §3 deben dar lo mismo.
- Los respaldos contienen datos (sintéticos en este MVP): no los subas al repositorio.
