"""Mensajes publicos seguros del registro de participantes."""

MESSAGES = {
    "accepted": (
        "Si la solicitud es valida, recibiras un codigo "
        "en tu correo electronico."
    ),
    "resend_too_soon": (
        "Espera unos segundos antes de solicitar otro codigo."
    ),
    "rate_limited": (
        "Has realizado demasiadas solicitudes. "
        "Intentalo mas tarde."
    ),
    "delivery_error": (
        "No hemos podido completar el envio. "
        "Intentalo mas tarde."
    ),
    "unexpected_error": (
        "No hemos podido completar la operacion. "
        "Intentalo mas tarde."
    ),
}


def public_registration_message(status):
    """Devuelve exclusivamente mensajes publicos predefinidos."""

    if not isinstance(status, str):
        return MESSAGES["unexpected_error"]

    return MESSAGES.get(
        status,
        MESSAGES["unexpected_error"]
    )
