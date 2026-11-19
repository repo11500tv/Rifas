"""Seguimiento de resultados de envio de codigos OTP."""

SCHEMA_DELIVERY_STATUS = """
CREATE TABLE IF NOT EXISTS participant_code_deliveries (
    id INTEGER PRIMARY KEY,
    code_id INTEGER NOT NULL UNIQUE
        REFERENCES participant_codes(id),
    status TEXT NOT NULL
        CHECK(status IN (
            'pending',
            'accepted',
            'failed',
            'uncertain'
        )),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_participant_code_deliveries_status
ON participant_code_deliveries(status);
"""


def create_delivery_record(connection, code_id):
    """Crea el estado pendiente para un codigo concreto."""

    connection.execute(
        "INSERT INTO participant_code_deliveries "
        "(code_id,status) VALUES(?,?)",
        (code_id, "pending")
    )


def update_delivery_status(connection, code_id, status):
    """Actualiza el estado de entrega de un codigo."""

    if status not in ("accepted", "failed", "uncertain"):
        raise ValueError("Estado de entrega invalido")

    result = connection.execute(
        "UPDATE participant_code_deliveries "
        "SET status=?, updated_at=CURRENT_TIMESTAMP "
        "WHERE code_id=? AND status='pending'",
        (status, code_id)
    )

    return result.rowcount == 1


def get_delivery_status(connection, code_id):
    """Consulta el estado de entrega de un codigo."""

    row = connection.execute(
        "SELECT status FROM participant_code_deliveries "
        "WHERE code_id=?",
        (code_id,)
    ).fetchone()

    return row[0] if row else None


def failed_delivery_allows_retry(connection, code_id):
    """Solo un fallo confirmado permite omitir la espera."""

    return get_delivery_status(
        connection, code_id
    ) == "failed"
