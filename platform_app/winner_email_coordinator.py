"""Coordinador de notificaciones de premios.

Este modulo solo registra notificaciones pendientes.
No realiza envios SMTP.
"""

from platform_app.winner_email_queue import queue_winner_email


def queue_after_draw(db, raffle_id, entity_name=None):
    """
    Registra la notificacion correspondiente a un sorteo
    definitivamente adjudicado.

    La adjudicacion debe estar confirmada previamente.
    """

    result = db.execute(
        """
        SELECT id, outcome
        FROM raffle_draw_results
        WHERE raffle_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (raffle_id,)
    ).fetchone()

    if result is None:
        return {
            "queued": False,
            "reason": "draw_not_recorded"
        }

    if result["outcome"] != "winner":
        return {
            "queued": False,
            "reason": "no_winner"
        }

    # Obtener la denominacion configurada para esta entidad.
    setting = db.execute(
        '''
        SELECT value
        FROM entity_settings
        WHERE key='entity_display_name'
        '''
    ).fetchone()

    configured_name = (
        str(setting["value"] or "").strip()
        if setting is not None else ""
    )

    if not configured_name:
        return {
            "queued": False,
            "reason": "entity_name_not_configured"
        }

    return queue_winner_email(
        db,
        result["id"],
        configured_name
    )
