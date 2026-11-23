"""Vinculación Google con OTP específico, atómica y compatible con GOOGLE_SCHEMA.

El llamante DEBE verificar previamente el ID token OIDC y la sesión del participante.
No expone rutas HTTP, no envía correos y no almacena secretos ni tokens Google.
"""
import hashlib
import hmac
import secrets
import sqlite3
import time

PURPOSES = {'link', 'replace'}
MAX_ATTEMPTS = 5
TTL = 300


def _validate(secret, participant_id, purpose, context_digest):
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError('Clave OTP inválida')
    if type(participant_id) is not int or participant_id <= 0 or purpose not in PURPOSES:
        raise ValueError('Operación inválida')
    if not isinstance(context_digest, str) or len(context_digest) != 64 or any(c not in '0123456789abcdef' for c in context_digest):
        raise ValueError('Contexto inválido')


def _code_digest(secret, participant_id, purpose, context_digest, code):
    message = '\x00'.join((str(participant_id), purpose, context_digest, code)).encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def issue_authorization(connection, *, secret, participant_id, purpose, context_digest, now=None):
    """Emite código pendiente de entrega. El llamante envía el correo y marca su resultado.

    Devuelve (id, código). NUNCA registrar el código en logs.
    """
    _validate(secret, participant_id, purpose, context_digest)
    if connection.in_transaction:
        raise RuntimeError('Transacción previa')
    now = int(time.time()) if now is None else now
    code = f'{secrets.randbelow(1000000):06d}'
    try:
        connection.execute('BEGIN IMMEDIATE')
        if not connection.execute('SELECT 1 FROM participants WHERE id=? AND active=1 AND email_verified=1', (participant_id,)).fetchone():
            raise ValueError('Participante no autorizado')
        # Una nueva emisión invalida autorizaciones previas del mismo contexto.
        connection.execute("UPDATE participant_google_authorizations SET used_at=? WHERE participant_id=? AND purpose=? AND used_at IS NULL", (now, participant_id, purpose))
        cursor = connection.execute('INSERT INTO participant_google_authorizations '
            '(participant_id,purpose,context_digest,code_digest,expires_at) VALUES (?,?,?,?,?)',
            (participant_id,purpose,context_digest,_code_digest(secret,participant_id,purpose,context_digest,code),now+TTL))
        connection.commit()
        return cursor.lastrowid, code
    except BaseException:
        connection.rollback()
        raise


def mark_delivery(connection, authorization_id, accepted):
    if type(authorization_id) is not int or authorization_id <= 0 or type(accepted) is not bool:
        raise ValueError('Resultado inválido')
    if connection.in_transaction:
        raise RuntimeError('Transacción previa')
    status = 'accepted' if accepted else 'failed'
    cursor = connection.execute("UPDATE participant_google_authorizations SET delivery_status=? "
        "WHERE id=? AND delivery_status='pending' AND used_at IS NULL", (status,authorization_id))
    connection.commit()
    return cursor.rowcount == 1


def bind_verified_identity(connection, *, secret, participant_id, purpose, context_digest,
                           code, verified_google_subject, now=None):
    """OTP + identidad + auditoría en una sola transacción; sujeto OIDC ya verificado.

    Solo se invoca después de comprobar sesión Flask, entidad y flujo OIDC.
    """
    _validate(secret, participant_id, purpose, context_digest)
    if not isinstance(verified_google_subject, str) or not 1 <= len(verified_google_subject) <= 255:
        raise ValueError('Identidad OIDC inválida')
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        return 'invalid_code'
    if connection.in_transaction:
        raise RuntimeError('Transacción previa')
    now = int(time.time()) if now is None else now
    try:
        connection.execute('BEGIN IMMEDIATE')
        if not connection.execute('SELECT 1 FROM participants WHERE id=? AND active=1 AND email_verified=1', (participant_id,)).fetchone():
            connection.rollback()
            return 'not_authorized'
        row = connection.execute('SELECT id,code_digest FROM participant_google_authorizations '
            'WHERE participant_id=? AND purpose=? AND context_digest=? AND used_at IS NULL '
            "AND delivery_status='accepted' AND expires_at>? AND attempts<? LIMIT 1",
            (participant_id,purpose,context_digest,now,MAX_ATTEMPTS)).fetchone()
        if row is None:
            connection.rollback()
            return 'invalid_code'
        if not hmac.compare_digest(row[1],_code_digest(secret,participant_id,purpose,context_digest,code)):
            connection.execute('UPDATE participant_google_authorizations SET attempts=attempts+1 WHERE id=?', (row[0],))
            connection.commit()
            return 'invalid_code'
        current = connection.execute("SELECT provider_subject FROM participant_external_identities WHERE participant_id=? AND provider='google'", (participant_id,)).fetchone()
        if purpose == 'link' and current is not None:
            connection.rollback()
            return 'already_linked'
        if purpose == 'replace' and current is None:
            connection.rollback()
            return 'not_linked'
        owner = connection.execute("SELECT participant_id FROM participant_external_identities WHERE provider='google' AND provider_subject=?", (verified_google_subject,)).fetchone()
        if owner is not None and owner[0] != participant_id:
            connection.rollback()
            return 'already_linked_elsewhere'
        if current is not None and current[0] == verified_google_subject:
            connection.rollback()
            return 'unchanged'
        if current is None:
            connection.execute("INSERT INTO participant_external_identities(participant_id,provider,provider_subject) VALUES(?,'google',?)", (participant_id,verified_google_subject))
        else:
            connection.execute("UPDATE participant_external_identities SET provider_subject=?,updated_at=CURRENT_TIMESTAMP WHERE participant_id=? AND provider='google'", (verified_google_subject,participant_id))
        connection.execute('INSERT INTO participant_google_audit(participant_id,action,subject_fingerprint) VALUES(?,?,?)',
                           (participant_id,purpose,hashlib.sha256(verified_google_subject.encode()).hexdigest()))
        if connection.execute('UPDATE participant_google_authorizations SET used_at=? WHERE id=? AND used_at IS NULL', (now,row[0])).rowcount != 1:
            raise RuntimeError('Autorización ya utilizada')
        connection.commit()
        return purpose
    except BaseException:
        connection.rollback()
        raise
