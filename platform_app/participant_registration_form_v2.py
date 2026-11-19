"""Registro de participantes mediante verificacion por email."""

import re
import sqlite3
from html import escape

from flask import (
    Blueprint, abort, current_app, redirect,
    request, session, url_for
)

from platform_app.entity_routes import (
    edb, get_entity, layout, token
)
from platform_app.participant_registration_service import (
    request_registration_email_code
)
from platform_app.participant_email_verification import (
    confirm_email_code
)


from platform_app.participant_registration_service import RegistrationResendTooSoon

bp = Blueprint(
    "participant_registration_v2",
    __name__,
    url_prefix="/e/<slug>/participantes"
)


def page(title, content):
    return layout(title, content)


def form_field(label, name, kind="text", value=""):
    return (
        "<p><label>" + escape(label) + "<br>"
        '<input type="' + kind + '" name="' + name + '" '
        'value="' + escape(value, quote=True) + '" '
        'required></label></p>'
    )


def csrf_field():
    return (
        '<input type="hidden" name="_csrf" value="' +
        escape(str(token()), quote=True) + '">'
    )


def registration_form_html(slug, message=""):
    action = url_for(
        "participant_registration_v2.registration_form",
        slug=slug
    )

    content = "<h2>Registro de participantes</h2>"

    if message:
        content += "<p><strong>" + escape(message) + "</strong></p>"

    content += (
        '<form method="post" action="' +
        escape(action, quote=True) + '">' +
        csrf_field() +
        form_field("Nombre completo", "name") +
        form_field("Correo electronico", "email", "email") +
        form_field("Telefono movil", "phone", "tel") +
        '<button type="submit">Registrarme</button>'
        "</form>"
        "<p>Recibiras un codigo por correo electronico "
        "para verificar tu cuenta.</p>"
    )

    return content


@bp.route("/registro-nuevo", methods=["GET", "POST"])
def registration_form(slug):
    entity = get_entity(slug)

    if entity is None or entity["status"] != "active":
        abort(404)

    if request.method == "GET":
        return page(
            "Registro de participantes",
            registration_form_html(slug)
        )

    name = " ".join(
        request.form.get("name", "").strip().split()
    )
    email = request.form.get("email", "").strip().lower()
    phone = re.sub(
        r"[\s().-]", "",
        request.form.get("phone", "").strip()
    )

    if not (
        2 <= len(name) <= 150
        and len(email) <= 254
        and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
        and re.fullmatch(r"\+?[0-9]{9,15}", phone)
    ):
        return page(
            "Registro de participantes",
            registration_form_html(
                slug, "Comprueba los datos introducidos."
            )
        ), 400

    connection = edb(slug)

    try:
        existing = connection.execute(
            "SELECT id,email,phone,active,email_verified "
            "FROM participants "
            "WHERE email=? OR phone=? LIMIT 1",
            (email, phone)
        ).fetchone()

        if existing:
            same_email = existing[1].strip().lower() == email
            same_phone = existing[2] == phone
            active = existing[3] == 1
            email_pending = existing[4] == 0

            if same_email and same_phone and active and email_pending:
                participant_id = existing[0]

                session["registration_slug"] = slug
                session["registration_participant_id"] = participant_id

                try:
                    request_registration_email_code(
                        connection,
                        current_app.secret_key.encode("utf-8"),
                        participant_id,
                        request.remote_addr or "unknown"
                    )
                    session["registration_message"] = (
                        "Cuenta pendiente recuperada. "
                        "Se ha solicitado un nuevo codigo de verificacion."
                    )
                except RegistrationResendTooSoon as exc:
                    session["registration_message"] = (
                        "Tu cuenta esta pendiente de verificacion. "
                        "Espera " + str(exc.seconds) +
                        " segundos para solicitar otro codigo."
                    )
                except Exception:
                    current_app.logger.exception(
                        "Error recuperando registro pendiente"
                    )
                    session["registration_message"] = (
                        "Cuenta pendiente recuperada, pero no se ha "
                        "podido enviar el codigo. Puedes intentarlo "
                        "de nuevo mediante Reenviar codigo."
                    )

                return redirect(
                    url_for(
                        "participant_registration_v2.verify_registration",
                        slug=slug
                    )
                )

            return page(
                "Registro de participantes",
                registration_form_html(
                    slug,
                    "El correo o telefono ya figura registrado."
                )
            ), 409

        cursor = connection.execute(
            "INSERT INTO participants "
            "(name,email,phone,email_verified,phone_verified,"
            "preferred_login,active) "
            "VALUES (?,?,?,0,0,'email',1)",
            (name, email, phone)
        )

        participant_id = cursor.lastrowid
        connection.commit()

        session["registration_slug"] = slug
        session["registration_participant_id"] = participant_id

        try:
            request_registration_email_code(
                connection,
                current_app.secret_key.encode('utf-8'),
                participant_id,
                request.remote_addr or "unknown"
            )
        except Exception:
            current_app.logger.exception(
                "Error enviando codigo de registro"
            )
            return page(
                "Verificacion pendiente",
                "<h2>Cuenta creada</h2>"
                "<p>No se ha podido confirmar el envio del "
                "codigo. No se ha activado la cuenta.</p>"
                "<p>Contacta con la hermandad para "
                "resolver la incidencia.</p>"
            ), 503

        return redirect(
            url_for(
                "participant_registration_v2.verify_registration",
                slug=slug
            )
        )

    except sqlite3.IntegrityError:
        connection.rollback()
        return page(
            "Registro de participantes",
            registration_form_html(
                slug,
                "El correo o telefono ya figura registrado."
            )
        ), 409

    finally:
        connection.close()



@bp.route("/reenviar-registro", methods=["POST"])
def resend_registration(slug):
    entity = get_entity(slug)
    if entity is None or entity["status"] != "active":
        abort(404)

    participant_id = session.get(
        "registration_participant_id"
    )

    if (
        session.get("registration_slug") != slug
        or not isinstance(participant_id, int)
    ):
        return redirect(
            url_for(
                "participant_registration_v2.registration_form",
                slug=slug
            )
        )

    connection = edb(slug)
    try:
        try:
            request_registration_email_code(
                connection,
                current_app.secret_key.encode("utf-8"),
                participant_id,
                request.remote_addr or "unknown"
            )
            message = "Se ha enviado un nuevo codigo."
        except RegistrationResendTooSoon as exc:
            message = (
                "Espera " + str(exc.seconds) +
                " segundos antes de solicitar otro codigo."
            )
        except Exception:
            current_app.logger.exception(
                "Error reenviando codigo de registro"
            )
            message = (
                "No se ha podido enviar el codigo. "
                "Intentalo mas tarde."
            )
    finally:
        connection.close()

    session["registration_message"] = message

    return redirect(
        url_for(
            "participant_registration_v2.verify_registration",
            slug=slug
        )
    )


@bp.route("/verificar-registro", methods=["GET", "POST"])
def verify_registration(slug):
    entity = get_entity(slug)

    if entity is None or entity["status"] != "active":
        abort(404)

    if (
        session.get("registration_slug") != slug
        or not isinstance(
            session.get("registration_participant_id"), int
        )
    ):
        return redirect(
            url_for(
                "participant_registration_v2.registration_form",
                slug=slug
            )
        )

    message = session.pop("registration_message", "")

    if request.method == "POST":
        code = request.form.get("code", "").strip()

        if not re.fullmatch(r"[0-9]{6}", code):
            message = "Introduce un codigo de seis cifras."
        else:
            connection = edb(slug)
            try:
                valid = confirm_email_code(
                    connection,
                    current_app.secret_key.encode('utf-8'),
                    session["registration_participant_id"],
                    code
                )
            finally:
                connection.close()

            if valid:
                session.pop("registration_slug", None)
                session.pop(
                    "registration_participant_id", None
                )
                return page(
                    "Cuenta verificada",
                    "<h2>Correo verificado correctamente</h2>"
                    "<p>Tu cuenta de participante ya esta "
                    "habilitada para acceder mediante "
                    "codigos enviados por correo.</p>"
                    '<p><a class="btn" href="' +
                    escape(
                        url_for(
                            "participant_access_v2.request_code",
                            slug=slug
                        ),
                        quote=True
                    ) +
                    '">Acceder a mi cuenta</a></p>'
                )

            message = "Codigo incorrecto o caducado."

    content = "<h2>Verificar correo electronico</h2>"

    if message:
        content += "<p>" + escape(message) + "</p>"

    content += (
        '<form method="post">' +
        csrf_field() +
        '<p><label>Codigo de seis cifras<br>'
        '<input name="code" inputmode="numeric" '
        'pattern="[0-9]{6}" maxlength="6" required>'
        '</label></p>'
        '<button type="submit">Verificar codigo</button>'
        '</form>'
    )


    content += (
        '<form method="post" action="' +
        escape(
            url_for(
                "participant_registration_v2.resend_registration",
                slug=slug
            ),
            quote=True
        ) +
        '">' +
        csrf_field() +
        '<button type="submit">Reenviar codigo</button>' +
        '</form>'
    )

    return page("Verificar correo", content)
