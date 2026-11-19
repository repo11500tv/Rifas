"""Solicitudes de recarga de participantes."""

from decimal import Decimal, InvalidOperation
from html import escape

from flask import (
    Blueprint, abort, redirect, request,
    session, url_for
)

from platform_app.entity_routes import (
    edb, get_entity, layout, token
)
from platform_app.participant_account_access_v2 import (
    participant_can_access
)

bp = Blueprint(
    "participant_topup_requests",
    __name__,
    url_prefix="/e/<slug>/participantes/recargas"
)

METHODS = {
    "transfer": "Transferencia bancaria",
    "bizum": "Bizum",
    "cash": "Efectivo presencial",
}

STATES = {
    "pending": "Pendiente",
    "approved": "Aprobada",
    "rejected": "Rechazada",
}


def parse_amount(value):
    try:
        amount = Decimal(value.replace(",", "."))
        cents = amount * 100
        if not amount.is_finite():
            raise ValueError()
        if cents != cents.to_integral_value():
            raise ValueError()
        cents = int(cents)
        if cents < 100 or cents > 100000:
            raise ValueError()
        return cents
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError(
            "El importe debe estar entre 1 y 1.000 euros"
        )


@bp.route("/", methods=["GET", "POST"])
def requests_page(slug):
    entity = get_entity(slug)

    if entity is None or entity["status"] != "active":
        abort(404)

    if session.get("participant_slug") != slug:
        return redirect(
            url_for(
                "participant_access_v2.request_code",
                slug=slug
            )
        )

    participant_id = session.get("participant_id")

    with edb(slug) as con:
        if not participant_can_access(
            con, participant_id
        ):
            abort(403)

    message = ""

    if request.method == "POST":
        try:
            cents = parse_amount(
                request.form.get("amount", "")
            )

            method = request.form.get(
                "payment_method", ""
            )

            if method not in METHODS:
                raise ValueError(
                    "Metodo de pago no valido"
                )

            reference = request.form.get(
                "payment_reference", ""
            ).strip()

            notes = request.form.get(
                "notes", ""
            ).strip()

            if len(reference) > 150:
                raise ValueError(
                    "Referencia demasiado larga"
                )

            if len(notes) > 500:
                raise ValueError(
                    "Comentario demasiado largo"
                )

            with edb(slug) as con:
                con.execute(
                    "INSERT INTO topup_requests "
                    "(participant_id,amount_cents,"
                    "payment_method,payment_reference,"
                    "participant_notes) "
                    "VALUES (?,?,?,?,?)",
                    (
                        participant_id,
                        cents,
                        method,
                        reference,
                        notes
                    )
                )
                con.commit()

            message = (
                "Solicitud registrada. "
                "Los creditos se incorporaran "
                "cuando la hermandad confirme el pago."
            )

        except ValueError as exc:
            message = str(exc)

    with edb(slug) as con:
        requests = con.execute(
            "SELECT id,amount_cents,payment_method,"
            "status,created_at "
            "FROM topup_requests "
            "WHERE participant_id=? "
            "ORDER BY id DESC LIMIT 50",
            (participant_id,)
        ).fetchall()

    options = "".join(
        '<option value="' + key + '">' +
        escape(value) + '</option>'
        for key, value in METHODS.items()
    )

    rows = "".join(
        "<tr><td>" + str(r["id"]) +
        "</td><td>" +
        escape(str(r["created_at"])) +
        "</td><td>" +
        f'{r["amount_cents"]/100:.2f}' +
        "</td><td>" +
        escape(METHODS[r["payment_method"]]) +
        "</td><td>" +
        escape(STATES[r["status"]]) +
        "</td></tr>"
        for r in requests
    )

    body = (
        '<div class="card">'
        '<h2>Solicitar recarga de creditos</h2>'
        '<p>' + escape(message) + '</p>'
        '<form method="post">'
        '<input type="hidden" name="_csrf" value="' +
        escape(str(token()), quote=True) + '">'
        '<label>Importe en euros</label>'
        '<input name="amount" required '
        'placeholder="10,00">'
        '<label>Metodo de pago</label>'
        '<select name="payment_method">' +
        options + '</select>'
        '<label>Referencia del pago (opcional)</label>'
        '<input name="payment_reference" maxlength="150">'
        '<label>Comentario (opcional)</label>'
        '<textarea name="notes" maxlength="500"></textarea>'
        '<button type="submit">Enviar solicitud</button>'
        '</form>'
        '<p>La solicitud no supone la confirmacion '
        'del pago ni aumenta automaticamente el saldo.</p>'
        '<h3>Mis solicitudes</h3>'
        '<table><tr><th>N.</th><th>Fecha</th>'
        '<th>Euros</th><th>Metodo</th>'
        '<th>Estado</th></tr>' +
        rows + '</table>'
        '</div>'
    )

    return layout(
        "Recargas - " + entity["name"],
        body
    )
