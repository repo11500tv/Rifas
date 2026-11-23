"""Google OIDC login: identity resolution only, never implicit account linking.

The caller MUST pass a subject from a cryptographically verified OIDC ID token.
"""
import sqlite3


class GoogleIdentityNotLinked(Exception):
    pass


class GoogleIdentityNotEligible(Exception):
    pass


def resolve_verified_google_login(connection, subject):
    if not isinstance(subject, str) or not (1 <= len(subject) <= 255):
        raise ValueError('OIDC subject invalid')
    if not isinstance(connection, sqlite3.Connection):
        raise TypeError('SQLite connection required')
    row = connection.execute(
        "SELECT p.id, p.active, p.email_verified "
        "FROM participant_external_identities i "
        "JOIN participants p ON p.id=i.participant_id "
        "WHERE i.provider='google' AND i.provider_subject=?", (subject,)
    ).fetchone()
    if row is None:
        raise GoogleIdentityNotLinked()
    if row[1] != 1 or row[2] != 1:
        raise GoogleIdentityNotEligible()
    return int(row[0])
