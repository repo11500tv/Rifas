"""Traduccion segura de errores para participantes."""

from platform_app.participant_public_messages import (
    public_registration_message,
)
from platform_app.participant_registration_service import (
    RegistrationResendTooSoon,
)
from platform_app.participant_combined_guard import (
    CombinedLimitExceeded,
)
from platform_app.entity_mailer import EntityMailError


def registration_error_status(error):
    """Clasifica excepciones sin revelar datos internos."""

    if isinstance(error, RegistrationResendTooSoon):
        return "resend_too_soon"

    if isinstance(error, CombinedLimitExceeded):
        return "rate_limited"

    if isinstance(error, EntityMailError):
        return "delivery_error"

    return "unexpected_error"


def registration_error_message(error):
    """Devuelve exclusivamente un mensaje publico seguro."""

    return public_registration_message(
        registration_error_status(error)
    )


def registration_success_message():
    """Mensaje generico para una solicitud aceptada."""

    return public_registration_message("accepted")
