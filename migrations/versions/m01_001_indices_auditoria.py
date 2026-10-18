"""índices de auditoria_eventos para sesión, bloqueo y trazabilidad

Crea los dos índices del diccionario de datos (docs/diccionario-de-datos.json →
auditoria_eventos.indices):
- (id_usuario, accion, creado_en): bloqueo por intentos (D-009) e invalidación de
  sesiones por LOGOUT (D-010), que se consultan en cada login y en cada petición.
- (entidad_afectada, id_entidad): trazabilidad, check-in y oferta vigente (D-012, D-014).

Revision ID: m01_001_indices_auditoria
Revises: m00_002_rol_operativo
Create Date: 2026-10-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "m01_001_indices_auditoria"
down_revision: Union[str, Sequence[str], None] = "m00_002_rol_operativo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_auditoria_eventos_usuario_accion_fecha", "auditoria_eventos",
                    ["id_usuario", "accion", "creado_en"])
    op.create_index("ix_auditoria_eventos_entidad", "auditoria_eventos",
                    ["entidad_afectada", "id_entidad"])


def downgrade() -> None:
    op.drop_index("ix_auditoria_eventos_entidad", table_name="auditoria_eventos")
    op.drop_index("ix_auditoria_eventos_usuario_accion_fecha", table_name="auditoria_eventos")
