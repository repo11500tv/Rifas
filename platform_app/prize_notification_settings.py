"""Configuracion de notificaciones de premios por entidad."""

from html import escape

from flask import (
    Blueprint, flash, redirect, request,
    session, url_for
)

from platform_app.entity_routes import (
    edb, layout, protected, token
)

bp = Blueprint(
    "prize_notification_settings",
    __name__,
    url_prefix="/e/<slug>/administracion/premios"
)


@bp.route("/configuracion", methods=["GET", "POST"])
@protected
def settings(slug):
    if request.method == "POST":
        enabled = (
            "1" if request.form.get("automatic_enabled") == "yes"
            else "0"
        )

        instructions = request.form.get(
            "collection_instructions", ""
        ).strip()

        if not instructions or len(instructions) > 2000:
            flash(
                "Las instrucciones son obligatorias "
                "y no pueden superar 2000 caracteres."
            )
        else:
            with edb(slug) as db:
                db.execute("""
                    INSERT INTO entity_settings(key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE
                    SET value=excluded.value
                """, (
                    "automatic_winner_notifications",
                    enabled
                ))

                db.execute("""
                    INSERT INTO entity_settings(key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE
                    SET value=excluded.value
                """, (
                    "prize_collection_instructions",
                    instructions
                ))

                db.commit()

            flash("Configuracion guardada correctamente.")

            return redirect(url_for(
                "prize_notification_settings.settings",
                slug=slug
            ))

    with edb(slug) as db:
        rows = db.execute("""
            SELECT key, value
            FROM entity_settings
            WHERE key IN (
                'automatic_winner_notifications',
                'prize_collection_instructions'
            )
        """).fetchall()

    values = {row["key"]: row["value"] for row in rows}

    enabled = (
        values.get("automatic_winner_notifications", "0") == "1"
    )

    instructions = values.get(
        "prize_collection_instructions", ""
    )

    checked = "checked" if enabled else ""

    status = (
        "ACTIVADAS" if enabled else "DESACTIVADAS"
    )

    body = (
        '<div class="card">'
        '<h2>Configuracion de premios</h2>'
        '<p><strong>Notificaciones automaticas:</strong> '
        + status + '</p>'
        '<p>Esta configuracion pertenece exclusivamente '
        'a esta hermandad.</p>'
        '<form method="post">'
        '<input type="hidden" name="_csrf" value="'
        + escape(token(), quote=True) + '">'
        '<p><label>'
        '<input type="checkbox" name="automatic_enabled" '
        'value="yes" ' + checked + ' '
        'style="display:inline;width:auto">'
        ' Activar notificaciones automaticas al ganador'
        '</label></p>'
        '<p><strong>Instrucciones de recogida:</strong></p>'
        '<textarea name="collection_instructions" '
        'rows="6" maxlength="2000" required '
        'style="width:100%;box-sizing:border-box">'
        + escape(instructions) + '</textarea>'
        '<p><button type="submit">'
        'Guardar configuracion'
        '</button></p>'
        '</form>'
        '<p><small>La activacion se guarda como '
        'preferencia. El envio automatico de correos '
        'todavia no esta habilitado.</small></p>'
        '</div>'
    )

    return layout("Configuracion de premios", body)
