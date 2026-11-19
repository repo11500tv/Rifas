"""Control seguro de reintentos tras fallos SMTP confirmados."""

from platform_app.participant_delivery_status import (
    failed_delivery_allows_retry,
)


def can_retry_after_failed_delivery(
    connection,
    participant_id,
    channel,
    purpose,
):
    """Permite omitir la espera solo tras un fallo confirmado.

    Se consulta exclusivamente el ultimo codigo del
    participante para el canal y la operacion indicados.
    """

    if (
        not isinstance(participant_id, int)
        or isinstance(participant_id, bool)
        or participant_id <= 0
    ):
        return False

    if channel not in ("email", "sms"):
        return False

    if purpose not in (
        "register", "login", "verify", "recovery"
    ):
        return False

    row = connection.execute(
        "SELECT id, used_at "
        "FROM participant_codes "
        "WHERE participant_id=? "
        "AND channel=? AND purpose=? "
        "ORDER BY id DESC LIMIT 1",
        (participant_id, channel, purpose)
    ).fetchone()

    if row is None:
        return False

    code_id, used_at = row

    # Un codigo pendiente de uso no permite
    # omitir el intervalo de seguridad.
    if used_at is None:
        return False

    return failed_delivery_allows_retry(
        connection, code_id
    )
