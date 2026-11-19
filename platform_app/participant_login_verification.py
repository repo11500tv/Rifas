"""Verificacion segura de codigos de acceso de participantes."""

from platform_app.participant_otp import verify_code
from platform_app.participant_session_validation import (
    valid_participant_id,
)


def confirm_login_code(
    connection, secret_key, participant_id, code
):
    """Autoriza el acceso solo con codigo valido y envio aceptado.

    No crea sesiones web.
    """

    participant_id = valid_participant_id(participant_id)

    if participant_id is None:
        return False

    if connection.in_transaction:
        raise RuntimeError(
            "La conexion ya tiene una transaccion abierta"
        )

    try:
        connection.execute("BEGIN IMMEDIATE")

        participant = connection.execute(
            "SELECT active,email_verified "
            "FROM participants WHERE id=?",
            (participant_id,)
        ).fetchone()

        if (
            participant is None
            or participant[0] != 1
            or participant[1] != 1
        ):
            connection.rollback()
            return False

        delivery = connection.execute(
            "SELECT d.status "
            "FROM participant_codes c "
            "JOIN participant_code_deliveries d "
            "ON d.code_id=c.id "
            "WHERE c.participant_id=? "
            "AND c.channel='email' "
            "AND c.purpose='login' "
            "AND c.used_at IS NULL "
            "ORDER BY c.id DESC LIMIT 1",
            (participant_id,)
        ).fetchone()

        if delivery is None or delivery[0] != "accepted":
            connection.rollback()
            return False

        valid = verify_code(
            connection,
            secret_key,
            participant_id,
            "email",
            "login",
            code
        )

        # Conserva los intentos fallidos y el consumo del codigo.
        connection.commit()

        return bool(valid)

    except Exception:
        connection.rollback()
        raise
