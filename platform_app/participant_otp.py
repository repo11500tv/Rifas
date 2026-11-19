"""Codigos temporales para participantes."""

import hashlib
import hmac
import secrets
import time

CODE_LIFETIME = 300
MAX_ATTEMPTS = 5


def generate_code():
    """Genera un codigo numerico de seis cifras."""
    return f"{secrets.randbelow(1000000):06d}"


def code_digest(secret_key, participant_id, channel, purpose, code):
    """Calcula el HMAC del codigo vinculado a su contexto."""
    message = (
        f"{participant_id}:{channel}:{purpose}:{code}"
    ).encode("utf-8")

    return hmac.new(
        secret_key,
        message,
        hashlib.sha256
    ).hexdigest()


def create_code(db, secret_key, participant_id, channel, purpose):
    """Crea un codigo e invalida los anteriores del mismo tipo."""
    if channel not in ("email", "sms"):
        raise ValueError("Canal no valido")

    if purpose not in ("register", "login", "verify", "recovery"):
        raise ValueError("Finalidad no valida")

    now = int(time.time())
    code = generate_code()

    digest = code_digest(
        secret_key, participant_id, channel, purpose, code
    )

    db.execute(
        "UPDATE participant_codes SET used_at=? "
        "WHERE participant_id=? AND channel=? "
        "AND purpose=? AND used_at IS NULL",
        (now, participant_id, channel, purpose)
    )

    db.execute(
        "INSERT INTO participant_codes "
        "(participant_id,channel,purpose,code_hash,expires_at) "
        "VALUES(?,?,?,?,?)",
        (
            participant_id,
            channel,
            purpose,
            digest,
            now + CODE_LIFETIME
        )
    )

    return code


def verify_code(
    db, secret_key, participant_id, channel, purpose, code
):
    """Comprueba el codigo, su caducidad y sus intentos."""
    if channel not in ("email", "sms"):
        return False

    if purpose not in ("register", "login", "verify", "recovery"):
        return False

    if not isinstance(code, str):
        return False

    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return False

    now = int(time.time())

    row = db.execute(
        "SELECT id,code_hash,expires_at,attempts "
        "FROM participant_codes "
        "WHERE participant_id=? AND channel=? AND purpose=? "
        "AND used_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (participant_id, channel, purpose)
    ).fetchone()

    if row is None:
        return False

    code_id, stored_hash, expires_at, attempts = row

    if expires_at <= now or attempts >= MAX_ATTEMPTS:
        return False

    expected = code_digest(
        secret_key, participant_id, channel, purpose, code
    )

    if hmac.compare_digest(stored_hash, expected):
        result = db.execute(
            "UPDATE participant_codes SET used_at=? "
            "WHERE id=? AND used_at IS NULL AND expires_at>? "
            "AND attempts<?",
            (now, code_id, now, MAX_ATTEMPTS)
        )
        return result.rowcount == 1

    db.execute(
        "UPDATE participant_codes "
        "SET attempts=attempts+1 "
        "WHERE id=? AND used_at IS NULL AND attempts<?",
        (code_id, MAX_ATTEMPTS)
    )

    return False


def create_code_with_id(
    connection,
    secret_key,
    participant_id,
    channel,
    purpose,
):
    """Genera un codigo y devuelve su ID y valor temporal.

    El llamador debe confirmar la transaccion.
    """

    code = create_code(
        connection,
        secret_key,
        participant_id,
        channel,
        purpose,
    )

    row = connection.execute(
        "SELECT id FROM participant_codes "
        "WHERE participant_id=? "
        "AND channel=? "
        "AND purpose=? "
        "AND used_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (participant_id, channel, purpose)
    ).fetchone()

    if row is None:
        raise RuntimeError(
            "No se ha encontrado el codigo generado"
        )

    return row[0], code
