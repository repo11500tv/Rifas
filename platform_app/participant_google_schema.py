"""Persistencia de identidades Google por entidad (versión 2.4.2).

No almacena tokens de Google. La identidad estable es (provider, subject).
"""
import sqlite3

GOOGLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS participant_external_identities (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL CHECK(provider='google'),
    provider_subject TEXT NOT NULL CHECK(length(provider_subject) BETWEEN 1 AND 255),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, provider_subject),
    UNIQUE(participant_id, provider)
);
CREATE INDEX IF NOT EXISTS idx_external_identities_participant
ON participant_external_identities(participant_id);
CREATE TABLE IF NOT EXISTS participant_google_audit (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    action TEXT NOT NULL CHECK(action IN ('link','replace','unlink')),
    subject_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS participant_google_authorizations (
    id INTEGER PRIMARY KEY,
    participant_id INTEGER NOT NULL REFERENCES participants(id),
    purpose TEXT NOT NULL CHECK(purpose IN ('link','replace')),
    context_digest TEXT NOT NULL UNIQUE,
    code_digest TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
    used_at INTEGER,
    delivery_status TEXT NOT NULL DEFAULT 'pending'
        CHECK(delivery_status IN ('pending','accepted','failed','uncertain')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_google_authorizations_lookup
ON participant_google_authorizations(participant_id,purpose,expires_at);

CREATE TABLE IF NOT EXISTS participant_google_pending_registration (
 id INTEGER PRIMARY KEY,
 handle_digest TEXT NOT NULL UNIQUE,
 google_subject TEXT NOT NULL,
 google_email TEXT NOT NULL,
 google_name TEXT NOT NULL,
 session_binding TEXT NOT NULL,
 expires_at INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_google_pending_expiry ON participant_google_pending_registration(expires_at);
"""

REQUIRED_TABLES = (
    'participant_external_identities',
    'participant_google_audit',
    'participant_google_authorizations',
    'participant_google_pending_registration',
)

MODULE = "google_oidc"
VERSION = "2.4.2"
REQUIRED_PARTICIPANT_COLUMNS = {
    "id", "name", "email", "phone", "email_verified", "phone_verified",
    "preferred_login", "active",
}


def check_tables(connection):
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_schema WHERE type='table'"
    )}
    if not set(REQUIRED_TABLES).issubset(tables):
        raise RuntimeError("Faltan tablas de identidad Google")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(participants)")}
    if not REQUIRED_PARTICIPANT_COLUMNS <= columns:
        raise RuntimeError("El esquema de participantes no admite Google 2.4.2")


def validate_google_schema(connection):
    check_tables(connection)
    versions = connection.execute("SELECT version FROM module_versions WHERE module=?", (MODULE,)).fetchall()
    if len(versions) != 1 or versions[0][0] != VERSION:
        raise RuntimeError("Falta la migración Google 2.4.2")


def migrate_google_schema(connection):
    """Actualizar datos de entidad y plantilla con el mismo contrato."""
    if not isinstance(connection, sqlite3.Connection) or connection.in_transaction:
        raise ValueError("Se requiere una conexión SQLite sin transacción activa")
    connection.execute("PRAGMA foreign_keys=ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("No se pudieron activar las claves externas")
    try:
        # executescript confirma de forma implícita antes de ejecutar; BEGIN
        # dentro del script mantiene DDL y marcador en una sola transacción.
        connection.executescript("BEGIN IMMEDIATE;\n" + GOOGLE_SCHEMA)
        check_tables(connection)
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Relaciones SQLite inconsistentes")
        connection.execute(
            "INSERT INTO module_versions(module,version,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
            "ON CONFLICT(module) DO UPDATE SET version=excluded.version, updated_at=CURRENT_TIMESTAMP "
            "WHERE module_versions.version=excluded.version", (MODULE, VERSION),
        )
        validate_google_schema(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
