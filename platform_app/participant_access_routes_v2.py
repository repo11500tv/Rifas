"""Acceso de participantes mediante codigo de correo."""

import re
from html import escape

from flask import (
    Blueprint, abort, current_app, redirect,
    request, session, url_for
)

from platform_app.entity_routes import (
    edb, get_entity, layout, token
)
from platform_app.participant_email_lookup_v2 import (
    find_eligible_participant
)
from platform_app.participant_login_service_v2 import (
    request_login_email_code,
    LoginResendTooSoon
)
from platform_app.participant_login_verification import (
    confirm_login_code
)
from platform_app.participant_pending_login import (
    start_pending_login,
    get_pending_login,
    finish_pending_login,
    clear_pending_login
)
from platform_app.participant_account_access_v2 import (
    participant_can_access
)

bp = Blueprint(
    "participant_access_v2",
    __name__,
    url_prefix="/e/<slug>/participantes"
)


def check_entity(slug):
    entity = get_entity(slug)
    if entity is None or entity["status"] != "active":
        abort(404)
    return entity


def csrf():
    return (
        '<input type="hidden" name="_csrf" value="' +
        escape(str(token()), quote=True) + '">'
    )


def notice(message):
    return '<p>' + escape(message) + '</p>'


@bp.route("/acceso-codigo", methods=["GET", "POST"])
def request_code(slug):
    entity = check_entity(slug)
    message = ""

    if request.method == "POST":
        email = request.form.get("email", "")
        connection = edb(slug)

        try:
            participant_id = find_eligible_participant(
                connection, email
            )

            if participant_id is not None:
                start_pending_login(
                    session, slug, participant_id
                )

                try:
                    request_login_email_code(
                        connection,
                        current_app.secret_key.encode("utf-8"),
                        participant_id,
                        request.remote_addr or "unknown"
                    )
                except LoginResendTooSoon:
                    pass
                except Exception:
                    current_app.logger.exception(
                        "Error enviando codigo de acceso"
                    )

                return redirect(
                    url_for(
                        "participant_access_v2.verify_access",
                        slug=slug
                    )
                )

        finally:
            connection.close()

        message = (
            "Si el correo corresponde a una cuenta "
            "verificada, recibiras instrucciones "
            "para acceder."
        )

    body = (
        '<div class="card">'
        '<h2>Acceso de participantes</h2>'
        '<p>Introduce tu correo electronico.</p>' +
        notice(message) +
        '<form method="post">' + csrf() +
        '<p><input name="email" type="email" '
        'maxlength="254" autocomplete="email" '
        'required></p>'
        '<button type="submit">Solicitar codigo</button>'
        '</form>'
        '</div>'
    )

    return layout(
        "Acceso de participantes - " + entity["name"],
        body
    )


@bp.route("/verificar-acceso", methods=["GET", "POST"])
def verify_access(slug):
    entity = check_entity(slug)
    participant_id = get_pending_login(session, slug)

    if participant_id is None:
        return redirect(
            url_for(
                "participant_access_v2.request_code",
                slug=slug
            )
        )

    message = session.pop("login_message", "")

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        if not re.fullmatch(r"[0-9]{6}", code):
            message = "Introduce un codigo de seis cifras."
        else:
            connection = edb(slug)
            try:
                valid = confirm_login_code(
                    connection,
                    current_app.secret_key.encode("utf-8"),
                    participant_id,
                    code
                )

                if valid:
                    valid = participant_can_access(
                        connection, participant_id
                    )
            finally:
                connection.close()

            if valid and finish_pending_login(
                session, slug, participant_id
            ):
                return redirect(
                    url_for(
                        "participants.account",
                        slug=slug
                    )
                )

            message = "Codigo incorrecto o caducado."

    body = (
        '<div class="card">'
        '<h2>Verificar acceso</h2>' +
        notice(message) +
        '<form method="post">' + csrf() +
        '<p><input name="code" inputmode="numeric" '
        'pattern="[0-9]{6}" maxlength="6" '
        'autocomplete="one-time-code" required></p>'
        '<button type="submit">Verificar codigo</button>'
        '</form>'
        '<form method="post" action="' +
        escape(
            url_for(
                "participant_access_v2.resend_code",
                slug=slug
            ), quote=True
        ) + '">' + csrf() +
        '<button type="submit">Reenviar codigo</button>'
        '</form>'
        '</div>'
    )

    return layout(
        "Verificar acceso - " + entity["name"],
        body
    )


@bp.route("/reenviar-codigo", methods=["POST"])
def resend_code(slug):
    check_entity(slug)
    participant_id = get_pending_login(session, slug)

    if participant_id is None:
        return redirect(
            url_for(
                "participant_access_v2.request_code",
                slug=slug
            )
        )

    connection = edb(slug)

    try:
        request_login_email_code(
            connection,
            current_app.secret_key.encode("utf-8"),
            participant_id,
            request.remote_addr or "unknown"
        )
        message = "Se ha solicitado un nuevo codigo."
    except LoginResendTooSoon as exc:
        message = (
            "Espera " + str(exc.seconds) +
            " segundos antes de solicitar otro codigo."
        )
    except Exception:
        current_app.logger.exception(
            "Error reenviando codigo de acceso"
        )
        message = "No se ha podido enviar el codigo."
    finally:
        connection.close()

    session["login_message"] = message

    return redirect(
        url_for(
            "participant_access_v2.verify_access",
            slug=slug
        )
    )
