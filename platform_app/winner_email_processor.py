"""Procesador seguro de notificaciones en modo simulacion.

No permite envios SMTP reales.
"""

from platform_app.winner_email_queue import claim_winner_email
from platform_app.winner_email_pending import prepare_pending_winner_email
from platform_app.winner_email_sender import send_winner_email


def simulate_pending_winner_email(db, notification_id):
    """Simula el procesamiento sin enviar correos."""

    row = db.execute("""
        SELECT status
        FROM winner_email_notifications
        WHERE id=?
    """, (notification_id,)).fetchone()

    if row is None:
        return {
            "processed": False,
            "reason": "notification_not_found"
        }

    if row["status"] != "pending":
        return {
            "processed": False,
            "reason": "notification_not_pending"
        }

    # No se reclama ni modifica la notificacion real.
    # Se utiliza una copia temporal de la base de datos.
    import sqlite3

    simulated_db = sqlite3.connect(":memory:")
    simulated_db.row_factory = sqlite3.Row

    try:
        db.backup(simulated_db)

        if not claim_winner_email(simulated_db, notification_id):
            return {
                "processed": False,
                "reason": "claim_rejected"
            }

        prepared = prepare_pending_winner_email(
            simulated_db, notification_id
        )

        if not prepared.get("ready"):
            return {
                "processed": False,
                "reason": prepared.get("reason", "not_ready")
            }

        result = send_winner_email(
            simulated_db,
            prepared,
            dry_run=True
        )

        return {
            "processed": result.get("status") == "simulated",
            "status": result.get("status"),
            "smtp_accepted": False
        }
    finally:
        simulated_db.close()
