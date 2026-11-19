"""Registro transaccional de resultados de notificaciones."""

def record_winner_email_result(
    db,
    notification_id,
    status,
    error_message=""
):
    """
    Registra el resultado de un intento de envio SMTP.

    Esta funcion no envia correos.
    Solo admite transiciones desde 'sending'.
    """

    if status not in ("sent", "failed", "uncertain"):
        raise ValueError("Estado de envio no permitido.")

    error_message = str(error_message or "").strip()[:1000]

    try:
        db.execute("BEGIN IMMEDIATE")

        notification = db.execute("""
            SELECT
                n.id,
                n.draw_result_id,
                n.status,
                d.outcome
            FROM winner_email_notifications n
            JOIN raffle_draw_results d
                ON d.id=n.draw_result_id
            WHERE n.id=?
        """, (notification_id,)).fetchone()

        if notification is None:
            db.rollback()
            return {
                "updated": False,
                "reason": "not_found"
            }

        if notification["status"] != "sending":
            db.rollback()
            return {
                "updated": False,
                "reason": "invalid_transition",
                "current_status": notification["status"]
            }

        if notification["outcome"] != "winner":
            db.rollback()
            return {
                "updated": False,
                "reason": "no_winner"
            }

        if status == "sent":
            cursor = db.execute("""
                UPDATE winner_email_notifications
                SET status='sent',
                    sent_at=CURRENT_TIMESTAMP,
                    last_error=''
                WHERE id=? AND status='sending'
            """, (notification_id,))
        else:
            cursor = db.execute("""
                UPDATE winner_email_notifications
                SET status=?,
                    last_error=?,
                    sent_at=NULL
                WHERE id=? AND status='sending'
            """, (
                status,
                error_message,
                notification_id
            ))

        if cursor.rowcount != 1:
            raise RuntimeError(
                "No se ha podido actualizar la notificacion."
            )

        if status == "sent":
            db.execute("""
                INSERT INTO prize_communications (
                    draw_result_id,
                    communication_type,
                    direction,
                    status,
                    notes,
                    recorded_by
                )
                VALUES (?, 'email', 'outgoing', 'sent', ?, NULL)
            """, (
                notification["draw_result_id"],
                "Notificacion automatica al ganador. "
                "Mensaje aceptado por el servidor SMTP."
            ))

            db.execute("""
                UPDATE prize_deliveries
                SET notification_status='notified',
                    notified_at=COALESCE(
                        notified_at, CURRENT_TIMESTAMP
                    ),
                    updated_at=CURRENT_TIMESTAMP
                WHERE draw_result_id=?
            """, (notification["draw_result_id"],))

        db.commit()

        return {
            "updated": True,
            "status": status,
            "notification_id": notification_id
        }

    except Exception:
        db.rollback()
        raise
