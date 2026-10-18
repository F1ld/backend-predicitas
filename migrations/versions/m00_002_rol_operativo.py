"""rol operativo predicitas_app: auditoría inmutable por permisos

Concede al rol de la aplicación solo lo que necesita (RNF-009, D-015,
Diseño de BD §5 «Inmutabilidad de Bitácoras»):
- SELECT, INSERT, UPDATE en las 7 tablas operativas (sin DELETE: el diseño no borra filas).
- Solo SELECT, INSERT en auditoria_eventos e historial_estados_cita.
- Una política RLS por tabla para que RLS siga activo sin bloquear a la app.
Los triggers de solo inserción de la migración inicial se mantienen como segunda barrera.

El rol se crea fuera de la migración (backend/db/init/01_rol_app.sh o
backend/scripts/crear_rol_app.py) porque su contraseña no debe vivir en el repo.

Revision ID: m00_002_rol_operativo
Revises: 2cfdcb7d3da2
Create Date: 2026-10-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "m00_002_rol_operativo"
down_revision: Union[str, Sequence[str], None] = "2cfdcb7d3da2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROL_APP = "predicitas_app"
TABLAS_OPERATIVAS = (
    "usuarios", "citas", "predicciones_ia", "intervenciones",
    "lista_espera", "cupos_liberados", "reasignaciones",
)
TABLAS_SOLO_INSERCION = ("historial_estados_cita", "auditoria_eventos")


def _politica(tabla: str) -> str:
    return f"pol_{tabla}_{ROL_APP}"


def upgrade() -> None:
    existe = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :rol"), {"rol": ROL_APP}
    ).scalar()
    if not existe:
        raise RuntimeError(
            f"El rol '{ROL_APP}' no existe. Créalo antes de migrar: con Docker lo crea "
            "backend/db/init/01_rol_app.sh al iniciar una base nueva; sin Docker ejecuta "
            "'python -m scripts.crear_rol_app' desde backend/ (lee DATABASE_URL_MIGRACIONES "
            "y APP_DB_PASSWORD). Ver backend/db/README.md."
        )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROL_APP}")
    for tabla in TABLAS_OPERATIVAS:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {tabla} TO {ROL_APP}")
    for tabla in TABLAS_SOLO_INSERCION:
        op.execute(f"GRANT SELECT, INSERT ON {tabla} TO {ROL_APP}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROL_APP}")

    for tabla in TABLAS_OPERATIVAS + TABLAS_SOLO_INSERCION:
        op.execute(
            f"CREATE POLICY {_politica(tabla)} ON {tabla} FOR ALL TO {ROL_APP} "
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    # Revierte políticas y privilegios; el rol no se borra (puede tener otras dependencias).
    for tabla in TABLAS_OPERATIVAS + TABLAS_SOLO_INSERCION:
        op.execute(f"DROP POLICY IF EXISTS {_politica(tabla)} ON {tabla}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROL_APP}")
    for tabla in TABLAS_OPERATIVAS + TABLAS_SOLO_INSERCION:
        op.execute(f"REVOKE ALL ON {tabla} FROM {ROL_APP}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROL_APP}")
