"""Solicitud de codigos de verificacion del registro."""

from platform_app.participant_otp import create_code_with_id
from platform_app.participant_code_invalidation import invalidate_code
from platform_app.participant_delivery_status import (
    create_delivery_record,
    update_delivery_status,
)
from platform_app.participant_smtp_outcome import (
    classify_smtp_result,
)
from platform_app.participant_combined_guard import (
    register_combined_attempt,
)
from platform_app.participant_otp_limits import seconds_until_resend
from platform_app.participant_safe_retry import (
    can_retry_after_failed_delivery,
)
from platform_app.participant_registration_email import (
    send_registration_code
)


class RegistrationResendTooSoon(Exception):
    """Debe transcurrir el intervalo minimo entre solicitudes."""

    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__("Debe esperar antes de solicitar otro codigo")


def request_registration_email_code(
    connection, secret_key, participant_id, ip_address
):
    """Solicita un codigo de verificacion de correo."""

    register_combined_attempt(
        connection, participant_id, ip_address
    )

    if connection.in_transaction:
        raise RuntimeError(
            "La conexion ya tiene una transaccion abierta"
        )

    try:
        connection.execute("BEGIN IMMEDIATE")

        participant = connection.execute(
            "SELECT email,active,email_verified "
            "FROM participants WHERE id=?",
            (participant_id,)
        ).fetchone()

        if participant is None or participant[1] != 1:
            raise ValueError(
                "Participante inexistente o inactivo"
            )

        if participant[2] == 1:
            raise ValueError(
                "El correo ya esta verificado"
            )

        destination = participant[0]

        remaining = seconds_until_resend(
            connection,
            participant_id,
            "email",
            "register"
        )

        if remaining > 0:
            retry_allowed = can_retry_after_failed_delivery(
                connection,
                participant_id,
                "email",
                "register",
            )

            if not retry_allowed:
                raise RegistrationResendTooSoon(remaining)

        code_id, code = create_code_with_id(
            connection,
            secret_key,
            participant_id,
            "email",
            "register"
        )

        create_delivery_record(connection, code_id)

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    # El envio SMTP se realiza sin transaccion abierta.
    try:
        send_registration_code(connection, destination, code)
    except Exception as exc:
        estado = classify_smtp_result(exc)

        # Conservamos el error original si falla el seguimiento.
        try:
            connection.execute("BEGIN IMMEDIATE")
            update_delivery_status(connection, code_id, estado)
            connection.commit()
        except Exception:
            connection.rollback()

        try:
            invalidate_code(
                connection,
                code_id,
                participant_id,
                "email",
                "register",
            )
        except Exception:
            pass

        raise

    connection.execute("BEGIN IMMEDIATE")
    try:
        update_delivery_status(
            connection, code_id, "accepted"
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return True
