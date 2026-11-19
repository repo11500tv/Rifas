"""Registro definitivo de entrega de premios."""

import html
import sqlite3

from flask import (
    Blueprint, abort, flash, redirect,
    request, session, url_for
)

from platform_app.entity_routes import (
    edb, layout, protected, token
)

bp = Blueprint(
    "prize_delivery_admin",
    __name__,
    url_prefix="/e/<slug>/administracion/premios"
)


def esc(value):
    return html.escape(
        str(value if value is not None else ""),
        quote=True
    )


@bp.route("/<int:result_id>/entrega", methods=["GET", "POST"])
@protected
def delivery(slug, result_id):
    with edb(slug) as db:
        prize = db.execute("""
            SELECT
                d.id,
                d.outcome,
                d.winning_number,
                r.title AS raffle_title,
                p.name AS participant_name,
                pd.delivery_status,
                pd.delivered_at,
                pd.delivered_by,
                pd.delivery_notes,
                a.username AS delivery_admin
            FROM raffle_draw_results d
            JOIN raffles r ON r.id=d.raffle_id
            LEFT JOIN participants p
                ON p.id=d.winning_participant_id
            LEFT JOIN prize_deliveries pd
                ON pd.draw_result_id=d.id
            LEFT JOIN entity_admins a
                ON a.id=pd.delivered_by
            WHERE d.id=?
        """, (result_id,)).fetchone()

        if prize is None:
            abort(404)

        if prize["outcome"] != "winner":
            abort(403)

        if request.method == "POST":
            notes = request.form.get("delivery_notes", "").strip()
            confirmed = request.form.get("confirmed") == "yes"

            if not confirmed or not notes or len(notes) > 1000:
                flash(
                    "Debe confirmar la entrega e indicar "
                    "observaciones (maximo 1000 caracteres)."
                )
            else:
                try:
                    db.execute("BEGIN IMMEDIATE")

                    admin = db.execute("""
                        SELECT id FROM entity_admins
                        WHERE id=? AND username=? AND active=1
                    """, (
                        session.get("entity_user_id"),
                        session.get("entity_user")
                    )).fetchone()

                    if admin is None:
                        abort(403)

                    current = db.execute("""
                        SELECT delivery_status
                        FROM prize_deliveries
                        WHERE draw_result_id=?
                    """, (result_id,)).fetchone()

                    if current is None:
                        abort(404)

                    if current["delivery_status"] == "delivered":
                        db.rollback()
                        flash("Este premio ya consta como entregado.")
                    else:
                        db.execute("""
                            UPDATE prize_deliveries
                            SET delivery_status='delivered',
                                delivered_at=CURRENT_TIMESTAMP,
                                delivered_by=?,
                                delivery_notes=?,
                                updated_at=CURRENT_TIMESTAMP
                            WHERE draw_result_id=?
                              AND delivery_status='pending'
                        """, (
                            admin["id"], notes, result_id
                        ))
                        db.commit()
                        flash("Entrega registrada definitivamente.")

                    return redirect(url_for(
                        "prize_delivery_admin.delivery",
                        slug=slug,
                        result_id=result_id
                    ))

                except sqlite3.Error:
                    db.rollback()
                    raise

    with edb(slug) as db:
        prize = db.execute("""
            SELECT d.id, d.winning_number,
                   r.title AS raffle_title,
                   p.name AS participant_name,
                   pd.delivery_status,
                   pd.delivered_at,
                   pd.delivery_notes,
                   a.username AS delivery_admin
            FROM raffle_draw_results d
            JOIN raffles r ON r.id=d.raffle_id
            JOIN participants p
                ON p.id=d.winning_participant_id
            JOIN prize_deliveries pd
                ON pd.draw_result_id=d.id
            LEFT JOIN entity_admins a
                ON a.id=pd.delivered_by
            WHERE d.id=? AND d.outcome='winner'
        """, (result_id,)).fetchone()

    if prize is None:
        abort(404)

    body = (
        '<div class="card">'
        '<h2>Entrega de premio</h2>'
        '<p><strong>Sorteo:</strong> ' +
        esc(prize["raffle_title"]) + '</p>'
        '<p><strong>Numero ganador:</strong> ' +
        esc(prize["winning_number"]) + '</p>'
        '<p><strong>Ganador:</strong> ' +
        esc(prize["participant_name"]) + '</p>'
    )

    if prize["delivery_status"] == "delivered":
        body += (
            '<h3>PREMIO ENTREGADO</h3>'
            '<p><strong>Fecha:</strong> ' +
            esc(prize["delivered_at"]) + '</p>'
            '<p><strong>Administrador:</strong> ' +
            esc(prize["delivery_admin"]) + '</p>'
            '<p><strong>Observaciones:</strong> ' +
            esc(prize["delivery_notes"]) + '</p>'
            '<p>La entrega esta registrada definitivamente.</p>'
        )
    else:
        body += (
            '<p><strong>Estado:</strong> Pendiente de entrega</p>'
            '<form method="post">'
            '<input type="hidden" name="_csrf" value="' +
            esc(token()) + '">'
            '<label>Observaciones de la entrega</label>'
            '<textarea name="delivery_notes" rows="4" '
            'maxlength="1000" required '
            'style="width:100%;box-sizing:border-box"></textarea>'
            '<p><label>'
            '<input type="checkbox" name="confirmed" value="yes" '
            'required style="display:inline;width:auto">'
            ' Confirmo que el premio ha sido entregado '
            'al ganador.</label></p>'
            '<button type="submit">Confirmar entrega definitiva</button>'
            '</form>'
        )

    body += '</div>'

    return layout("Entrega de premio", body)
