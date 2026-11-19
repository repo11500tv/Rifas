"""Actualizacion administrativa de participantes."""

import re
import sqlite3
import time

from platform_app.participant_admin_audit import record_participant_change


def validate_participant_data(name, email, phone):
    """Normaliza y valida los datos editables."""

    name = " ".join(str(name).split())
    email = str(email).strip().lower()
    phone = re.sub(r"[\s().-]", "", str(phone).strip())

    if not 2 <= len(name) <= 150:
        raise ValueError("El nombre debe tener entre 2 y 150 caracteres")

    if len(email) > 254 or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
    ):
        raise ValueError("Correo electronico no valido")

    if not re.fullmatch(r"\+?[0-9]{9,15}", phone):
        raise ValueError("Telefono movil no valido")

    return name, email, phone


def update_participant(
    connection,
    participant_id,
    admin_id,
    name,
    email,
    phone,
    active,
):
    """Actualiza participante y auditoria atomicamente."""

    if connection.in_transaction:
        raise RuntimeError("La conexion ya tiene una transaccion abierta")

    if type(participant_id) is not int or participant_id <= 0:
        raise ValueError("Identificador de participante invalido")

    if type(admin_id) is not int or admin_id <= 0:
        raise ValueError("Identificador de administrador invalido")

    name, email, phone = validate_participant_data(
        name, email, phone
    )

    if type(active) is not bool:
        raise ValueError("El estado activo debe ser booleano")

    try:
        connection.execute("BEGIN IMMEDIATE")

        admin = connection.execute(
            "SELECT role,active FROM entity_admins WHERE id=?",
            (admin_id,),
        ).fetchone()

        if not admin or admin[0] != "owner" or admin[1] != 1:
            raise PermissionError("Administrador no autorizado")

        participant = connection.execute(
            "SELECT name,email,phone,active "
            "FROM participants WHERE id=?",
            (participant_id,),
        ).fetchone()

        if participant is None:
            raise ValueError("Participante no encontrado")

        old_name, old_email, old_phone, old_active = participant

        changed = []

        if name != old_name:
            changed.append("name")

        if email != old_email:
            changed.append("email")

        if phone != old_phone:
            changed.append("phone")

        if int(active) != old_active:
            changed.append("active")

        if not changed:
            connection.rollback()
            return []

        email_changed = "email" in changed
        phone_changed = "phone" in changed

        connection.execute(
            "UPDATE participants SET "
            "name=?,email=?,phone=?,active=?,"
            "email_verified=CASE WHEN ? THEN 0 "
            "ELSE email_verified END,"
            "phone_verified=CASE WHEN ? THEN 0 "
            "ELSE phone_verified END "
            "WHERE id=?",
            (
                name, email, phone, int(active),
                int(email_changed), int(phone_changed),
                participant_id,
            ),
        )

        if email_changed or phone_changed:
            now = int(time.time())

            # Invalida los codigos pendientes de ambos
            # canales, independientemente de su finalidad.
            connection.execute(
                "UPDATE participant_codes SET used_at=? "
                "WHERE participant_id=? "
                "AND used_at IS NULL",
                (now, participant_id),
            )

        record_participant_change(
            connection,
            participant_id,
            admin_id,
            changed,
        )

        connection.commit()
        return changed

    except sqlite3.IntegrityError as exc:
        connection.rollback()
        raise ValueError(
            "El correo o telefono ya pertenece a otro participante"
        ) from exc

    except Exception:
        connection.rollback()
        raise
