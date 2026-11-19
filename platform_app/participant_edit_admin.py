"""Administracion de la edicion de participantes."""

from html import escape

from flask import (
    Blueprint, abort, flash, redirect,
    request, session, url_for
)

from platform_app.entity_routes import (
    edb, get_entity, layout, owner_required, token
)

from platform_app.participant_admin_form import participant_edit_form
from platform_app.participant_admin_update import update_participant


bp = Blueprint(
    "participant_edit_admin",
    __name__,
    url_prefix="/e/<slug>/participantes/administracion",
)


@bp.route("/<int:participant_id>/editar", methods=["GET", "POST"])
@owner_required
def edit_participant(slug, participant_id):
    entity = get_entity(slug)

    if entity is None or entity["status"] != "active":
        abort(404)

    with edb(slug) as connection:
        participant = connection.execute(
            "SELECT id,name,email,phone,email_verified,active "
            "FROM participants WHERE id=?",
            (participant_id,),
        ).fetchone()

        if participant is None:
            abort(404)

        balance = connection.execute(
            "SELECT COALESCE(SUM(amount_cents),0) "
            "FROM credit_movements WHERE participant_id=?",
            (participant_id,),
        ).fetchone()[0]

    message = ""

    if request.method == "POST":
        name = request.form.get("name", "")
        email = request.form.get("email", "")
        phone = request.form.get("phone", "")
        active_value = request.form.get("active", "")

        if active_value not in ("0", "1"):
            message = "Selecciona un estado valido."

        else:
            try:
                with edb(slug) as connection:
                    changed = update_participant(
                        connection,
                        participant_id,
                        int(session["entity_user_id"]),
                        name,
                        email,
                        phone,
                        active_value == "1",
                    )

                if changed:
                    flash("Datos del participante actualizados.")
                else:
                    flash("No se han detectado cambios.")

                return redirect(
                    url_for(
                        "participant_edit_admin.edit_participant",
                        slug=slug,
                        participant_id=participant_id,
                    )
                )

            except (ValueError, PermissionError) as exc:
                message = str(exc)

        # Conservar los valores introducidos si hay un error.
        participant = {
            "id": participant_id,
            "name": name,
            "email": email,
            "phone": phone,
            "email_verified": participant["email_verified"],
            "active": (
                active_value == "1"
                if active_value in ("0", "1")
                else participant["active"]
            ),
        }

    action_url = url_for(
        "participant_edit_admin.edit_participant",
        slug=slug,
        participant_id=participant_id,
    )

    back_url = url_for(
        "participants.admin_list",
        slug=slug,
    )

    body = participant_edit_form(
        participant,
        token(),
        action_url,
        back_url,
        balance,
        message,
    )

    return layout(
        "Editar participante - " + entity["name"],
        body,
    )
