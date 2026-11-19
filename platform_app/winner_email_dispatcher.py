"""
Coordinador de notificaciones de premios.

Por seguridad, este modulo no permite envios SMTP
reales hasta su habilitacion expresa.
"""

from platform_app.winner_email_processor import (
    simulate_pending_winner_email
)


def process_winner_notification(
    db,
    notification_id,
    dry_run=True
):
    """
    Procesa una notificacion pendiente.

    dry_run=True:
        Simula el procesamiento sin modificar la base
        de datos original y sin enviar correos.

    dry_run=False:
        Bloqueado por seguridad hasta autorizacion.
    """

    if dry_run is not True:
        return {
            "processed": False,
            "status": "blocked",
            "reason": "real_smtp_not_authorized",
            "smtp_sent": False
        }

    result = simulate_pending_winner_email(
        db,
        notification_id
    )

    return {
        "processed": bool(result.get("processed")),
        "status": result.get("status", "unknown"),
        "reason": result.get("reason", ""),
        "smtp_sent": False
    }
