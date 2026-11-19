"""Servicio de solicitud de codigos de acceso por correo."""

import sqlite3

from platform_app.participant_otp import create_code
from platform_app.participant_otp_limits import seconds_until_resend
from platform_app.participant_email_otp import send_login_code


class OTPResendTooSoon(Exception):
    """Todavia no se permite solicitar otro codigo."""

    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__("Debe esperar antes de solicitar otro codigo")


def request_email_login_code(
    connection, secret_key, participant_id, destination
):
    """Genera y envia un codigo de acceso por correo."""

    if connection.in_transaction:
        raise RuntimeError(
            "La conexion ya tiene una transaccion abierta"
        )

    try:
        # Bloquea las escrituras concurrentes de esta base SQLite.
        connection.execute("BEGIN IMMEDIATE")

        participant = connection.execute(
            "SELECT email,active,email_verified FROM participants WHERE id=?",
            (participant_id,)
        ).fetchone()

        if participant is None or participant[1] != 1:
            raise ValueError("Participante inexistente o inactivo")

        if participant[2] != 1:
            raise ValueError("Correo electronico no verificado")

        registered_email = participant[0]

        if (
            not isinstance(destination, str)
            or destination.casefold() != registered_email.casefold()
        ):
            raise ValueError(
                "El destinatario no coincide con el registrado"
            )

        remaining = seconds_until_resend(
            connection, participant_id, "email", "login"
        )

        if remaining > 0:
            raise OTPResendTooSoon(remaining)

        code = create_code(
            connection,
            secret_key,
            participant_id,
            "email",
            "login"
        )

        send_login_code(
            connection,
            destination,
            code
        )

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise
