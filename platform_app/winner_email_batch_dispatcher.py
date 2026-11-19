from platform_app.winner_email_dispatcher import (
    process_winner_notification,
)


def process_winner_notifications(db, limit=10, dry_run=True):
    """
    Procesa notificaciones pendientes en modo simulacion.

    El envio SMTP real permanece bloqueado.
    """

    if dry_run is not True:
        return {
            "processed": 0,
            "simulated": 0,
            "blocked": True,
            "reason": "real_smtp_not_authorized",
            "smtp_sent": False,
        }

    limit = max(1, min(int(limit), 100))

    rows = db.execute(
        """
        SELECT id
        FROM winner_email_notifications
        WHERE status='pending'
        ORDER BY id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    results = []

    for row in rows:
        notification_id = row[0]

        result = process_winner_notification(
            db,
            notification_id,
            dry_run=True,
        )

        results.append({
            "notification_id": notification_id,
            "processed": result.get("processed", False),
            "status": result.get("status", "unknown"),
            "reason": result.get("reason", ""),
        })

    return {
        "processed": len(results),
        "simulated": sum(
            1 for result in results
            if result["status"] == "simulated"
        ),
        "blocked": False,
        "smtp_sent": False,
        "results": results,
    }
