"""Procesamiento por lotes en modo simulacion.

No envia correos ni modifica las notificaciones originales.
"""

from platform_app.winner_email_processor import (
    simulate_pending_winner_email
)


def simulate_winner_email_batch(db, limit=10):
    """Simula un lote limitado de notificaciones pendientes."""

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("El limite debe ser un numero entero.")

    if limit < 1 or limit > 10:
        raise ValueError("El limite debe estar entre 1 y 10.")

    rows = db.execute("""
        SELECT id
        FROM winner_email_notifications
        WHERE status='pending'
        ORDER BY id
        LIMIT ?
    """, (limit,)).fetchall()

    summary = {
        "total": len(rows),
        "simulated": 0,
        "blocked": 0,
        "errors": 0,
        "smtp_sent": 0
    }

    for row in rows:
        try:
            result = simulate_pending_winner_email(
                db, row["id"]
            )

            if result.get("processed"):
                summary["simulated"] += 1
            else:
                summary["blocked"] += 1

        except Exception:
            summary["errors"] += 1

    return summary
