"""Auditoria de modificaciones administrativas de participantes."""

import json


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS participant_admin_changes (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    changed_fields TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (participant_id)
        REFERENCES participants(id),
    FOREIGN KEY (admin_id)
        REFERENCES entity_admins(id)
)
"""


ALLOWED_FIELDS = frozenset({
    "name",
    "email",
    "phone",
    "active",
})


def record_participant_change(
    connection,
    participant_id,
    admin_id,
    changed_fields,
):
    """Registra un cambio dentro de la transaccion del llamador.

    No realiza commit: la modificacion y su auditoria
    deben confirmarse o revertirse conjuntamente.
    """
    if not connection.in_transaction:
        raise RuntimeError(
            "Se requiere una transaccion activa"
        )

    if type(participant_id) is not int or participant_id <= 0:
        raise ValueError("Participante invalido")

    if type(admin_id) is not int or admin_id <= 0:
        raise ValueError("Administrador invalido")

    fields = set(changed_fields)

    if not fields or not fields.issubset(ALLOWED_FIELDS):
        raise ValueError("Campos modificados invalidos")

    connection.execute(
        "INSERT INTO participant_admin_changes "
        "(participant_id,admin_id,changed_fields) "
        "VALUES (?,?,?)",
        (
            participant_id,
            admin_id,
            json.dumps(sorted(fields)),
        ),
    )
