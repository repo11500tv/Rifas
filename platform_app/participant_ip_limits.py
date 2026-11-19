"""Limites de solicitudes de codigos por direccion IP."""

import ipaddress
import time

SHORT_WINDOW = 15 * 60
SHORT_LIMIT = 5

LONG_WINDOW = 60 * 60
LONG_LIMIT = 10


SCHEMA_IP_LIMITS = """
CREATE TABLE IF NOT EXISTS participant_otp_requests (
    id INTEGER PRIMARY KEY,
    ip_address TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_participant_otp_requests_ip_time
ON participant_otp_requests(ip_address, created_at);
"""


def normalize_ip(ip_address):
    """Valida y normaliza una direccion IPv4 o IPv6."""
    return str(ipaddress.ip_address(ip_address))


def check_ip_limit(connection, ip_address, now=None):
    """Indica si una IP puede realizar otra solicitud."""

    ip_address = normalize_ip(ip_address)

    if now is None:
        now = int(time.time())

    short_count = connection.execute(
        "SELECT COUNT(*) FROM participant_otp_requests "
        "WHERE ip_address=? AND created_at>?",
        (ip_address, now - SHORT_WINDOW)
    ).fetchone()[0]

    long_count = connection.execute(
        "SELECT COUNT(*) FROM participant_otp_requests "
        "WHERE ip_address=? AND created_at>?",
        (ip_address, now - LONG_WINDOW)
    ).fetchone()[0]

    return (
        short_count < SHORT_LIMIT
        and long_count < LONG_LIMIT
    )


def record_ip_request(connection, ip_address, now=None):
    """Registra una solicitud de codigo temporal."""

    ip_address = normalize_ip(ip_address)

    if now is None:
        now = int(time.time())

    connection.execute(
        "INSERT INTO participant_otp_requests "
        "(ip_address,created_at) VALUES(?,?)",
        (ip_address, now)
    )


def cleanup_old_requests(connection, now=None):
    """Elimina registros anteriores a la ventana de control."""

    if now is None:
        now = int(time.time())

    connection.execute(
        "DELETE FROM participant_otp_requests "
        "WHERE created_at<=?",
        (now - LONG_WINDOW,)
    )
