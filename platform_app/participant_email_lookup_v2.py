"""Identificacion de participantes por correo."""

import re


def normalize_email(email):
    if not isinstance(email, str):
        return None

    email = email.strip().lower()

    if len(email) > 254 or not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+",
        email
    ):
        return None

    return email


def find_eligible_participant(connection, email):
    """Devuelve el ID de una cuenta habilitada o None.

    La conexion debe pertenecer a la hermandad actual.
    """

    normalized = normalize_email(email)

    if normalized is None:
        return None

    row = connection.execute(
        "SELECT id FROM participants "
        "WHERE email=? "
        "AND active=1 "
        "AND email_verified=1",
        (normalized,)
    ).fetchone()

    return row[0] if row else None
