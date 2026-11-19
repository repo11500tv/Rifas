"""Control de frecuencia de codigos temporales."""

import time

RESEND_INTERVAL = 60


def seconds_until_resend(
    connection, participant_id, channel, purpose, now=None
):
    """Devuelve los segundos restantes antes de otro codigo."""

    if channel not in ("email", "sms"):
        raise ValueError("Canal no valido")

    if purpose not in ("register", "login", "verify", "recovery"):
        raise ValueError("Finalidad no valida")

    if now is None:
        now = int(time.time())

    row = connection.execute(
        "SELECT created_at FROM participant_codes "
        "WHERE participant_id=? AND channel=? AND purpose=? "
        "ORDER BY id DESC LIMIT 1",
        (participant_id, channel, purpose)
    ).fetchone()

    if row is None:
        return 0

    created = row[0]

    # SQLite almacena created_at como fecha UTC.
    from datetime import datetime, timezone

    timestamp = int(
        datetime.strptime(
            created, "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc).timestamp()
    )

    remaining = RESEND_INTERVAL - (now - timestamp)

    return max(0, remaining)


def can_resend(
    connection, participant_id, channel, purpose, now=None
):
    """Indica si ha transcurrido el intervalo minimo."""

    return seconds_until_resend(
        connection, participant_id, channel, purpose, now
    ) == 0
