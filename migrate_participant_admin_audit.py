"""Migracion controlada de auditoria administrativa de participantes."""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CENTRAL = ROOT / "central" / "plataforma.sqlite"
TEMPLATE = ROOT / "central" / "plantillas" / "entidad_maestra.sqlite3"
ENTITIES = ROOT / "entidades"

TABLE = "participant_admin_changes"


def connect_ro(path):
    return sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro",
        uri=True,
        timeout=20,
    )


def table_sql(con):
    row = con.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name=?",
        (TABLE,),
    ).fetchone()
    return row[0] if row else None


def verify(con, label):
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError(f"{label}: integridad incorrecta")

    if con.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError(f"{label}: relaciones incorrectas")


def backup_database(source, destination):
    with connect_ro(source) as original:
        with sqlite3.connect(destination) as copy:
            original.backup(copy)
            verify(copy, "Copia de seguridad")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplicar migracion con copia previa",
    )
    args = parser.parse_args()

    if not CENTRAL.is_file() or not TEMPLATE.is_file():
        raise RuntimeError("Falta la base central o la plantilla")

    with connect_ro(TEMPLATE) as template:
        verify(template, "Plantilla")
        expected = table_sql(template)

    if not expected:
        raise RuntimeError("La plantilla no contiene la tabla")

    with connect_ro(CENTRAL) as central:
        verify(central, "Central")
        slugs = [
            row[0] for row in central.execute(
                "SELECT slug FROM entities ORDER BY id"
            )
        ]

    pending = []

    for slug in slugs:
        path = ENTITIES / slug / "data" / "rifas.sqlite3"

        if not path.is_file():
            raise RuntimeError(f"{slug}: falta la base de datos")

        with connect_ro(path) as con:
            verify(con, slug)
            actual = table_sql(con)

        if actual is None:
            pending.append((slug, path))
            print(f"PENDIENTE | {slug}: falta {TABLE}")
        elif actual == expected:
            print(f"OK | {slug}: tabla correcta")
        else:
            raise RuntimeError(
                f"{slug}: estructura distinta de la plantilla"
            )

    if not args.apply:
        print(
            f"\nMODO LECTURA | Entidades pendientes: {len(pending)}"
        )
        print("No se ha modificado ninguna base de datos")
        return

    if not pending:
        print("\nNo hay migraciones pendientes")
        return

    stamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S_%f"
    )
    backup_dir = ROOT / "backups" / f"migracion_auditoria_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    print(f"\nCopias de seguridad: {backup_dir}")

    for slug, path in pending:
        backup_path = backup_dir / f"{slug}.sqlite3"

        backup_database(path, backup_path)
        print(f"BACKUP OK | {slug}")

        with sqlite3.connect(
            path.resolve().as_uri() + "?mode=rw",
            uri=True,
            timeout=20,
        ) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")

            if table_sql(con) is not None:
                raise RuntimeError(
                    f"{slug}: la tabla apareció durante la migración"
                )

            con.execute(expected)
            verify(con, slug)

            if table_sql(con) != expected:
                raise RuntimeError(
                    f"{slug}: estructura final incorrecta"
                )

            con.commit()

        print(f"MIGRADA | {slug}")

    print("\nMIGRACION FINALIZADA CORRECTAMENTE")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
