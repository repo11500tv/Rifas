"""Contexto de autorización Google vinculado a sesión, entidad y operación.

La validación criptográfica de ID Token, nonce y state OAuth corresponde a Authlib.
"""
import re
import secrets
import time

KEY = '_google_oidc_pending'
TTL = 300
OPERATIONS = frozenset({'login', 'register', 'link', 'replace'})


def begin_flow(session, slug, operation, participant_id=None, now=None):
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,49}", slug):
        raise ValueError('Entidad no válida')
    if operation not in OPERATIONS:
        raise ValueError('Operación no válida')
    if operation in ('link', 'replace'):
        if type(participant_id) is not int or participant_id <= 0 or session.get('participant_slug') != slug or session.get('participant_id') != participant_id:
            raise PermissionError('Se requiere sesión de participante en la misma entidad')
    elif participant_id is not None:
        raise ValueError('No aceptar participante para login/registro')
    now = int(time.time() if now is None else now)
    for key in tuple(session):
        if key.startswith("_state_google_"):
            session.pop(key, None)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    session[KEY] = {'slug': slug, 'operation': operation, 'participant_id': participant_id,
                    'state': state, 'nonce': nonce, 'expires': now + TTL}
    return state, nonce


def valid_flow(session, slug, state, now=None):
    """Inspección sin efectos laterales: state erróneo no destruye un flujo legítimo."""
    data = session.get(KEY)
    now = int(time.time() if now is None else now)
    if not isinstance(data, dict) or not isinstance(state, str) or not state.isascii() or len(state) > 128:
        return None
    expires = data.get('expires')
    if type(expires) is not int or expires <= now or data.get('slug') != slug:
        return None
    stored_state = data.get('state')
    if not isinstance(stored_state, str) or not secrets.compare_digest(stored_state, state):
        return None
    operation = data.get('operation')
    if operation not in OPERATIONS:
        return None
    if operation in ('link', 'replace'):
        participant_id = data.get('participant_id')
        if type(participant_id) is not int or participant_id <= 0 or session.get('participant_slug') != slug or session.get('participant_id') != participant_id:
            return None
    elif data.get('participant_id') is not None:
        return None
    nonce = data.get('nonce')
    if not isinstance(nonce, str) or not nonce:
        return None
    return {'operation': operation, 'participant_id': data.get('participant_id'), 'nonce': nonce}


def consume_flow(session, slug, state, now=None):
    """Solo consume un contexto válido, antes del intercambio de tokens."""
    result = valid_flow(session, slug, state, now=now)
    if result is not None:
        session.pop(KEY, None)
    return result
