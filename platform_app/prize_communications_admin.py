"""Registro manual de comunicaciones con ganadores."""

import html

from flask import (
    Blueprint, abort, flash, redirect,
    request, session, url_for
)

from platform_app.entity_routes import (
    edb, layout, protected, token
)

bp = Blueprint(
    "prize_communications_admin",
    __name__,
    url_prefix="/e/<slug>/administracion/premios"
)

METHODS = {
    "phone": "Telefono",
    "whatsapp": "WhatsApp",
    "email": "Correo electronico",
    "in_person": "Presencial",
    "other": "Otro medio",
}

STATUSES = {
    "completed": "Comunicacion realizada",
    "attempted": "Intento sin contacto",
    "sent": "Mensaje enviado",
    "failed": "Envio fallido",
}


def esc(value):
    return html.escape(
        str(value if value is not None else ""),
        quote=True
    )


@bp.route("/<int:result_id>/comunicaciones", methods=["GET", "POST"])
@protected
def communications(slug, result_id):
    with edb(slug) as db:
        prize = db.execute("""
            SELECT d.id, d.outcome, d.winning_number,
                   r.title AS raffle_title,
                   p.name AS participant_name,
                   p.email AS participant_email
            FROM raffle_draw_results d
            JOIN raffles r ON r.id=d.raffle_id
            LEFT JOIN participants p
                ON p.id=d.winning_participant_id
            WHERE d.id=?
        """, (result_id,)).fetchone()

        if prize is None:
            abort(404)

        if prize["outcome"] != "winner":
            abort(403)

        if request.method == "POST":
            method = request.form.get("communication_type", "")
            status = request.form.get("status", "")
            direction = request.form.get("direction", "outgoing")
            notes = request.form.get("notes", "").strip()

            if (
                method not in METHODS
                or status not in STATUSES
                or direction not in ("outgoing", "incoming")
                or not notes
                or len(notes) > 1000
            ):
                flash("Revise los datos de la comunicacion.")
            else:
                admin_id = session.get("entity_user_id")

                db.execute("""
                    INSERT INTO prize_communications(
                        draw_result_id,
                        communication_type,
                        direction,
                        status,
                        notes,
                        recorded_by
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    result_id, method, direction,
                    status, notes, admin_id
                ))

                if status in ("completed", "sent"):
                    db.execute("""
                        UPDATE prize_deliveries
                        SET notification_status='notified',
                            notified_at=COALESCE(
                                notified_at, CURRENT_TIMESTAMP
                            ),
                            updated_at=CURRENT_TIMESTAMP
                        WHERE draw_result_id=?
                    """, (result_id,))

                db.commit()
                flash("Comunicacion registrada correctamente.")

                return redirect(url_for(
                    "prize_communications_admin.communications",
                    slug=slug,
                    result_id=result_id
                ))

        history = db.execute("""
            SELECT c.*, a.username AS administrator
            FROM prize_communications c
            LEFT JOIN entity_admins a
                ON a.id=c.recorded_by
            WHERE c.draw_result_id=?
            ORDER BY c.id DESC
        """, (result_id,)).fetchall()

    options_method = "".join(
        '<option value="' + esc(key) + '">' +
        esc(label) + '</option>'
        for key, label in METHODS.items()
    )

    options_status = "".join(
        '<option value="' + esc(key) + '">' +
        esc(label) + '</option>'
        for key, label in STATUSES.items()
    )

    body = (
        '<div class="card">'
        '<h2>Registrar comunicacion</h2>'
        '<p><strong>Sorteo:</strong> ' +
        esc(prize["raffle_title"]) + '</p>'
        '<p><strong>Numero ganador:</strong> ' +
        esc(prize["winning_number"]) + '</p>'
        '<p><strong>Ganador:</strong> ' +
        esc(prize["participant_name"]) + '</p>'
        '<p><strong>Correo:</strong> ' +
        esc(prize["participant_email"]) + '</p>'
        '<form method="post">'
        '<input type="hidden" name="_csrf" value="' +
        esc(token()) + '">'
        '<label>Medio de comunicacion</label>'
        '<select name="communication_type" required>' +
        options_method + '</select>'
        '<p><label>Direccion</label>'
        '<select name="direction">'
        '<option value="outgoing">Saliente</option>'
        '<option value="incoming">Entrante</option>'
        '</select></p>'
        '<p><label>Resultado</label>'
        '<select name="status" required>' +
        options_status + '</select></p>'
        '<p><label>Observaciones</label>'
        '<textarea name="notes" maxlength="1000" '
        'rows="4" required '
        'style="width:100%;box-sizing:border-box"></textarea></p>'
        '<button type="submit">Guardar comunicacion</button>'
        '</form></div>'
        '<div class="card"><h2>Historial de comunicaciones</h2>'
    )

    if not history:
        body += '<p>No hay comunicaciones registradas.</p>'

    for item in history:
        body += (
            '<hr>'
            '<p><strong>Fecha:</strong> ' +
            esc(item["created_at"]) + '</p>'
            '<p><strong>Medio:</strong> ' +
            esc(METHODS.get(
                item["communication_type"], "Otro"
            )) + '</p>'
            '<p><strong>Resultado:</strong> ' +
            esc(STATUSES.get(
                item["status"], "Desconocido"
            )) + '</p>'
            '<p><strong>Observaciones:</strong> ' +
            esc(item["notes"]) + '</p>'
            '<p><strong>Administrador:</strong> ' +
            esc(item["administrator"]) + '</p>'
        )

    body += '</div>'

    return layout("Comunicaciones del premio", body)
