"""Control transaccional de notificaciones de premios."""

import sqlite3

from platform_app.winner_email_service import (
    prepare_winner_notification
)


def queue_winner_email(db, draw_result_id, entity_name):
    """Registra una notificacion pendiente sin enviar correos."""

    try:
        db.execute("BEGIN IMMEDIATE")

        prepared = prepare_winner_notification(
            db, draw_result_id, entity_name
        )

        if not prepared["ready"]:
            db.rollback()
            return prepared

        db.execute("""
            INSERT INTO winner_email_notifications (
                draw_result_id,
                recipient_email,
                status
            )
            VALUES (?, ?, 'pending')
        """, (
            draw_result_id,
            prepared["recipient"]
        ))

        db.commit()

        return {
            "queued": True,
            "draw_result_id": draw_result_id,
            "status": "pending"
        }

    except Exception:
        db.rollback()
        raise


def claim_winner_email(db, notification_id):
    """
    Reclama una notificacion pendiente.
    No realiza ningun envio SMTP.
    """

    try:
        db.execute("BEGIN IMMEDIATE")

        cursor = db.execute("""
            UPDATE winner_email_notifications
            SET status='sending',
                attempts=attempts+1,
                last_attempt_at=CURRENT_TIMESTAMP,
                last_error=''
            WHERE id=?
              AND status='pending'
              AND EXISTS (
                  SELECT 1
                  FROM entity_settings
                  WHERE key='automatic_winner_notifications'
                    AND value='1'
              )
        """, (notification_id,))

        claimed = cursor.rowcount == 1

        db.commit()

        return claimed

    except Exception:
        db.rollback()
        raise
