"""Configuración SMTP independiente por entidad."""

from pathlib import Path

from cryptography.fernet import Fernet


SMTP_KEYS = (
    "smtp_host",
    "smtp_port",
    "smtp_security",
    "smtp_username",
    "smtp_sender",
    "smtp_sender_name",
    "smtp_password_encrypted",
)


def encryption_key_path():
    """Ruta de la clave exclusiva de esta instalación."""
    return (
        Path(__file__).resolve().parent.parent
        / "central"
        / "smtp_encryption.key"
    )


def cipher():
    """Obtiene el cifrador de la instalación."""
    key = encryption_key_path().read_bytes()
    return Fernet(key)


def encrypt_password(password):
    """Cifra una contraseña SMTP antes de guardarla."""
    if not isinstance(password, str):
        raise ValueError("La contraseña debe ser texto")

    if not password:
        return ""

    return cipher().encrypt(
        password.encode("utf-8")
    ).decode("ascii")


def decrypt_password(encrypted):
    """Descifra una contraseña SMTP almacenada."""
    if not encrypted:
        return ""

    return cipher().decrypt(
        encrypted.encode("ascii")
    ).decode("utf-8")


def read_settings(connection):
    """Lee los ajustes SMTP de una entidad."""
    rows = connection.execute(
        "SELECT key, value FROM entity_settings "
        "WHERE key IN ({})".format(
            ",".join("?" for _ in SMTP_KEYS)
        ),
        SMTP_KEYS,
    ).fetchall()

    settings = {key: "" for key in SMTP_KEYS}

    for row in rows:
        settings[row[0]] = row[1]

    return settings


def save_settings(connection, settings):
    """Guarda los ajustes SMTP de una entidad."""
    for key in SMTP_KEYS:
        if key not in settings:
            continue

        connection.execute(
            "INSERT INTO entity_settings(key,value) "
            "VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, settings[key]),
        )


def get_smtp_config(connection):
    """Devuelve la configuración necesaria para el envío."""
    settings = read_settings(connection)

    return {
        "host": settings["smtp_host"],
        "port": int(settings["smtp_port"] or "465"),
        "security": settings["smtp_security"] or "ssl",
        "username": settings["smtp_username"],
        "sender": settings["smtp_sender"],
        "sender_name": settings["smtp_sender_name"],
        "password": decrypt_password(
            settings["smtp_password_encrypted"]
        ),
    }
