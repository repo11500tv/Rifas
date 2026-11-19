"""Registro definitivo y transaccional de adjudicaciones."""

from datetime import datetime
import sqlite3

from platform_app.raffle_draw_calculator import (
    calculate_winning_number
)


class DrawFinalizationError(ValueError):
    pass


class DrawAlreadyRecorded(DrawFinalizationError):
    pass


def validate_official_data(
    official_result,
    official_source,
    official_draw_at,
):
    official_result = str(official_result).strip()
    official_source = str(official_source).strip()
    official_draw_at = str(official_draw_at).strip()

    if not official_source or len(official_source) > 1000:
        raise DrawFinalizationError(
            "La fuente oficial es obligatoria "
            "y no puede superar 1000 caracteres."
        )

    try:
        date = datetime.strptime(
            official_draw_at,
            "%Y-%m-%dT%H:%M"
        )
    except ValueError:
        raise DrawFinalizationError(
            "La fecha oficial no tiene un formato valido."
        )

    if date.year < 2000 or date.year > 2100:
        raise DrawFinalizationError(
            "La fecha oficial queda fuera "
            "del intervalo admitido."
        )

    return (
        official_result,
        official_source,
        official_draw_at
    )


def finalize_draw(
    db,
    raffle_id,
    admin_id,
    official_result,
    official_source,
    official_draw_at,
    confirmed=False,
    preview_number=None,
    preview_outcome=None,
):
    """
    Registra una adjudicacion definitiva.

    La conexion db debe corresponder a la entidad
    correcta y no tener una transaccion abierta.

    No realiza commit: el llamante debe confirmar
    la transaccion al finalizar correctamente.
    """

    if confirmed is not True:
        raise DrawFinalizationError(
            "Debe confirmar que ha comprobado "
            "el resultado oficial."
        )

    (
        official_result,
        official_source,
        official_draw_at
    ) = validate_official_data(
        official_result,
        official_source,
        official_draw_at
    )

    if db.in_transaction:
        raise DrawFinalizationError(
            "La conexion ya tiene una transaccion abierta."
        )

    db.execute("BEGIN IMMEDIATE")

    try:
        admin = db.execute(
            "SELECT id FROM entity_admins "
            "WHERE id=? AND active=1",
            (admin_id,)
        ).fetchone()

        if admin is None:
            raise DrawFinalizationError(
                "Administrador no autorizado."
            )

        raffle = db.execute(
            "SELECT * FROM raffles WHERE id=?",
            (raffle_id,)
        ).fetchone()

        if raffle is None:
            raise DrawFinalizationError(
                "Sorteo inexistente."
            )

        if raffle["status"] != "closed":
            raise DrawFinalizationError(
                "El sorteo debe estar cerrado "
                "para adjudicar el premio."
            )

        recorded = db.execute(
            "SELECT id FROM raffle_draw_results "
            "WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()

        if recorded is not None:
            raise DrawAlreadyRecorded(
                "Este sorteo ya tiene un resultado definitivo."
            )

        rule = db.execute(
            "SELECT * FROM raffle_draw_rules "
            "WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()

        if rule is None:
            raise DrawFinalizationError(
                "El sorteo no tiene regla de adjudicacion."
            )

        try:
            winning_number = calculate_winning_number(
                official_result,
                rule["rule_type"],
                rule["rule_parameters"],
                raffle["number_start"],
                raffle["number_end"]
            )
        except ValueError as exc:
            raise DrawFinalizationError(str(exc))

        assigned = db.execute(
            """
            SELECT id,participant_id
            FROM raffle_numbers
            WHERE raffle_id=? AND number=?
            """,
            (raffle_id, winning_number)
        ).fetchone()

        if assigned is None:
            outcome = "void"
            participant_id = None
            number_id = None
        else:
            outcome = "winner"
            participant_id = assigned["participant_id"]
            number_id = assigned["id"]

        if (
            preview_number is not None
            or preview_outcome is not None
        ):
            if (
                preview_number is None
                or preview_outcome is None
            ):
                raise DrawFinalizationError(
                    'Faltan datos de la vista previa.'
                )

            validate_preview_match(
                winning_number,
                outcome,
                preview_number,
                preview_outcome
            )

        result_cursor = db.execute(
            """
            INSERT INTO raffle_draw_results(
                raffle_id,rule_id,
                official_result,official_source,
                official_draw_at,winning_number,
                outcome,winning_participant_id,
                winning_raffle_number_id,
                recorded_by
            )
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                raffle_id,
                rule["id"],
                official_result,
                official_source,
                official_draw_at,
                winning_number,
                outcome,
                participant_id,
                number_id,
                admin_id
            )
        )

        # Crear el expediente de entrega en la misma
        # transaccion que registra la adjudicacion.
        # Los premios desiertos no necesitan expediente.
        if outcome == "winner":
            db.execute(
                """
                INSERT INTO prize_deliveries(
                    draw_result_id
                )
                VALUES(?)
                """,
                (result_cursor.lastrowid,)
            )

        # Un resultado registrado finaliza el sorteo.
        db.execute(
            """
            UPDATE raffles
            SET status='finished',
                updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='closed'
            """,
            (raffle_id,)
        )

        return {
            "winning_number": winning_number,
            "outcome": outcome,
            "participant_id": participant_id,
            "raffle_number_id": number_id
        }

    except Exception:
        db.rollback()
        raise


def validate_preview_match(
    calculated_number,
    calculated_outcome,
    preview_number,
    preview_outcome,
):
    """
    Comprueba que la adjudicacion coincide
    con la vista previa confirmada.
    """

    if (
        str(calculated_number) != str(preview_number)
        or calculated_outcome != preview_outcome
    ):
        raise DrawFinalizationError(
            "El resultado ha cambiado respecto "
            "a la vista previa. Revise nuevamente "
            "la adjudicacion."
        )

    return True
