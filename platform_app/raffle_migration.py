"""Migracion idempotente de fotografia e informacion ampliada."""

import sqlite3

TARGET_VERSION = "2.4.0"

COLUMNS = {
    "image_filename": "TEXT",
    "extended_info": "TEXT",
}


def migrate_raffles(connection, update_version=False):
    """Actualiza una base de entidad sin eliminar datos.

    La conexion debe estar fuera de una transaccion activa.
    No cierra la conexion recibida.
    """
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError("Se requiere una conexion SQLite")

    if connection.in_transaction:
        raise RuntimeError(
            "La conexion ya tiene una transaccion activa"
        )

    try:
        connection.execute("BEGIN IMMEDIATE")

        exists = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='raffles'"
        ).fetchone()

        if not exists:
            raise RuntimeError(
                "No existe la tabla raffles"
            )

        current = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(raffles)"
            )
        }

        added = []

        for column, column_type in COLUMNS.items():
            if column not in current:
                connection.execute(
                    "ALTER TABLE raffles ADD COLUMN "
                    + column + " " + column_type
                )
                added.append(column)

        if update_version:
            version_table = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' "
                "AND name='module_versions'"
            ).fetchone()

            if not version_table:
                raise RuntimeError(
                    "No existe module_versions"
                )

            connection.execute(
                "INSERT INTO module_versions "
                "(module,version,updated_at) "
                "VALUES ('sorteos', ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(module) DO UPDATE SET "
                "version=excluded.version, "
                "updated_at=excluded.updated_at",
                (TARGET_VERSION,)
            )

        connection.commit()
        return {
            "added": added,
            "version_updated": bool(update_version),
        }

    except BaseException:
        connection.rollback()
        raise
