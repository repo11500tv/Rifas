"""Clasificacion conservadora de resultados SMTP."""

import smtplib


def classify_smtp_exception(exc):
    """Clasifica errores SMTP, incluidos los encapsulados.

    Solo se considera fallo confirmado un rechazo explicito
    de todos los destinatarios. Ante cualquier duda,
    el resultado es incierto.
    """

    actual = exc
    visitados = set()

    for _ in range(5):
        if actual is None or id(actual) in visitados:
            break

        visitados.add(id(actual))

        if isinstance(
            actual, smtplib.SMTPRecipientsRefused
        ):
            return "failed"

        actual = getattr(actual, "__cause__", None)

    return "uncertain"


def classify_smtp_result(error=None):
    """Devuelve accepted, failed o uncertain.

    Sin excepcion, se considera aceptacion SMTP.
    """

    if error is None:
        return "accepted"

    return classify_smtp_exception(error)
