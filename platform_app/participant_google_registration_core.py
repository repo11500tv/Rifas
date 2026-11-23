"""Atomic Google participant registration, called only after verified OIDC ID token.

This module does not validate Google tokens, send SMS, or manage HTTP sessions.
It deliberately rejects existing email/phone accounts: no implicit linking.
"""
import hashlib
import re
import sqlite3

class RegistrationConflict(ValueError):
    """Identity, contact email, or phone already registered."""

class InvalidRegistration(ValueError):
    """Missing or invalid verified registration information."""


def register_verified_google_participant(connection, *, google_subject, google_email,
                                         google_email_verified, name, phone, manage_transaction=True):
    """Register a new participant and bind Google in one SQLite transaction.

    Preconditions: `google_subject`, `google_email`, and verification flag MUST
    originate from an ID token validated by the OIDC client (issuer, audience,
    signature, expiration, nonce and state). Phone is supplied by the user.
    The caller must additionally enforce CSRF, request limits and OIDC flow context.
    """
    if not isinstance(connection, sqlite3.Connection) or (manage_transaction and connection.in_transaction) or (not manage_transaction and not connection.in_transaction):
        raise ValueError('Unexpected SQLite transaction state')
    if not isinstance(google_subject, str) or not 1 <= len(google_subject) <= 255:
        raise InvalidRegistration('Invalid Google subject')
    if google_email_verified is not True:
        raise InvalidRegistration('Google email must be verified')
    if not isinstance(google_email, str):
        raise InvalidRegistration('Invalid email')
    email = google_email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise InvalidRegistration('Invalid email')
    if not isinstance(name, str) or not isinstance(phone, str):
        raise InvalidRegistration('Invalid name or phone')
    name = ' '.join(name.strip().split())
    phone = re.sub(r'[\s().-]', '', phone.strip())
    if not 2 <= len(name) <= 150 or not re.fullmatch(r'\+?[0-9]{9,15}', phone):
        raise InvalidRegistration('Invalid name or phone')
    try:
        if manage_transaction:
            connection.execute('BEGIN IMMEDIATE')
        # This check makes conflicts explicit; UNIQUE constraints handle races.
        if connection.execute('SELECT 1 FROM participants WHERE email=? COLLATE NOCASE OR phone=? LIMIT 1',
                              (email, phone)).fetchone():
            raise RegistrationConflict('Contact details already registered; verify existing account via OTP')
        if connection.execute('SELECT 1 FROM participant_external_identities WHERE provider=? AND provider_subject=?',
                              ('google', google_subject)).fetchone():
            raise RegistrationConflict('Google identity already linked')
        cursor = connection.execute(
            "INSERT INTO participants (name,email,phone,email_verified,phone_verified,preferred_login,active) "
            "VALUES (?,?,?,1,0,'email',1)", (name, email, phone))
        participant_id = cursor.lastrowid
        connection.execute(
            'INSERT INTO participant_external_identities (participant_id,provider,provider_subject) VALUES (?,?,?)',
            (participant_id, 'google', google_subject))
        connection.execute(
            'INSERT INTO participant_google_audit (participant_id,action,subject_fingerprint) VALUES (?,?,?)',
            (participant_id, 'link', hashlib.sha256(google_subject.encode('utf-8')).hexdigest()))
        if manage_transaction:
            connection.commit()
        return participant_id
    except sqlite3.IntegrityError as exc:
        if manage_transaction:
            connection.rollback()
        raise RegistrationConflict('Participant or identity conflict') from exc
    except BaseException:
        if manage_transaction:
            connection.rollback()
        raise
