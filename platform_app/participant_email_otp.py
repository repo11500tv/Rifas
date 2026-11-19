"""Envio de codigos temporales por correo electronico."""

from platform_app.entity_mailer import send_entity_email


def send_login_code(connection, destination, code):
    """Envia un codigo temporal al correo del participante."""

    if (
        not isinstance(code, str)
        or len(code) != 6
        or not code.isascii()
        or not code.isdigit()
    ):
        raise ValueError("Codigo temporal no valido")

    subject = "Codigo de acceso a Rifas Beneficas"

    body = (
        "Has solicitado un codigo para acceder a tu cuenta.\n\n"
        f"Tu codigo de acceso es: {code}\n\n"
        "Este codigo caduca en 5 minutos y solo puede "
        "utilizarse una vez.\n\n"
        "Si no has solicitado el acceso, ignora este mensaje.\n"
    )

    return send_entity_email(
        connection,
        destination,
        subject,
        body,
    )
