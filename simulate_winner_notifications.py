"""Ejecucion manual y segura de simulaciones de notificaciones."""

import argparse
import sqlite3
from pathlib import Path

from platform_app.winner_email_batch import simulate_winner_email_batch


def main():
    parser = argparse.ArgumentParser(
        description="Simular notificaciones pendientes sin enviar correos."
    )
    parser.add_argument(
        "--entidad",
        default="pruebas",
        choices=["pruebas"]
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=10
    )
    args = parser.parse_args()

    if not 1 <= args.limite <= 10:
        parser.error("El limite debe estar entre 1 y 10.")

    root = Path(__file__).resolve().parent
    database = (
        root / "entidades" / args.entidad /
        "data" / "rifas.sqlite3"
    ).resolve()

    if not database.is_file():
        parser.error("No se encuentra la base de datos.")

    print("===== SIMULACION DE NOTIFICACIONES =====")
    print("Entidad:", args.entidad)
    print("Limite:", args.limite)

    db = sqlite3.connect(
        database.as_uri() + "?mode=ro",
        uri=True
    )
    db.row_factory = sqlite3.Row

    try:
        summary = simulate_winner_email_batch(
            db,
            limit=args.limite
        )
    finally:
        db.close()

    print("Pendientes examinadas:", summary["total"])
    print("Simuladas:", summary["simulated"])
    print("Bloqueadas:", summary["blocked"])
    print("Errores:", summary["errors"])
    print("Correos SMTP enviados: 0")
    print("Base de datos modificada: NO")


if __name__ == "__main__":
    main()
