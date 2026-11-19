"""Solicitud segura de codigos de acceso por correo."""

from platform_app.participant_otp import create_code_with_id
from platform_app.participant_combined_guard import register_combined_attempt
from platform_app.participant_otp_limits import seconds_until_resend
from platform_app.participant_safe_retry import can_retry_after_failed_delivery
from platform_app.participant_delivery_status import (
    create_delivery_record,
    update_delivery_status,
)
from platform_app.participant_code_invalidation import invalidate_code
from platform_app.participant_smtp_outcome import classify_smtp_result
from platform_app.participant_email_otp import send_login_code


class LoginResendTooSoon(Exception):
    """Intervalo minimo entre solicitudes."""

    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__("Debe esperar antes de solicitar otro codigo")


def request_login_email_code(
    connection, secret_key, participant_id, ip_address
):
    """Solicita un codigo de acceso sin bloquear SQLite durante SMTP."""

    register_combined_attempt(
        connection, participant_id, ip_address
    )

    if connection.in_transaction:
        raise RuntimeError("Transaccion inesperada")

    try:
        connection.execute("BEGIN IMMEDIATE")

        participant = connection.execute(
            "SELECT email,active,email_verified "
            "FROM participants WHERE id=?",
            (participant_id,)
        ).fetchone()

        if (
            participant is None
            or participant[1] != 1
            or participant[2] != 1
        ):
            raise ValueError("Cuenta no habilitada para acceso")

        destination = participant[0]

        remaining = seconds_until_resend(
            connection, participant_id, "email", "login"
        )

        if remaining > 0 and not can_retry_after_failed_delivery(
            connection, participant_id, "email", "login"
        ):
            raise LoginResendTooSoon(remaining)

        code_id, code = create_code_with_id(
            connection, secret_key, participant_id,
            "email", "login"
        )

        create_delivery_record(connection, code_id)
        connection.commit()

    except Exception:
        connection.rollback()
        raise

    # El envio SMTP se realiza fuera de la transaccion SQLite.
    try:
        send_login_code(connection, destination, code)

    except Exception as exc:
        estado = classify_smtp_result(exc)

        try:
            connection.execute("BEGIN IMMEDIATE")
            update_delivery_status(connection, code_id, estado)
            connection.commit()
        except Exception:
            connection.rollback()

        try:
            invalidate_code(
                connection, code_id, participant_id,
                "email", "login"
            )
        except Exception:
            pass

        raise

    try:
        connection.execute("BEGIN IMMEDIATE")
        update_delivery_status(connection, code_id, "accepted")
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return True
