"""Carga usuarios demo y el dataset oficial (1,000 citas históricas + 80 próximas) en la base de datos.

Uso interactivo o por argumentos:
    python -m scripts.seed [--historicas 1000] [--proximas 80] [--semilla 42] [--password <clave>]

Para recargar desde cero respetando los triggers de inmutabilidad (INSERT-ONLY en historial y auditoría):
    alembic downgrade base && alembic upgrade head && python -m scripts.seed --password DemoCRP2026!
"""
import argparse
import getpass
import os
from datetime import date

from sqlalchemy import func, select

import app.core.models  # noqa: F401
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Usuario
from app.modules.citas.importer import importar_citas
from app.modules.citas.models import Cita
from app.modules.citas.synthetic import generar_citas

USUARIOS_DEMO = [
    ("Administrador Demo", "admin@predicitas.crp", "ADMINISTRADOR"),
    ("Recepcion Demo", "recepcion@predicitas.crp", "RECEPCION"),
    ("Tecnico IA Demo", "tecnico.ia@predicitas.crp", "TECNICO_IA"),
]


def _obtener_password(arg_password: str | None) -> str:
    if arg_password:
        return arg_password
    env_pwd = os.environ.get("SEED_PASSWORD")
    if env_pwd:
        return env_pwd
    return getpass.getpass("Contraseña para los 3 usuarios demo (mínimo 8 caracteres): ")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--historicas", type=int, default=1000, help="Citas históricas cerradas (default: 1000)")
    parser.add_argument("--proximas", type=int, default=80, help="Citas próximas operativas en estado RECIBIDA (default: 80)")
    parser.add_argument("--semilla", type=int, default=42, help="Semilla reproducible (default: 42)")
    parser.add_argument("--desde", type=date.fromisoformat, default=date(2026, 10, 29), help="Fecha de corte (YYYY-MM-DD)")
    parser.add_argument("--tasa-no-show", type=float, default=0.20, help="Tasa basal de no-show entre 0.18 y 0.22 (default: 0.20)")
    parser.add_argument("--con-invalidas", action="store_true", help="Incluir las 4 filas inválidas de prueba del importador")
    parser.add_argument("--password", type=str, default=None, help="Contraseña para los usuarios demo (mínimo 8 caracteres)")
    args = parser.parse_args()

    password = _obtener_password(args.password)
    if len(password) < 8:
        raise SystemExit("La contraseña debe tener al menos 8 caracteres.")

    with SessionLocal() as db:
        por_rol: dict[str, Usuario] = {}
        pwd_hash = hash_password(password)
        for nombre, correo, rol in USUARIOS_DEMO:
            usuario = db.scalar(select(Usuario).where(Usuario.correo_institucional == correo))
            if usuario is None:
                usuario = Usuario(
                    nombre_completo=nombre,
                    correo_institucional=correo,
                    password_hash=pwd_hash,
                    rol=rol,
                    activo=True,
                )
                db.add(usuario)
                print(f"Usuario creado : {correo} ({rol})")
            else:
                print(f"Usuario existe : {correo} ({rol})")
            por_rol[rol] = usuario
        db.commit()

        existentes = db.scalar(select(func.count(Cita.id_cita)).where(Cita.id_cita_externa.like("CIT-SIM-%"))) or 0
        if existentes > 0:
            print(
                f"Ya existen {existentes} citas sintéticas (CIT-SIM-*) en la tabla `citas`.\n"
                "Nota: Como `historial_estados_cita` y `auditoria_eventos` tienen triggers INSERT-ONLY,\n"
                "para regenerar desde cero ejecute:\n"
                "  alembic downgrade base && alembic upgrade head && python -m scripts.seed --password <clave>"
            )
            return

        registros = generar_citas(
            historicas=args.historicas,
            proximas=args.proximas,
            semilla=args.semilla,
            desde=args.desde,
            tasa_no_show=args.tasa_no_show,
            con_invalidas=args.con_invalidas,
        )
        resultado = importar_citas(
            db,
            registros,
            id_usuario=por_rol["ADMINISTRADOR"].id_usuario,
            ip="127.0.0.1",
            origen=f"seed sintético acreditado E-04 (semilla={args.semilla}, hist={args.historicas}, prox={args.proximas})",
        )

        total_hist = db.scalar(select(func.count(Cita.id_cita)).where(Cita.target_no_show.is_not(None))) or 0
        total_no_show = db.scalar(select(func.count(Cita.id_cita)).where(Cita.target_no_show == 1)) or 0
        total_prox = db.scalar(select(func.count(Cita.id_cita)).where(Cita.target_no_show.is_(None))) or 0
        tasa_real = (total_no_show / total_hist * 100.0) if total_hist else 0.0

        print("=" * 70)
        print("POBLADO OFICIAL COMPLETADO EN BASE DE DATOS")
        print("=" * 70)
        print(f"Filas procesadas : {resultado.recibidas} recibidas | {resultado.aceptadas} aceptadas | {resultado.rechazadas} rechazadas")
        print(f"Citas históricas : {total_hist} (ATENDIDA={total_hist - total_no_show}, NO_SHOW={total_no_show}, Tasa No-Show={tasa_real:.2f}%)")
        print(f"Citas próximas   : {total_prox} (estado='RECIBIDA', target_no_show=NULL)")
        print("=" * 70)
        for r in resultado.detalle_rechazos:
            print(f"  fila {r.fila} [{r.id_cita_externa}]: {'; '.join(r.motivos)}")


if __name__ == "__main__":
    main()
