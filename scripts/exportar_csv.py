"""Genera data/citas_demo.csv con citas próximas y filas inválidas a propósito.

Uso: python -m scripts.exportar_csv [--filas 20] [--semilla 7]
"""
import argparse
import csv
from pathlib import Path

from app.modules.citas.synthetic import generar_citas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filas", type=int, default=20)
    parser.add_argument("--semilla", type=int, default=7)
    args = parser.parse_args()

    registros = generar_citas(historicas=0, proximas=args.filas, semilla=args.semilla, prefijo="DEMO")
    destino = Path("data") / "citas_demo.csv"
    with destino.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(registros[0]))
        escritor.writeheader()
        escritor.writerows(registros)
    print(f"{len(registros)} filas escritas en {destino}")


if __name__ == "__main__":
    main()