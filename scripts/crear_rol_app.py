"""Crea (o actualiza la contraseña de) el rol operativo predicitas_app sin Docker.

Equivale a backend/db/init/01_rol_app.sh para quien trabaja con .venv (RNF-009, D-015).
Uso, desde backend/:  python -m scripts.crear_rol_app
Lee DATABASE_URL_MIGRACIONES (rol dueño) y APP_DB_PASSWORD. Nunca imprime la contraseña.
"""
import os
import sys

import psycopg
from psycopg import sql

ROL_APP = "predicitas_app"


def _url_libpq(url: str) -> str:
    # SQLAlchemy usa "postgresql+psycopg://"; psycopg solo entiende "postgresql://".
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def crear_rol(url_dueno: str, password: str) -> bool:
    """Crea el rol si no existe y fija su contraseña. Devuelve True si lo creó."""
    with psycopg.connect(_url_libpq(url_dueno), autocommit=True) as conn:
        existe = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROL_APP,)).fetchone()
        # Con un dueño sin SUPERUSER solo se puede cambiar la contraseña de un rol existente.
        plantilla = ("ALTER ROLE {} WITH PASSWORD {}" if existe else
                     "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}")
        conn.execute(sql.SQL(plantilla).format(sql.Identifier(ROL_APP), sql.Literal(password)))
        return not existe


def main() -> int:
    url = os.environ.get("DATABASE_URL_MIGRACIONES")
    password = os.environ.get("APP_DB_PASSWORD")
    if not url or not password:
        print("Faltan DATABASE_URL_MIGRACIONES o APP_DB_PASSWORD en el entorno.", file=sys.stderr)
        return 1
    creado = crear_rol(url, password)
    print(f"Rol {ROL_APP} {'creado' if creado else 'ya existía: contraseña actualizada'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
