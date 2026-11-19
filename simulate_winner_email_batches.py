import argparse
import sqlite3
from pathlib import Path

from platform_app.winner_email_batch_dispatcher import (
    process_winner_notifications,
)


def main():
    parser = argparse.ArgumentParser(
        description="Simulacion de notificaciones de premios"
    )

    parser.add_argument(
        "--entity",
        default="pruebas",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )

    args = parser.parse_args()

    # Seguridad: solo se permite la entidad de pruebas.
    if args.entity != "pruebas":
        raise SystemExit(
            "BLOQUEADO: solo se permite la entidad pruebas"
        )

    database = (
        Path(__file__).resolve().parent
        / "entidades"
        / args.entity
        / "data"
        / "rifas.sqlite3"
    )

    if not database.is_file():
        raise SystemExit("Base de datos no encontrada")

    with sqlite3.connect(
        f"file:{database}?mode=ro",
        uri=True
    ) as db:
        db.row_factory = sqlite3.Row

        result = process_winner_notifications(
            db,
            limit=args.limit,
            dry_run=True,
        )

    print("===== SIMULACION DE NOTIFICACIONES =====")
    print("Entidad:", args.entity)
    print("Notificaciones procesadas:", result["processed"])
    print("Simulaciones:", result["simulated"])
    print("SMTP enviado:", result["smtp_sent"])
    print("Datos modificados: NO")


if __name__ == "__main__":
    main()
