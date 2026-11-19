"""Verificacion inicial del correo de participantes."""

from platform_app.participant_otp import verify_code


def confirm_email_code(
    connection, secret_key, participant_id, code
):
    """Confirma el correo mediante un codigo temporal."""

    if connection.in_transaction:
        raise RuntimeError(
            "La conexion ya tiene una transaccion abierta"
        )

    try:
        connection.execute("BEGIN IMMEDIATE")

        participant = connection.execute(
            "SELECT active,email_verified FROM participants "
            "WHERE id=?",
            (participant_id,)
        ).fetchone()

        if participant is None or participant[0] != 1:
            connection.rollback()
            return False

        if participant[1] == 1:
            connection.rollback()
            return False

        # Solo se verifican codigos cuya entrega SMTP
        # haya sido aceptada para ese codigo concreto.
        delivery = connection.execute(
            "SELECT d.status "
            "FROM participant_codes c "
            "LEFT JOIN participant_code_deliveries d "
            "ON d.code_id=c.id "
            "WHERE c.participant_id=? "
            "AND c.channel='email' "
            "AND c.purpose='register' "
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
            "register",
            code
        )

        if not valid:
            connection.commit()
            return False

        connection.execute(
            "UPDATE participants SET email_verified=1 "
            "WHERE id=? AND email_verified=0",
            (participant_id,)
        )

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise
