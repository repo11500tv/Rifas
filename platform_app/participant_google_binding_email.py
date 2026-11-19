"""Servicio de envío OTP de vinculación Google usando el SMTP existente de la entidad.

El llamante debe verificar sesión, entidad, identidad OIDC y CSRF, y construir el
context_digest en el servidor. No expone una ruta ni almacena códigos en claro.
"""
import time

from platform_app.participant_google_binding_core import issue_authorization, mark_delivery
from platform_app.participant_combined_guard import register_combined_attempt
from platform_app.entity_mailer import send_entity_email


class GoogleBindingResendTooSoon(Exception):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__('Debe esperar antes de solicitar otro código')


MIN_RESEND_SECONDS = 60


def request_google_binding_code(connection, *, secret, participant_id, purpose,
                                context_digest, ip_address, now=None):
    """Emite, envía y confirma aceptación SMTP; devuelve True o propaga error.

    El limitador de IP/cuenta existente registra el intento incluso ante error SMTP.
    Nunca se considera aceptado un envío incierto o fallido.
    """
    now = int(time.time()) if now is None else int(now)
    register_combined_attempt(connection, participant_id, ip_address)
    if connection.in_transaction:
        raise RuntimeError('Transacción inesperada tras limitador')

    # No revelar destinatarios al navegador; obtenerlo de la cuenta ya autenticada.
    row = connection.execute(
        'SELECT email FROM participants WHERE id=? AND active=1 AND email_verified=1',
        (participant_id,),
    ).fetchone()
    if row is None:
        raise ValueError('Cuenta no autorizada')
    destination = row[0]

    # Evitar reenvíos repetidos, incluso si el primer correo falló. Para reintentar,
    # iniciar un nuevo flujo con un nuevo context_digest tras el intervalo.
    previous = connection.execute(
        'SELECT created_at FROM participant_google_authorizations '
        'WHERE participant_id=? AND purpose=? ORDER BY id DESC LIMIT 1',
        (participant_id, purpose),
    ).fetchone()
    if previous is not None:
        # created_at es CURRENT_TIMESTAMP de SQLite; convertir con strftime.
        latest = connection.execute(
            'SELECT CAST(strftime("%s", ?) AS INTEGER)', (previous[0],)
        ).fetchone()[0]
        if latest is not None and now - latest < MIN_RESEND_SECONDS:
            raise GoogleBindingResendTooSoon(MIN_RESEND_SECONDS - (now - latest))

    authorization_id, code = issue_authorization(
        connection, secret=secret, participant_id=participant_id,
        purpose=purpose, context_digest=context_digest, now=now,
    )
    subject = 'Código de seguridad — Rifas Benéficas'
    body = (
        'Has solicitado vincular o sustituir una cuenta Google.\n\n'
        f'Tu código de seguridad es: {code}\n\n'
        'Caduca en 5 minutos y solo puede utilizarse una vez.\n'
        'Si no has solicitado esta operación, ignora este mensaje.\n'
    )
    try:
        send_entity_email(connection, destination, subject, body)
    except Exception:
        # Fail closed. No se marca aceptado ante error o aceptación incierta.
        mark_delivery(connection, authorization_id, False)
        raise
    if not mark_delivery(connection, authorization_id, True):
        raise RuntimeError('No se pudo confirmar el estado de entrega OTP')
    return True
