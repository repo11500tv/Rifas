"""Validacion estricta de identificadores de participantes."""


def valid_participant_id(value):
    """Devuelve un entero positivo valido o None."""
    if type(value) is not int:
        return None

    if value <= 0:
        return None

    if value > 9223372036854775807:
        return None

    return value
