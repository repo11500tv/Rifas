"""Administracion de creditos por entidad."""

import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
from html import escape

from flask import (
    Blueprint, abort, flash, redirect,
    request, session, url_for
)

from platform_app.entity_routes import (
    edb, get_entity, layout, token, protected
)

bp = Blueprint(
    "participant_credits_admin",
    __name__,
    url_prefix="/e/<slug>/creditos"
)


def euros_to_cents(value):
    try:
        amount = Decimal(value.replace(",", "."))
        if not amount.is_finite():
            raise ValueError()
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise ValueError()
        cents = int(cents)
        if cents <= 0 or cents > 100000000:
            raise ValueError()
        return cents
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError("Importe no valido")


def money(cents):
    return f"{cents / 100:.2f}"


@bp.route("/", methods=["GET", "POST"])
@protected
def manage(slug):
    entity = get_entity(slug)

    if not entity or entity["status"] != "active":
        abort(404)

    message = ""

    if request.method == "POST":
        participant_id = request.form.get(
            "participant_id", ""
        )
        operation = request.form.get(
            "operation", ""
        )
        amount = request.form.get("amount", "")
        notes = request.form.get("notes", "").strip()
        operation_id = request.form.get("operation_id", "").strip()
        admin_id = session.get("entity_user_id")
        admin_name = session.get("entity_user", "")

        try:
            pid = int(participant_id)
            if pid <= 0:
                raise ValueError()

            cents = euros_to_cents(amount)

            if operation not in ("recarga", "ajuste"):
                raise ValueError("Operacion no valida")

            if not notes or len(notes) > 500:
                raise ValueError(
                    "Indica un concepto de hasta 500 caracteres"
                )

            if operation == "ajuste":
                cents = -cents
                movement_type = "adjustment"
            else:
                movement_type = "topup"

            if not operation_id or len(operation_id) != 32:
                raise ValueError("Identificador de operacion no valido")

            if not all(c in "0123456789abcdef" for c in operation_id):
                raise ValueError("Identificador de operacion no valido")

            reference = "ADMIN-" + operation_id

            with edb(slug) as con:
                con.execute("BEGIN IMMEDIATE")

                participant = con.execute(
                    "SELECT id FROM participants "
                    "WHERE id=? AND active=1",
                    (pid,)
                ).fetchone()

                if participant is None:
                    raise ValueError(
                        "Participante no disponible"
                    )

                balance = con.execute(
                    "SELECT COALESCE(SUM(amount_cents),0) "
                    "FROM credit_movements "
                    "WHERE participant_id=?",
                    (pid,)
                ).fetchone()[0]

                if balance + cents < 0:
                    raise ValueError(
                        "Saldo insuficiente para el ajuste"
                    )

                existing = con.execute(
                    "SELECT id FROM credit_movements "
                    "WHERE reference=?",
                    (reference,)
                ).fetchone()

                if existing:
                    raise ValueError(
                        "Esta operacion ya fue registrada. "
                        "No se ha realizado ningun cargo adicional."
                    )

                audit_notes = (
                    notes +
                    " | Administrador: " +
                    str(admin_name) +
                    " (ID " + str(admin_id) + ")"
                )

                con.execute(
                    "INSERT INTO credit_movements "
                    "(participant_id,amount_cents,"
                    "movement_type,reference,notes) "
                    "VALUES (?,?,?,?,?)",
                    (
                        pid, cents, movement_type,
                        reference, audit_notes
                    )
                )

                con.commit()

            message = "Operacion registrada correctamente"

        except (ValueError, TypeError) as exc:
            message = str(exc)
        except sqlite3.Error:
            message = "No se pudo registrar la operacion"

    with edb(slug) as con:
        participants = con.execute(
            "SELECT p.id,p.name,p.email,"
            "COALESCE(SUM(m.amount_cents),0) balance "
            "FROM participants p "
            "LEFT JOIN credit_movements m "
            "ON m.participant_id=p.id "
            "WHERE p.active=1 "
            "GROUP BY p.id "
            "ORDER BY p.name"
        ).fetchall()

        movements = con.execute(
            "SELECT m.created_at,p.name,"
            "m.movement_type,m.amount_cents,"
            "m.reference,m.notes "
            "FROM credit_movements m "
            "JOIN participants p "
            "ON p.id=m.participant_id "
            "ORDER BY m.id DESC LIMIT 50"
        ).fetchall()

    options = "".join(
        '<option value="' + str(p["id"]) + '">' +
        escape(p["name"]) + " - " +
        escape(p["email"]) +
        " (saldo: " + money(p["balance"]) + ")" +
        "</option>"
        for p in participants
    )

    rows = "".join(
        "<tr><td>" + escape(str(m["created_at"])) +
        "</td><td>" + escape(m["name"]) +
        "</td><td>" + escape(m["movement_type"]) +
        "</td><td>" + money(m["amount_cents"]) +
        "</td><td>" + escape(m["reference"]) +
        "</td><td>" + escape(m["notes"] or "") +
        "</td></tr>"
        for m in movements
    )

    new_operation_id = uuid.uuid4().hex

    body = (
        '<div class="card">'
        '<h2>Gestion de creditos</h2>'
        '<p>' + escape(message) + '</p>'
        '<form method="post">'
        '<input type="hidden" name="operation_id" value="' +
        new_operation_id + '">'
        '<input type="hidden" name="_csrf" value="' +
        escape(str(token()), quote=True) + '">'
        '<label>Participante</label>'
        '<select name="participant_id" required>' +
        options + '</select>'
        '<label>Operacion</label>'
        '<select name="operation">'
        '<option value="recarga">Recarga de creditos</option>'
        '<option value="ajuste">Descontar creditos</option>'
        '</select>'
        '<label>Importe en euros</label>'
        '<input name="amount" type="text" '
        'placeholder="10,00" required>'
        '<label>Concepto</label>'
        '<input name="notes" maxlength="500" required>'
        '<button type="submit">Registrar operacion</button>'
        '</form>'
        '<h3>Ultimos movimientos</h3>'
        '<table><tr><th>Fecha</th>'
        '<th>Participante</th><th>Operacion</th>'
        '<th>Euros</th><th>Referencia</th>'
        '<th>Concepto y responsable</th></tr>' +
        rows + '</table>'
        '</div>'
    )

    return layout(
        "Creditos - " + entity["name"],
        body
    )
