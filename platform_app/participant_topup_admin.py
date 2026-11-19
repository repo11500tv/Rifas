"""Administracion de solicitudes de recarga."""

from html import escape
import sqlite3

from flask import (
    Blueprint, abort, request, redirect,
    session, url_for
)

from platform_app.entity_routes import (
    edb, get_entity, layout, protected, token
)

bp = Blueprint(
    "participant_topup_admin",
    __name__,
    url_prefix="/e/<slug>/administracion/recargas"
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


@bp.get("/")
@protected
def manage(slug):
    entity = get_entity(slug)

    if entity["status"] != "active":
        abort(403)

    with edb(slug) as con:
        requests = con.execute(
            "SELECT r.id,r.amount_cents,"
            "r.payment_method,r.status,"
            "r.payment_reference,"
            "r.participant_notes,"
            "r.admin_notes,r.created_at,"
            "r.reviewed_at,"
            "p.name,p.email "
            "FROM topup_requests r "
            "JOIN participants p "
            "ON p.id=r.participant_id "
            "ORDER BY "
            "CASE WHEN r.status='pending' "
            "THEN 0 ELSE 1 END,"
            "r.id DESC LIMIT 200"
        ).fetchall()

    pending = sum(
        1 for r in requests
        if r["status"] == "pending"
    )

    rows = []

    for r in requests:
        actions = ""

        if r["status"] == "pending":
            action_url = escape(
                url_for(
                    "participant_topup_admin.resolve",
                    slug=slug,
                    request_id=r["id"]
                ),
                quote=True
            )

            actions = (
                '<form method="post" action="' +
                action_url + '">'
                '<input type="hidden" name="_csrf" value="' +
                escape(str(token()), quote=True) + '">'
                '<p><label>Observaciones del administrador'
                '<br><input name="admin_notes" maxlength="500" '
                'style="width:100%" '
                'placeholder="Motivo o referencia del cobro">'
                '</label></p>'
                '<p><label>'
                '<input type="checkbox" name="payment_confirmed" '
                'value="yes"> Confirmo que hemos recibido '
                'el importe</label></p>'
                '<button type="submit" name="decision" '
                'value="approve">Aprobar y abonar</button> '
                '<button type="submit" name="decision" '
                'value="reject">Rechazar</button>'
                '</form>'
            )
        else:
            actions = escape(
                str(r["admin_notes"] or "")
            )
            if r["reviewed_at"]:
                actions += "<br><small>" + escape(
                    str(r["reviewed_at"])
                ) + "</small>"

        rows.append(
            "<tr>"
            "<td>" + str(r["id"]) + "</td>"
            "<td>" + escape(str(r["created_at"])) +
            "</td>"
            "<td>" + escape(str(r["name"])) +
            "<br><small>" +
            escape(str(r["email"])) +
            "</small></td>"
            "<td>" +
            f'{r["amount_cents"]/100:.2f} €' +
            "</td>"
            "<td>" +
            escape(METHODS[r["payment_method"]]) +
            "</td>"
            "<td>" +
            escape(str(r["payment_reference"])) +
            "</td>"
            "<td>" +
            escape(str(r["participant_notes"])) +
            "</td>"
            "<td><strong>" +
            escape(STATES[r["status"]]) +
            "</strong></td>"
            "<td>" + actions + "</td>"
            "</tr>"
        )

    body = (
        '<div class="card">'
        '<h2>Solicitudes de recarga</h2>'
        '<p>Solicitudes pendientes: '
        '<strong>' + str(pending) + '</strong></p>'
        '<p>Las solicitudes pendientes '
        'no aumentan el saldo del participante.</p>'
        '<p>Para aprobar, comprueba previamente '
        'el ingreso real del dinero.</p>'
        '<div style="overflow-x:auto">'
        '<table>'
        '<tr>'
        '<th>N.</th><th>Fecha</th>'
        '<th>Participante</th>'
        '<th>Importe</th>'
        '<th>Metodo</th>'
        '<th>Referencia</th>'
        '<th>Comentario</th>'
        '<th>Estado</th>'
        '<th>Resolucion</th>'
        '</tr>' +
        "".join(rows) +
        '</table></div>'
        '</div>'
    )

    return layout(
        "Administracion de recargas - " +
        entity["name"],
        body
    )


@bp.post("/<int:request_id>/resolver")
@protected
def resolve(slug, request_id):
    entity = get_entity(slug)

    if entity["status"] != "active":
        abort(403)

    decision = request.form.get("decision", "")
    notes = request.form.get("admin_notes", "").strip()

    if decision not in ("approve", "reject"):
        abort(400)

    if len(notes) > 500:
        abort(400)

    if decision == "approve":
        if request.form.get("payment_confirmed") != "yes":
            return layout(
                "Confirmacion necesaria",
                '<div class="card"><h2>Falta confirmar el cobro'
                '</h2><p>No se ha abonado ningun credito.</p>'
                '</div>'
            ), 400

    if decision == "reject" and not notes:
        return layout(
            "Motivo obligatorio",
            '<div class="card"><h2>Indica el motivo '
            'del rechazo</h2><p>No se ha modificado '
            'la solicitud.</p></div>'
        ), 400

    admin_id = session.get("entity_user_id")

    if not isinstance(admin_id, int):
        abort(403)

    with edb(slug) as con:
        try:
            con.execute("BEGIN IMMEDIATE")

            admin = con.execute(
                "SELECT id,username FROM entity_admins "
                "WHERE id=? AND active=1",
                (admin_id,)
            ).fetchone()

            if not admin:
                abort(403)

            item = con.execute(
                "SELECT id,participant_id,amount_cents,"
                "payment_method,status "
                "FROM topup_requests WHERE id=?",
                (request_id,)
            ).fetchone()

            if not item:
                abort(404)

            if item["status"] != "pending":
                con.rollback()
                return layout(
                    "Solicitud ya resuelta",
                    '<div class="card"><h2>Solicitud ya '
                    'resuelta</h2><p>No se ha realizado '
                    'ninguna nueva operacion.</p></div>'
                ), 409

            if decision == "approve":
                reference = "TOPUP-" + str(request_id)

                cursor = con.execute(
                    "INSERT INTO credit_movements "
                    "(participant_id,amount_cents,"
                    "movement_type,reference,notes) "
                    "VALUES (?,?,'topup',?,?)",
                    (
                        item["participant_id"],
                        item["amount_cents"],
                        reference,
                        "Recarga aprobada. Metodo: " +
                        item["payment_method"] +
                        ". Administrador: " +
                        str(admin["username"]) +
                        ". " + notes
                    )
                )

                con.execute(
                    "UPDATE topup_requests SET "
                    "status='approved',"
                    "admin_notes=?,"
                    "reviewed_by=?,"
                    "reviewed_at=CURRENT_TIMESTAMP,"
                    "credit_movement_id=? "
                    "WHERE id=? AND status='pending'",
                    (
                        notes, admin_id,
                        cursor.lastrowid, request_id
                    )
                )
            else:
                con.execute(
                    "UPDATE topup_requests SET "
                    "status='rejected',"
                    "admin_notes=?,"
                    "reviewed_by=?,"
                    "reviewed_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND status='pending'",
                    (notes, admin_id, request_id)
                )

            con.commit()

        except sqlite3.Error:
            con.rollback()
            raise

    return redirect(
        url_for("participant_topup_admin.manage", slug=slug)
    )
