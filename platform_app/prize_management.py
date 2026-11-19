"""Administracion de premios adjudicados."""

import html
from flask import Blueprint, abort, url_for
from platform_app.entity_routes import edb, layout, protected

bp = Blueprint(
    "prize_management",
    __name__,
    url_prefix="/e/<slug>/administracion/premios"
)


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


@bp.get("/")
@protected
def list_prizes(slug):
    with edb(slug) as db:
        prizes = db.execute("""
            SELECT
                d.id,
                r.title AS raffle_title,
                d.winning_number,
                d.outcome,
                d.recorded_at,
                p.name AS participant_name,
                p.email AS participant_email,
                pd.notification_status,
                pd.delivery_status
            FROM raffle_draw_results d
            JOIN raffles r ON r.id = d.raffle_id
            LEFT JOIN participants p
                ON p.id = d.winning_participant_id
            LEFT JOIN prize_deliveries pd
                ON pd.draw_result_id = d.id
            ORDER BY d.id DESC
        """).fetchall()

        setting = db.execute("""
            SELECT value FROM entity_settings
            WHERE key = 'automatic_winner_notifications'
        """).fetchone()

    automatic = bool(setting and setting["value"] == "1")

    body = (
        '<div class="card">'
        '<h2>Gestion de premios</h2>'
        '<p>Notificaciones automaticas: <strong>' +
        ("ACTIVADAS" if automatic else "DESACTIVADAS") +
        '</strong></p>'
        '<p>Esta configuracion pertenece exclusivamente '
        'a esta entidad.</p>'
        '<p>Premios registrados: <strong>' +
        str(len(prizes)) + '</strong></p>'
        '</div>'
    )

    if not prizes:
        body += (
            '<div class="card">'
            '<p>Todavia no hay adjudicaciones registradas.</p>'
            '</div>'
        )


    for prize in prizes:
        winner = prize["outcome"] == "winner"

        notification = (
            "Notificado"
            if prize["notification_status"] == "notified"
            else "Pendiente de notificacion"
        ) if winner else "No corresponde"

        delivery = (
            "Entregado"
            if prize["delivery_status"] == "delivered"
            else "Pendiente de entrega"
        ) if winner else "Premio desierto"

        body += (
            '<div class="card">'
            '<h3>' + esc(prize["raffle_title"]) + '</h3>'
            '<p><strong>Numero ganador:</strong> ' +
            esc(prize["winning_number"]) + '</p>'
            '<p><strong>Resultado:</strong> ' +
            ("Premio adjudicado" if winner else "Premio desierto") +
            '</p>'
            '<p><strong>Ganador:</strong> ' +
            esc(prize["participant_name"] or "Sin ganador") + '</p>'
            '<p><strong>Correo:</strong> ' +
            esc(prize["participant_email"] or "-") + '</p>'
            '<p><strong>Notificacion:</strong> ' +
            notification + '</p>'
            '<p><strong>Entrega:</strong> ' +
            delivery + '</p>'
            '<p><strong>Adjudicacion registrada:</strong> ' +
            esc(prize["recorded_at"]) + '</p>'
        )

        if winner:
            communications_url = url_for(
                "prize_communications_admin.communications",
                slug=slug,
                result_id=prize["id"]
            )
            delivery_url = url_for(
                "prize_delivery_admin.delivery",
                slug=slug,
                result_id=prize["id"]
            )
            body += (
                '<p><a href="' + esc(communications_url) +
                '">Registrar comunicaciones</a></p>'
            )
            body += (
                '<p><a href="' + esc(delivery_url) +
                '">Registrar entrega</a></p>'
            )

        body += '</div>'

    settings_url = url_for(
        "prize_notification_settings.settings",
        slug=slug
    )
    body = (
        '<p><a href="' + settings_url +
        '">Configurar notificaciones</a></p>'
    ) + body
    return layout("Gestion de premios", body)
