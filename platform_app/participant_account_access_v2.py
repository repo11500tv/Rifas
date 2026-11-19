"""Comprobacion de acceso a cuentas de participantes."""

from platform_app.participant_session_validation import (
    valid_participant_id,
)


def participant_can_access(connection, participant_id):
    """Comprueba si un participante puede acceder a su cuenta.

    La conexion debe corresponder a la entidad solicitada.
    No crea ni modifica sesiones.
    """

    participant_id = valid_participant_id(participant_id)

    if participant_id is None:
        return False

    row = connection.execute(
        "SELECT active,email_verified "
        "FROM participants WHERE id=?",
        (participant_id,)
    ).fetchone()

    if row is None:
        return False

    return (
        row[0] == 1
        and row[1] == 1
    )
