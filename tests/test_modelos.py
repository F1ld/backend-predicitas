import app.core.models  # noqa: F401
from app.core.database import Base

TABLAS_ESPERADAS = {
    "usuarios", "citas", "historial_estados_cita", "predicciones_ia",
    "intervenciones", "lista_espera", "cupos_liberados", "reasignaciones",
    "auditoria_eventos",
}


def test_el_esquema_tiene_las_nueve_tablas():
    assert set(Base.metadata.tables) == TABLAS_ESPERADAS


def test_claves_primarias_son_bigint():
    for tabla in Base.metadata.tables.values():
        for columna in tabla.primary_key.columns:
            assert columna.type.__class__.__name__ == "BigInteger", tabla.name