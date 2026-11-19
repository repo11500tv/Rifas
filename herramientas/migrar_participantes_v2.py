"""Ensayo seguro de migracion de participantes a V2."""

import argparse
import sqlite3
from pathlib import Path

from platform_app.participant_schema_transition import (
    SCHEMA_PARTICIPANTS_TRANSITION
)
from platform_app.participant_ip_limits import SCHEMA_IP_LIMITS
from platform_app.participant_account_limits import SCHEMA_ACCOUNT_LIMITS
from platform_app.participant_delivery_status import SCHEMA_DELIVERY_STATUS


TABLAS_CONSERVADAS = (
    "entity_admins",
    "entity_settings",
    "raffles",
    "metadata",
    "module_versions",
    "credit_movements",
    "participant_closure_requests",
)


def ejecutar_sql_individual(con, script):
    """Ejecuta SQL sin commits implicitos de executescript."""
    pendiente = ""

    for linea in script.splitlines():
        pendiente += linea + "\n"

        if sqlite3.complete_statement(pendiente):
            sentencia = pendiente.strip()

            if sentencia:
                con.execute(sentencia)

            pendiente = ""

    if pendiente.strip():
        raise RuntimeError("Sentencia SQL incompleta")


def registros(con, tabla):
    return con.execute(
        f'SELECT * FROM "{tabla}" ORDER BY rowid'
    ).fetchall()



def verificar_origen(con):
    """Rechaza esquemas incompatibles o ya migrados."""

    tablas = {
        fila[0]
        for fila in con.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table'"
        )
    }

    necesarias = {
        "participants",
        "password_reset_tokens",
        "credit_movements",
        "participant_closure_requests",
        "entity_admins",
        "entity_settings",
        "raffles",
        "metadata",
        "module_versions",
    }

    faltantes = necesarias - tablas

    if faltantes:
        raise RuntimeError(
            "Faltan tablas: " + ", ".join(sorted(faltantes))
        )

    columnas = {
        fila[1]
        for fila in con.execute(
            "PRAGMA table_info(participants)"
        )
    }

    antiguas = {
        "id",
        "name",
        "email",
        "password_hash",
        "active",
        "created_at",
    }

    if columnas != antiguas:
        raise RuntimeError(
            "Esquema de participantes incompatible "
            "o previamente migrado"
        )

    if "participant_codes" in tablas:
        raise RuntimeError(
            "Ya existe el sistema nuevo de codigos"
        )

    integridad = con.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0]

    relaciones = con.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()

    if integridad != "ok" or relaciones:
        raise RuntimeError(
            "La base de datos de origen no es integra"
        )

    return True


def migrar(con):
    """Migra una conexion SQLite dentro de una transaccion."""

    verificar_origen(con)

    con.execute("PRAGMA foreign_keys=OFF")

    originales = {
        tabla: registros(con, tabla)
        for tabla in TABLAS_CONSERVADAS
    }

    participantes = con.execute(
        "SELECT id,name,email,active,created_at "
        "FROM participants ORDER BY id"
    ).fetchall()

    tokens_antiguos = con.execute(
        "SELECT COUNT(*) FROM password_reset_tokens"
    ).fetchone()[0]

    try:
        con.execute("BEGIN IMMEDIATE")

        for tabla in (
            "password_reset_tokens",
            "participant_closure_requests",
            "credit_movements",
            "participants",
        ):
            con.execute(f'DROP TABLE "{tabla}"')

        for esquema in (
            SCHEMA_PARTICIPANTS_TRANSITION,
            SCHEMA_IP_LIMITS,
            SCHEMA_ACCOUNT_LIMITS,
            SCHEMA_DELIVERY_STATUS,
        ):
            ejecutar_sql_individual(con, esquema)

        for p in participantes:
            con.execute(
                "INSERT INTO participants "
                "(id,name,email,phone,legacy_pending,"
                "email_verified,phone_verified,active,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    p[0], p[1], p[2],
                    None, 1, 0, 0, p[3], p[4]
                )
            )

        for tabla in (
            "credit_movements",
            "participant_closure_requests",
        ):
            for fila in originales[tabla]:
                marcadores = ",".join("?" for _ in fila)

                con.execute(
                    f'INSERT INTO "{tabla}" '
                    f'VALUES({marcadores})',
                    fila
                )

        for tabla in TABLAS_CONSERVADAS:
            if registros(con, tabla) != originales[tabla]:
                raise RuntimeError(
                    "Datos modificados en " + tabla
                )

        actuales = con.execute(
            "SELECT id,name,email,active,created_at "
            "FROM participants ORDER BY id"
        ).fetchall()

        if actuales != participantes:
            raise RuntimeError(
                "Datos originales de participantes modificados"
            )

        pendientes = con.execute(
            "SELECT COUNT(*) FROM participants "
            "WHERE legacy_pending=1 "
            "AND phone IS NULL "
            "AND email_verified=0"
        ).fetchone()[0]

        if pendientes != len(participantes):
            raise RuntimeError(
                "Cuentas heredadas incorrectas"
            )

        integridad = con.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        relaciones = con.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if integridad != "ok" or relaciones:
            raise RuntimeError(
                "Error de integridad o relaciones"
            )

        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.execute("PRAGMA foreign_keys=ON")

    return {
        "participantes": len(participantes),
        "pendientes": pendientes,
        "tokens_retirados": tokens_antiguos,
        "integridad": integridad,
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--origen",
        required=True,
        help="Copia SQLite de origen"
    )

    args = parser.parse_args()

    origen = Path(args.origen).resolve()

    if not origen.is_file():
        raise SystemExit("ERROR: origen no encontrado")

    print("===== ENSAYO DE MIGRACION V2 =====")
    print("ORIGEN:", origen)
    print("DESTINO: MEMORIA")

    fuente = sqlite3.connect(
        origen.as_uri() + "?mode=ro",
        uri=True
    )

    destino = sqlite3.connect(":memory:")

    try:
        fuente.backup(destino)

        resultado = migrar(destino)

        print()
        print("RESULTADOS")

        for clave, valor in resultado.items():
            print(clave + ":", valor)

        print()
        print("ENSAYO COMPLETADO CORRECTAMENTE")
        print("BASE DE DATOS ORIGINAL SIN MODIFICAR")
        print("NINGUN ARCHIVO DE DATOS MODIFICADO")

    finally:
        fuente.close()
        destino.close()


if __name__ == "__main__":
    main()
