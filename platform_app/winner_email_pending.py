"""Preparacion de correos ya registrados en la cola."""

from platform_app.winner_email_template import build_winner_email


def prepare_pending_winner_email(db, notification_id):
    """Prepara una notificacion reclamada, sin enviar SMTP."""

    row = db.execute("""
        SELECT
            n.id,
            n.status,
            n.recipient_email,
            d.winning_number,
            d.outcome,
            r.title AS raffle_title,
            r.prizes AS prize_description,
            p.email AS current_email,
            p.active AS participant_active,
            p.email_verified AS participant_verified
        FROM winner_email_notifications n
        JOIN raffle_draw_results d
            ON d.id=n.draw_result_id
        JOIN raffles r
            ON r.id=d.raffle_id
        LEFT JOIN participants p
            ON p.id=d.winning_participant_id
        WHERE n.id=?
    """, (notification_id,)).fetchone()

    if row is None:
        return {"ready": False, "reason": "notification_not_found"}

    if row["status"] != "sending":
        return {"ready": False, "reason": "notification_not_claimed"}

    settings = dict(db.execute("""
        SELECT key,value
        FROM entity_settings
        WHERE key IN (
            'automatic_winner_notifications',
            'entity_display_name',
            'prize_collection_instructions'
        )
    """).fetchall())

    if settings.get("automatic_winner_notifications") != "1":
        return {"ready": False, "reason": "notifications_disabled"}

    if row["outcome"] != "winner":
        return {"ready": False, "reason": "no_winner"}

    if (
        not row["participant_active"]
        or not row["participant_verified"]
        or not row["current_email"]
    ):
        return {"ready": False, "reason": "invalid_recipient"}

    if row["current_email"] != row["recipient_email"]:
        return {"ready": False, "reason": "recipient_changed"}

    entity_name = settings.get("entity_display_name", "").strip()
    instructions = settings.get(
        "prize_collection_instructions", ""
    ).strip()

    if not entity_name:
        return {"ready": False, "reason": "entity_name_not_configured"}

    if not instructions:
        return {"ready": False, "reason": "missing_collection_instructions"}

    message = build_winner_email(
        entity_name=entity_name,
        raffle_title=row["raffle_title"],
        winning_number=str(row["winning_number"]),
        prize_description=row["prize_description"],
        collection_instructions=instructions
    )

    return {
        "ready": True,
        "notification_id": notification_id,
        "recipient": row["recipient_email"],
        "subject": message["subject"],
        "text": message["text"],
        "html": message["html"]
    }
