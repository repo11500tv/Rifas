"""Envío de correo mediante la configuración SMTP de cada entidad."""

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from platform_app.entity_smtp import get_smtp_config
from platform_app.smtp_transport import open_secure_smtp
from platform_app.smtp_validation import valid_email, validate_smtp


class EntityMailError(Exception):
    """Error controlado del servicio de correo de una entidad."""


def send_entity_email(connection, destination, subject, body):
    """
    Envía un mensaje utilizando la configuración SMTP
    almacenada en la base de datos de la entidad.
    """

    if not valid_email(destination):
        raise EntityMailError("Destinatario no válido")

    if not isinstance(subject, str) or not subject.strip():
        raise EntityMailError("Asunto no válido")

    if "\r" in subject or "\n" in subject:
        raise EntityMailError("El asunto contiene caracteres no permitidos")

    if not isinstance(body, str) or not body.strip():
        raise EntityMailError("El mensaje está vacío")

    try:
        config = get_smtp_config(connection)
    except Exception as exc:
        raise EntityMailError(
            "No se puede leer la configuración SMTP"
        ) from exc

    errors = validate_smtp(
        config["host"],
        config["port"],
        config["security"],
        config["username"],
        config["sender"],
    )

    if errors:
        raise EntityMailError(
            "Configuración SMTP incompleta o incorrecta: "
            + "; ".join(errors)
        )

    if not config["password"]:
        raise EntityMailError(
            "No se ha configurado la contraseña SMTP"
        )

    message = EmailMessage()
    sender_name = config.get("sender_name", "").strip()

    if (
        len(sender_name) > 120
        or "\r" in sender_name
        or "\n" in sender_name
    ):
        raise EntityMailError("Nombre del remitente no válido")

    message["From"] = (
        formataddr((sender_name, config["sender"]))
        if sender_name
        else config["sender"]
    )
    message["To"] = destination
    message["Subject"] = subject
    message.set_content(body)

    try:
        with open_secure_smtp(
            config["host"],
            config["port"],
            config["security"],
        ) as smtp:
            smtp.login(
                config["username"],
                config["password"],
            )
            smtp.send_message(message)

    except (
        smtplib.SMTPException,
        OSError,
        ValueError,
    ) as exc:
        raise EntityMailError(
            "No se ha podido enviar el correo electrónico"
        ) from exc

    return True
