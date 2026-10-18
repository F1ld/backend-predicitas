#!/bin/bash
# Crea el rol operativo predicitas_app al iniciar una base nueva (RNF-009, D-015).
# Lo ejecuta la imagen oficial de PostgreSQL desde /docker-entrypoint-initdb.d
# como POSTGRES_USER (el dueño). Idempotente: si el rol ya existe, no hace nada.
# Los privilegios y las políticas RLS los concede la migración m00_002_rol_operativo.
set -euo pipefail

if [ -z "${APP_DB_PASSWORD:-}" ]; then
    echo "01_rol_app.sh: falta APP_DB_PASSWORD; no se crea predicitas_app." >&2
    exit 1
fi

# La contraseña viaja como variable de psql (:'clave'), nunca en la línea de comandos ni en el log.
psql -v ON_ERROR_STOP=1 -v clave="$APP_DB_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SELECT format('CREATE ROLE predicitas_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'clave')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'predicitas_app')
\gexec
SQL

echo "01_rol_app.sh: rol predicitas_app listo."
