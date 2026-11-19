"""Esquema completo de participantes."""

from platform_app.participant_schema_v2 import (
    SCHEMA_PARTICIPANTS_V2,
)
from platform_app.participant_delivery_status import (
    SCHEMA_DELIVERY_STATUS,
)
from platform_app.participant_ip_limits import (
    SCHEMA_IP_LIMITS,
)
from platform_app.participant_account_limits import (
    SCHEMA_ACCOUNT_LIMITS,
)

SCHEMA_PARTICIPANTS_COMPLETE = "\n".join((
    SCHEMA_PARTICIPANTS_V2,
    SCHEMA_DELIVERY_STATUS,
    SCHEMA_IP_LIMITS,
    SCHEMA_ACCOUNT_LIMITS,
))


def initialize_participant_schema(connection):
    """Inicializa el esquema completo."""

    if connection.in_transaction:
        raise RuntimeError(
            "No se permite inicializar con una transaccion abierta"
        )

    connection.execute("PRAGMA foreign_keys = ON")

    if connection.execute(
        "PRAGMA foreign_keys"
    ).fetchone()[0] != 1:
        raise RuntimeError(
            "No se pudo activar la comprobacion de relaciones"
        )

    connection.executescript(SCHEMA_PARTICIPANTS_COMPLETE)
