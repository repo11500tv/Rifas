"""Control atomico de solicitudes OTP por IP y participante."""

from platform_app.participant_ip_limits import (
    normalize_ip,
    check_ip_limit,
    record_ip_request,
)
from platform_app.participant_account_limits import (
    validate_participant_id,
    check_account_limit,
    record_account_request,
)


class CombinedLimitExceeded(Exception):
    """Se ha superado un limite de solicitudes OTP."""

    pass


def register_combined_attempt(
    connection,
    participant_id,
    ip_address,
):
    """Comprueba y registra ambos limites en una transaccion."""

    participant_id = validate_participant_id(participant_id)
    ip_address = normalize_ip(ip_address)

    if connection.in_transaction:
        raise RuntimeError(
            "La conexion ya tiene una transaccion abierta"
        )

    connection.execute("BEGIN IMMEDIATE")

    try:
        ip_allowed = check_ip_limit(
            connection, ip_address
        )

        account_allowed = check_account_limit(
            connection, participant_id
        )

        if not ip_allowed or not account_allowed:
            connection.rollback()
            raise CombinedLimitExceeded(
                "Limite de solicitudes alcanzado"
            )

        record_ip_request(
            connection, ip_address
        )

        record_account_request(
            connection, participant_id
        )

        connection.commit()

    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise

    return True
