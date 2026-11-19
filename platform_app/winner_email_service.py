"""Preparacion segura de notificaciones de premios."""

from platform_app.winner_email_template import build_winner_email


def prepare_winner_notification(db, draw_result_id, entity_name):
    """
    Prepara un correo sin enviarlo ni modificar la base de datos.

    Devuelve un diccionario con los datos del mensaje.
    """

    enabled = db.execute("""
        SELECT value
        FROM entity_settings
        WHERE key='automatic_winner_notifications'
    """).fetchone()

    if enabled is None or enabled["value"] != "1":
        return {
            "ready": False,
            "reason": "notifications_disabled"
        }

    result = db.execute("""
        SELECT
            d.id,
            d.outcome,
            d.winning_number,
            r.title AS raffle_title,
            r.prizes AS prize_description,
            p.email AS participant_email,
            p.active AS participant_active,
            p.email_verified AS participant_verified
        FROM raffle_draw_results d
        JOIN raffles r ON r.id=d.raffle_id
        LEFT JOIN participants p
            ON p.id=d.winning_participant_id
        WHERE d.id=?
    """, (draw_result_id,)).fetchone()

    if result is None:
        return {
            "ready": False,
            "reason": "result_not_found"
        }

    if result["outcome"] != "winner":
        return {
            "ready": False,
            "reason": "no_winner"
        }

    if (
        not result["participant_email"]
        or not result["participant_active"]
        or not result["participant_verified"]
    ):
        return {
            "ready": False,
            "reason": "invalid_recipient"
        }

    existing = db.execute("""
        SELECT status
        FROM winner_email_notifications
        WHERE draw_result_id=?
    """, (draw_result_id,)).fetchone()

    if existing is not None:
        return {
            "ready": False,
            "reason": "notification_already_registered",
            "status": existing["status"]
        }

    instructions = db.execute("""
        SELECT value
        FROM entity_settings
        WHERE key='prize_collection_instructions'
    """).fetchone()

    if instructions is None or not instructions["value"].strip():
        return {
            "ready": False,
            "reason": "missing_collection_instructions"
        }

    message = build_winner_email(
        entity_name=entity_name,
        raffle_title=result["raffle_title"],
        winning_number=str(result["winning_number"]),
        prize_description=result["prize_description"],
        collection_instructions=instructions["value"]
    )

    return {
        "ready": True,
        "draw_result_id": draw_result_id,
        "recipient": result["participant_email"],
        "subject": message["subject"],
        "text": message["text"],
        "html": message["html"]
    }
