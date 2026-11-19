"""Control transaccional de solicitudes por direccion IP."""

import sqlite3

from platform_app.participant_ip_limits import (
    check_ip_limit,
    record_ip_request,
    normalize_ip,
)


class IPLimitExceeded(Exception):
    """La direccion IP ha alcanzado su limite."""


def register_ip_attempt(connection, ip_address):
    """Comprueba y registra un intento de forma atomica.

    La conexion debe estar fuera de cualquier transaccion.
    El registro se confirma antes de devolver el control.
    """

    ip_address = normalize_ip(ip_address)

    if connection.in_transaction:
        raise RuntimeError(
            "La conexion ya tiene una transaccion abierta"
        )

    try:
        connection.execute("BEGIN IMMEDIATE")

        if not check_ip_limit(connection, ip_address):
            raise IPLimitExceeded(
                "Limite de solicitudes por IP alcanzado"
            )

        record_ip_request(connection, ip_address)

        connection.commit()
        return True

    except Exception:
        connection.rollback()
        raise
