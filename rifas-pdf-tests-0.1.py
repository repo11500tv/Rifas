#!/usr/bin/env python3
"""Pruebas aisladas del generador PDF de Rifas Benéficas 2.x."""

import argparse
import importlib
import os
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path

from werkzeug.exceptions import HTTPException


def create_db(path, slug, outcome):
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE raffles (
      id INTEGER PRIMARY KEY, title TEXT, prizes TEXT, draw_at TEXT,
      donation_cents INTEGER, number_start INTEGER, number_end INTEGER,
      number_width INTEGER, status TEXT
    );
    CREATE TABLE raffle_draw_rules (
      id INTEGER PRIMARY KEY, raffle_id INTEGER,
      external_organizer TEXT, external_draw TEXT, rule_description TEXT
    );
    CREATE TABLE raffle_draw_results (
      id INTEGER PRIMARY KEY, raffle_id INTEGER, outcome TEXT,
      winning_number INTEGER, winning_participant_id INTEGER,
      recorded_by INTEGER, official_result TEXT, official_source TEXT,
      official_draw_at TEXT, recorded_at TEXT
    );
    CREATE TABLE participants (id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE prize_deliveries (
      id INTEGER PRIMARY KEY, draw_result_id INTEGER,
      notification_status TEXT, delivery_status TEXT,
      delivered_at TEXT, delivery_notes TEXT
    );
    CREATE TABLE entity_admins (id INTEGER PRIMARY KEY, username TEXT);
    CREATE TABLE raffle_purchases (
      id INTEGER PRIMARY KEY, raffle_id INTEGER,
      quantity INTEGER, total_cents INTEGER
    );
    """)
    con.execute(
        "INSERT INTO raffles VALUES (1,?,?,?,?,?,?,?,?)",
        (f"Sorteo {slug}", "Premio de prueba", "2026-11-16",
         500, 0, 99, 2, "finished")
    )
    con.execute(
        "INSERT INTO raffle_draw_rules VALUES (1,1,?,?,?)",
        ("Organismo de prueba", "Sorteo externo", "Últimas dos cifras")
    )
    participant = 11 if outcome == "winner" else None
    con.execute("""
        INSERT INTO raffle_draw_results VALUES
        (1,1,?,42,?,7,'Resultado oficial 42',
         'https://example.invalid/resultado',
         '2026-11-16','2026-11-16 18:00:00')
    """, (outcome, participant))
    if participant:
        con.execute(
            "INSERT INTO participants VALUES (11,?)",
            (f"Ganador {slug}",)
        )
        con.execute(
            "INSERT INTO prize_deliveries VALUES "
            "(1,1,'notified','pending',NULL,'Entrega pendiente')"
        )
    con.execute(
        "INSERT INTO entity_admins VALUES (7,?)",
        (f"admin_{slug}",)
    )
    con.execute(
        "INSERT INTO raffle_purchases VALUES (1,1,2,1000)"
    )
    con.commit()
    con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    if not (source / "raffle_acta_pdf.py").is_file():
        parser.error("No se encuentra raffle_acta_pdf.py")
    if not (source / "__init__.py").is_file():
        parser.error("El directorio no parece platform_app")

    sys.path.insert(0, str(source.parent))
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    cases = 0
    errors = 0

    def check(label, condition):
        nonlocal cases, errors
        cases += 1
        if not condition:
            errors += 1
        print(("OK" if condition else "ERROR") + " | " + label)

    try:
        import platform_app
        module = importlib.import_module(
            "platform_app.raffle_acta_pdf"
        )
        check("Importación del generador PDF",
              callable(module._read_data)
              and callable(module._render_pdf))
    except Exception:
        traceback.print_exc()
        print("ERROR | Importación del módulo")
        return 1

    from flask import Flask

    app = Flask("rifas_pdf_tests")

    with tempfile.TemporaryDirectory(
        prefix="rifas-pdf-tests-"
    ) as temp:

        base = Path(temp) / "entidades"
        base.mkdir()
        paths = {}

        for slug, outcome in (
            ("entidada", "winner"),
            ("entidadb", "void")
        ):
            directory = base / slug / "data"
            directory.mkdir(parents=True)
            path = directory / "rifas.sqlite3"
            create_db(path, slug, outcome)
            paths[slug] = path

        platform_app.ENTITIES = base

        entities = {
            "entidada": {
                "id": 1, "slug": "entidada",
                "name": "Entidad A", "public_name": "Entidad A",
                "status": "active"
            },
            "entidadb": {
                "id": 2, "slug": "entidadb",
                "name": "Entidad B", "public_name": "Entidad B",
                "status": "active"
            },
            "suspendida": {
                "id": 3, "slug": "suspendida",
                "name": "Suspendida", "status": "inactive"
            }
        }

        def fake_get_entity(slug):
            if slug not in entities:
                from flask import abort
                abort(404)
            return entities[slug]

        module.get_entity = fake_get_entity

        try:
            data_a = module._read_data("entidada", 1)
            data_b = module._read_data("entidadb", 1)

            check("Lectura aislada entidad A",
                  data_a[0]["slug"] == "entidada"
                  and data_a[1]["title"] == "Sorteo entidada")

            check("Lectura aislada entidad B",
                  data_b[0]["slug"] == "entidadb"
                  and data_b[1]["title"] == "Sorteo entidadb")

            check("Mismo ID sin cruce de entidades",
                  data_a[1]["id"] == data_b[1]["id"] == 1
                  and data_a[6]["username"] == "admin_entidada"
                  and data_b[6]["username"] == "admin_entidadb")

        except Exception:
            traceback.print_exc()
            data_a = data_b = None
            check("Lectura y aislamiento", False)

        with app.test_request_context("/"):
            try:
                module._read_data("no_existe", 1)
                check("Entidad inexistente HTTP 404", False)
            except HTTPException as exc:
                check("Entidad inexistente HTTP 404",
                      exc.code == 404)

            try:
                module._read_data("suspendida", 1)
                check("Entidad suspendida HTTP 403", False)
            except HTTPException as exc:
                check("Entidad suspendida HTTP 403",
                      exc.code == 403)

        try:
            con = sqlite3.connect(paths["entidadb"])
            con.execute(
                "UPDATE raffles SET status='closed' WHERE id=1"
            )
            con.commit()
            con.close()

            with app.test_request_context("/"):
                try:
                    module._read_data("entidadb", 1)
                    check("Sorteo no finalizado HTTP 409", False)
                except HTTPException as exc:
                    check("Sorteo no finalizado HTTP 409",
                          exc.code == 409)

            paths["entidadb"].unlink()
            create_db(paths["entidadb"], "entidadb", "void")

        except Exception:
            traceback.print_exc()
            check("Rechazo de sorteo no finalizado", False)

        if data_a is not None and data_b is not None:
            try:
                pdf = module._render_pdf(data_a).getvalue()
                check("PDF con ganador",
                      pdf.startswith(b"%PDF-")
                      and pdf.rstrip().endswith(b"%%EOF")
                      and len(pdf) > 1000)
            except Exception:
                traceback.print_exc()
                check("PDF con ganador", False)

            try:
                data_void = module._read_data("entidadb", 1)
                pdf = module._render_pdf(data_void).getvalue()

                check("PDF con premio desierto",
                      data_void[3]["outcome"] == "void"
                      and data_void[4] is None
                      and pdf.startswith(b"%PDF-")
                      and pdf.rstrip().endswith(b"%%EOF")
                      and len(pdf) > 1000)
            except Exception:
                traceback.print_exc()
                check("PDF con premio desierto", False)

        try:
            results = {}
            for slug, path in paths.items():
                con = sqlite3.connect(
                    f"file:{path}?mode=ro", uri=True
                )
                results[slug] = (
                    con.execute(
                        "SELECT COUNT(*) FROM raffles"
                    ).fetchone()[0],
                    con.execute(
                        "SELECT COUNT(*) FROM raffle_purchases"
                    ).fetchone()[0],
                    con.execute(
                        "SELECT SUM(total_cents) FROM raffle_purchases"
                    ).fetchone()[0]
                )
                con.close()

            check("Bases sin modificaciones",
                  results["entidada"] == (1, 1, 1000)
                  and results["entidadb"] == (1, 1, 1000))

        except Exception:
            traceback.print_exc()
            check("Integridad de bases", False)

    print(f"RESUMEN PDF: {cases} comprobaciones; {errors} errores")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
