"""Finalizacion compartida de sesion de participante, sin dependencia HTTP.

Solo llamar DESPUES de verificar OTP o identidad OIDC criptograficamente.
No constituye por si mismo un mecanismo de autenticacion.
"""
import time

from platform_app.participant_pending_login import clear_pending_login


def clear_participant_flows(session):
    clear_pending_login(session)
    for key in tuple(session):
        if key in {
            "_google_oidc_pending", "_google_binding_pending",
            "_google_registration_handle", "_google_registration_binding",
        } or key.startswith("_state_google_"):
            session.pop(key, None)


def finish_verified_participant_session(session, connection, slug, participant_id, *, now=None):
    """Establece la sesion local tras autenticar y autorizar la cuenta.

    El controlador debe haber comprobado previamente la entidad activa y el
    factor de autenticacion. No elimina otras identidades administrativas.
    """
    if not isinstance(slug, str) or not slug or len(slug) > 100:
        raise ValueError('Entidad invalida')
    if type(participant_id) is not int or not 0 < participant_id <= 9223372036854775807:
        raise ValueError('Identificador de participante invalido')
    timestamp = int(time.time()) if now is None else now
    if type(timestamp) is not int:
        raise ValueError('Tiempo invalido')
    row = connection.execute(
        'SELECT active,email_verified FROM participants WHERE id=?', (participant_id,)
    ).fetchone()
    if row is None or tuple(row) != (1, 1):
        raise PermissionError('Participante sin acceso autorizado')
    clear_participant_flows(session)
    session['participant_slug'] = slug
    session['participant_id'] = participant_id
    session['_activity_participant'] = timestamp
    return participant_id
