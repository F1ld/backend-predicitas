"""Carga usuarios demo y citas sintéticas simulando una importación.

Uso:   python -m scripts.seed [--historicas 300] [--proximas 60] [--semilla 42]
Para recargar desde cero (las tablas de historial/auditoría no admiten DELETE):
       alembic downgrade base && alembic upgrade head && python -m scripts.seed
"""
import argparse
import getpass
from datetime import date

from sqlalchemy import select

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--historicas", type=int, default=300)
    parser.add_argument("--proximas", type=int, default=60)
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument("--desde", type=date.fromisoformat, default=date(2026, 10, 20))
    args = parser.parse_args()

    password = getpass.getpass("Contraseña para los 3 usuarios demo (mínimo 8 caracteres): ")
    if len(password) < 8:
        raise SystemExit("La contraseña debe tener al menos 8 caracteres.")

    with SessionLocal() as db:
        por_rol: dict[str, Usuario] = {}
        for nombre, correo, rol in USUARIOS_DEMO:
            usuario = db.scalar(select(Usuario).where(Usuario.correo_institucional == correo))
            if usuario is None:
                usuario = Usuario(nombre_completo=nombre, correo_institucional=correo,
                                  password_hash=hash_password(password), rol=rol)
                db.add(usuario)
                print(f"Usuario creado : {correo} ({rol})")
            else:
                print(f"Usuario existe : {correo} ({rol})")
            por_rol[rol] = usuario
        db.commit()

        if db.scalar(select(Cita.id_cita).where(Cita.id_cita_externa.like("CIT-SIM-%")).limit(1)):
            print("Ya existen citas sintéticas (CIT-SIM-*): se omite la importación.")
            return

        registros = generar_citas(args.historicas, args.proximas, args.semilla, args.desde)
        resultado = importar_citas(
            db, registros, id_usuario=por_rol["ADMINISTRADOR"].id_usuario, ip="127.0.0.1",
            origen=f"seed sintético (semilla {args.semilla})",
        )
        print(f"Importación: {resultado.recibidas} recibidas, {resultado.aceptadas} aceptadas, "
              f"{resultado.rechazadas} rechazadas")
        for r in resultado.detalle_rechazos:
            print(f"  fila {r.fila} [{r.id_cita_externa}]: {'; '.join(r.motivos)}")


if __name__ == "__main__":
    main()