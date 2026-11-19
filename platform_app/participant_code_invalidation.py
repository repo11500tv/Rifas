"""Invalidacion selectiva de codigos de participantes."""

import time


def invalidate_code(
    connection,
    code_id,
    participant_id,
    channel,
    purpose,
):
    """Invalida un codigo concreto si sigue pendiente.

    Nunca invalida otros codigos del participante.
    Devuelve True solamente cuando se actualiza el registro.
    """

    if connection.in_transaction:
        raise RuntimeError(
            "La conexion ya tiene una transaccion abierta"
        )

    if not isinstance(code_id, int) or isinstance(code_id, bool):
        raise ValueError("Identificador de codigo invalido")

    if code_id <= 0:
        raise ValueError("Identificador de codigo invalido")

    if not isinstance(participant_id, int) or isinstance(participant_id, bool):
        raise ValueError("Identificador de participante invalido")

    if participant_id <= 0:
        raise ValueError("Identificador de participante invalido")

    if channel not in ("email", "sms"):
        raise ValueError("Canal invalido")

    if purpose not in ("register", "login", "verify", "recovery"):
        raise ValueError("Finalidad invalida")

    now = int(time.time())

    try:
        connection.execute("BEGIN IMMEDIATE")

        result = connection.execute(
            "UPDATE participant_codes "
            "SET used_at=? "
            "WHERE id=? "
            "AND participant_id=? "
            "AND channel=? "
            "AND purpose=? "
            "AND used_at IS NULL",
            (
                now,
                code_id,
                participant_id,
                channel,
                purpose,
            )
        )

        connection.commit()
        return result.rowcount == 1

    except Exception:
        connection.rollback()
        raise
