"""Estado provisional de acceso de participantes."""

import time

from platform_app.participant_session_validation import (
    valid_participant_id,
)

PENDING_LOGIN_LIFETIME = 300

PENDING_KEYS = (
    "pending_participant_slug",
    "pending_participant_id",
    "pending_participant_expires",
)


def clear_pending_login(session):
    """Elimina exclusivamente el estado de acceso pendiente."""
    for key in PENDING_KEYS:
        session.pop(key, None)


def start_pending_login(session, slug, participant_id):
    """Guarda la identidad pendiente sin autenticar al participante."""

    participant_id = valid_participant_id(participant_id)

    if (
        participant_id is None
        or not isinstance(slug, str)
        or not slug
        or len(slug) > 100
    ):
        raise ValueError("Identidad pendiente no valida")

    clear_pending_login(session)

    session["pending_participant_slug"] = slug
    session["pending_participant_id"] = participant_id
    session["pending_participant_expires"] = (
        int(time.time()) + PENDING_LOGIN_LIFETIME
    )


def get_pending_login(session, slug):
    """Devuelve el ID pendiente solo para su entidad y plazo."""

    if (
        not isinstance(slug, str)
        or session.get("pending_participant_slug") != slug
    ):
        return None

    participant_id = valid_participant_id(
        session.get("pending_participant_id")
    )

    expires = session.get("pending_participant_expires")

    if (
        participant_id is None
        or type(expires) is not int
        or expires <= int(time.time())
    ):
        clear_pending_login(session)
        return None

    return participant_id


def finish_pending_login(session, slug, participant_id):
    """Finaliza el estado pendiente tras verificar el codigo.

    Esta funcion NO verifica codigos. El llamador debe haber
    ejecutado confirm_login_code satisfactoriamente.
    """

    pending_id = get_pending_login(session, slug)

    if pending_id is None or pending_id != participant_id:
        return False

    # Replace only the participant identity, retaining other authenticated roles.
    clear_pending_login(session)
    session["participant_slug"] = slug
    session["participant_id"] = participant_id
    session["_activity_participant"] = int(time.time())

    return True
