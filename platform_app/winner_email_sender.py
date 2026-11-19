"""Adaptador SMTP para notificaciones de premios.

No se conecta automaticamente a ninguna ruta web.
"""

from platform_app.entity_mailer import send_entity_email
from platform_app.participant_smtp_outcome import (
    classify_smtp_exception
)


def send_winner_email(db, prepared, dry_run=True):
    """
    Envia un mensaje previamente preparado.

    dry_run=True:
        Simula el envio sin utilizar SMTP.

    dry_run=False:
        Utiliza la configuracion SMTP de la entidad.

    Esta funcion NO modifica el estado de las notificaciones.
    """

    if not isinstance(prepared, dict):
        raise ValueError("Datos de notificacion invalidos.")

    required = (
        "recipient",
        "subject",
        "text",
        "html"
    )

    if not all(prepared.get(key) for key in required):
        raise ValueError(
            "Faltan datos obligatorios del correo."
        )

    if dry_run:
        return {
            "status": "simulated",
            "smtp_accepted": False,
            "error": "",
            "recipient": prepared["recipient"]
        }

    try:
        # El sistema SMTP actual recibe un cuerpo de texto.
        accepted = send_entity_email(
            db,
            prepared["recipient"],
            prepared["subject"],
            prepared["text"]
        )

        if accepted is True:
            return {
                "status": "sent",
                "smtp_accepted": True,
                "error": "",
                "recipient": prepared["recipient"]
            }

        return {
            "status": "uncertain",
            "smtp_accepted": False,
            "error": "SMTP no confirmo la aceptacion.",
            "recipient": prepared["recipient"]
        }

    except Exception as exc:
        classification = classify_smtp_exception(exc)

        status = (
            "failed"
            if classification == "failed"
            else "uncertain"
        )

        return {
            "status": status,
            "smtp_accepted": False,
            "error": type(exc).__name__,
            "recipient": prepared["recipient"]
        }
