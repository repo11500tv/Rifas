"""Correo de verificacion inicial de participantes."""

from platform_app.entity_mailer import send_entity_email


def send_registration_code(connection, destination, code):
    """Envia un codigo para verificar el correo registrado."""

    if (
        not isinstance(code, str)
        or len(code) != 6
        or not code.isascii()
        or not code.isdigit()
    ):
        raise ValueError("Codigo temporal no valido")

    subject = "Verifica tu correo - Rifas Beneficas"

    body = (
        "Gracias por registrarte en Rifas Beneficas.\n\n"
        "Para confirmar tu direccion de correo electronico, "
        "introduce el siguiente codigo:\n\n"
        f"{code}\n\n"
        "El codigo caduca en 5 minutos y solo puede "
        "utilizarse una vez.\n\n"
        "Si no has solicitado este registro, "
        "puedes ignorar este mensaje.\n"
    )

    return send_entity_email(
        connection,
        destination,
        subject,
        body
    )
