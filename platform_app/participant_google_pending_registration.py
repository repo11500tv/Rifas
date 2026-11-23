"""Server-side pending OIDC registration. Never accept subject/email from browser POST.

Caller MUST validate OIDC ID token (issuer, signature, audience, nonce, expiry),
verify email_verified=True and validate its own OAuth state before calling start().
The random handle is stored in Flask session; only a digest lives in SQLite.
"""
import hashlib
import secrets
import time

class PendingRegistrationInvalid(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def start(connection, *, subject, email, email_verified, name, session_binding, now=None):
    if email_verified is not True or not all(isinstance(v, str) and v.strip() for v in (subject, email, name, session_binding)):
        raise PendingRegistrationInvalid('Invalid verified claims or session binding')
    if len(subject)>255 or len(email)>254 or len(name)>150 or len(session_binding)>255:
        raise PendingRegistrationInvalid('Oversized claims')
    handle = secrets.token_urlsafe(32)
    now = int(time.time() if now is None else now)
    # En cada alta se retiran los intentos caducados de esta entidad.
    with connection:
        connection.execute("DELETE FROM participant_google_pending_registration WHERE expires_at<=?", (now,))
        connection.execute(
            "INSERT INTO participant_google_pending_registration "
            "(handle_digest,google_subject,google_email,google_name,session_binding,expires_at) "
            "VALUES (?,?,?,?,?,?)", (_digest(handle), subject, email, name, _digest(session_binding), now + 300),
        )
    return handle


def finish(connection, *, handle, session_binding, phone, now=None):
    """Consume pending claims and create participant atomically on one connection."""
    from .participant_google_registration_core import register_verified_google_participant
    if not isinstance(handle,str) or len(handle)<32 or not isinstance(session_binding,str):
        raise PendingRegistrationInvalid('Invalid handle')
    if connection.in_transaction:
        raise ValueError('Expected clean connection')
    now = int(time.time() if now is None else now)
    try:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT id,google_subject,google_email,google_name,session_binding,expires_at '
                                 'FROM participant_google_pending_registration WHERE handle_digest=?',(_digest(handle),)).fetchone()
        if row is None or row[5] <= now or not secrets.compare_digest(row[4],_digest(session_binding)):
            raise PendingRegistrationInvalid('Expired, missing or foreign pending registration')
        # register_verified_google_participant normally owns its transaction;
        # here it runs as a nested logical unit in the caller's transaction.
        participant_id = register_verified_google_participant(connection,google_subject=row[1],google_email=row[2],
                              google_email_verified=True,name=row[3],phone=phone,manage_transaction=False)
        connection.execute('DELETE FROM participant_google_pending_registration WHERE id=?',(row[0],))
        connection.commit()
        return participant_id
    except BaseException:
        connection.rollback()
        raise
