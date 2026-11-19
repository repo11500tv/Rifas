"""Limites de solicitudes OTP por participante."""

import time

WINDOW_15_MIN = 15 * 60
LIMIT_15_MIN = 5

WINDOW_1_HOUR = 60 * 60
LIMIT_1_HOUR = 10

WINDOW_24_HOURS = 24 * 60 * 60
LIMIT_24_HOURS = 20


SCHEMA_ACCOUNT_LIMITS = """
CREATE TABLE IF NOT EXISTS participant_account_otp_requests (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL
        REFERENCES participants(id),
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_participant_account_otp_requests
ON participant_account_otp_requests(
    participant_id, created_at
);
"""


def validate_participant_id(participant_id):
    """Comprueba que el identificador sea valido."""

    if (
        not isinstance(participant_id, int)
        or isinstance(participant_id, bool)
        or participant_id <= 0
    ):
        raise ValueError(
            "Identificador de participante invalido"
        )

    return participant_id


def check_account_limit(connection, participant_id, now=None):
    """Comprueba los limites de solicitudes del participante."""

    participant_id = validate_participant_id(participant_id)

    if now is None:
        now = int(time.time())

    limits = (
        (WINDOW_15_MIN, LIMIT_15_MIN),
        (WINDOW_1_HOUR, LIMIT_1_HOUR),
        (WINDOW_24_HOURS, LIMIT_24_HOURS),
    )

    for window, maximum in limits:
        count = connection.execute(
            "SELECT COUNT(*) "
            "FROM participant_account_otp_requests "
            "WHERE participant_id=? AND created_at>?",
            (participant_id, now - window)
        ).fetchone()[0]

        if count >= maximum:
            return False

    return True


def record_account_request(connection, participant_id, now=None):
    """Registra un intento de solicitud del participante."""

    participant_id = validate_participant_id(participant_id)

    if now is None:
        now = int(time.time())

    connection.execute(
        "INSERT INTO participant_account_otp_requests "
        "(participant_id,created_at) VALUES(?,?)",
        (participant_id, now)
    )


def cleanup_old_account_requests(connection, now=None):
    """Elimina registros anteriores a 24 horas."""

    if now is None:
        now = int(time.time())

    connection.execute(
        "DELETE FROM participant_account_otp_requests "
        "WHERE created_at<=?",
        (now - WINDOW_24_HOURS,)
    )
