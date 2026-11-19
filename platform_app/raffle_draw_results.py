"""Consulta y vista previa de adjudicaciones externas."""

from platform_app.raffle_draw_confirmation import confirmation_form

import html
from flask import (
    Blueprint, abort, request, flash,
    redirect, url_for
)
from platform_app.entity_routes import (
    edb, layout, protected, token
)
from platform_app.raffle_draw_calculator import (
    calculate_winning_number
)

bp = Blueprint(
    "raffle_draw_results",
    __name__,
    url_prefix="/e/<slug>/admin/sorteos"
)


def esc(value):
    return html.escape(str(value or ""), quote=True)


@bp.route(
    "/<int:raffle_id>/resultado",
    methods=["GET", "POST"]
)
@protected
def result(slug, raffle_id):
    with edb(slug) as db:
        raffle = db.execute(
            "SELECT * FROM raffles WHERE id=?",
            (raffle_id,)
        ).fetchone()

        if raffle is None:
            abort(404)

        rule = db.execute(
            "SELECT * FROM raffle_draw_rules "
            "WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()

        recorded = db.execute(
            "SELECT * FROM raffle_draw_results "
            "WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()

    back = url_for(
        "raffles.detail",
        slug=slug,
        raffle_id=raffle_id
    )

    if rule is None:
        return layout(
            "Resultado del sorteo",
            '<div class="card">'
            '<h2>Resultado del sorteo</h2>'
            '<p>Este sorteo no tiene una regla '
            'de adjudicacion configurada.</p>'
            '<p><a href="' + back +
            '">Volver al sorteo</a></p>'
            '</div>'
        )

    if recorded is not None:
        with edb(slug) as db:
            winner = None

            if recorded["outcome"] == "winner":
                winner = db.execute(
                    "SELECT name,email FROM participants "
                    "WHERE id=?",
                    (recorded["winning_participant_id"],)
                ).fetchone()

            administrator = db.execute(
                "SELECT username FROM entity_admins "
                "WHERE id=?",
                (recorded["recorded_by"],)
            ).fetchone()

        if recorded["outcome"] == "winner":
            outcome_html = (
                '<p><strong>PREMIO ADJUDICADO</strong></p>'
                '<p>Participante: ' +
                esc(winner["name"] if winner else
                    "Participante no disponible") + '</p>'
                '<p>Correo: ' +
                esc(winner["email"] if winner else "") +
                '</p>'
            )
        else:
            outcome_html = (
                '<p><strong>PREMIO DESIERTO</strong></p>'
                '<p>El numero ganador no fue vendido.</p>'
            )

        body = (
            '<div class="card">'
            '<h2>Resultado definitivo del sorteo</h2>'
            '<p><strong>Sorteo:</strong> ' +
            esc(raffle["title"]) + '</p>'
            '<p><strong>Organismo externo:</strong> ' +
            esc(rule["external_organizer"]) + '</p>'
            '<p><strong>Sorteo externo:</strong> ' +
            esc(rule["external_draw"]) + '</p>'
            '<p><strong>Regla aplicada:</strong> ' +
            esc(rule["rule_description"]) + '</p>'
            '<p><strong>Resultado oficial:</strong> ' +
            esc(recorded["official_result"]) + '</p>'
            '<p><strong>Fuente oficial:</strong> ' +
            esc(recorded["official_source"]) + '</p>'
            '<p><strong>Fecha del sorteo externo:</strong> ' +
            esc(recorded["official_draw_at"]) + '</p>'
            '<p><strong>Numero ganador:</strong> ' +
            str(recorded["winning_number"]).zfill(
                raffle["number_width"]
            ) + '</p>' +
            outcome_html +
            '<p><strong>Registrado por:</strong> ' +
            esc(administrator["username"] if administrator
                else "Administrador no disponible") + '</p>'
            '<p><strong>Fecha de registro:</strong> ' +
            esc(recorded["recorded_at"]) + '</p>'
            '<p><strong>Estado:</strong> '
            'Resultado definitivo. Sorteo finalizado.</p>'
            '<p>El resultado externo fue introducido '
            'por un administrador y no se verifica '
            'automaticamente con el organismo emisor.</p>'
            '<p><a href="' + back +
            '">Volver al sorteo</a></p>'
            '</div>'
        )

        return layout("Resultado definitivo", body)

    if raffle["status"] not in ("closed", "finished"):
        return layout(
            "Resultado del sorteo",
            '<div class="card">'
            '<h2>Resultado del sorteo</h2>'
            '<p>Debe cerrar el sorteo antes '
            'de registrar su resultado.</p>'
            '<p><a href="' + back +
            '">Volver al sorteo</a></p>'
            '</div>'
        )

    preview = ""

    if request.method == "POST":
        official = request.form.get(
            "official_result", ""
        ).strip()

        source = request.form.get(
            "official_source", ""
        ).strip()

        draw_at = request.form.get(
            "official_draw_at", ""
        ).strip()

        if (
            not source
            or len(source) > 1000
            or not draw_at
        ):
            flash(
                "Indica la fuente oficial "
                "y la fecha del sorteo."
            )
            return redirect(request.url)

        try:
            winner = calculate_winning_number(
                official,
                rule["rule_type"],
                rule["rule_parameters"],
                raffle["number_start"],
                raffle["number_end"]
            )
        except ValueError as exc:
            flash(str(exc))
            return redirect(request.url)

        with edb(slug) as db:
            assigned = db.execute(
                """
                SELECT n.id,p.id AS participant_id,
                       p.name,p.email
                FROM raffle_numbers n
                JOIN participants p
                  ON p.id=n.participant_id
                WHERE n.raffle_id=?
                  AND n.number=?
                """,
                (raffle_id, winner)
            ).fetchone()

        number = str(winner).zfill(
            raffle["number_width"]
        )

        if assigned:
            outcome = (
                '<p><strong>PREMIO ADJUDICABLE</strong></p>'
                '<p>Participante: ' +
                esc(assigned["name"]) + '</p>'
                '<p>Correo: ' +
                esc(assigned["email"]) + '</p>'
            )
        else:
            outcome = (
                '<p><strong>PREMIO DESIERTO</strong></p>'
                '<p>El numero ganador no ha sido vendido.</p>'
            )

        preview = (
            '<div class="card">'
            '<h3>Vista previa de adjudicacion</h3>'
            '<p>Resultado externo: ' +
            esc(official) + '</p>'
            '<p>Fuente: ' + esc(source) + '</p>'
            '<p>Fecha: ' + esc(draw_at) + '</p>'
            '<p><strong>Numero ganador: ' +
            number + '</strong></p>' +
            outcome +
            '<p>Esta consulta no registra '
            'ninguna adjudicacion.</p>'
            '</div>'
        )


        confirm_url = url_for(
            "raffle_draw_results.confirm_result",
            slug=slug,
            raffle_id=raffle_id
        )

        preview += confirmation_form(
            action_url=confirm_url,
            csrf_token=token(),
            official_result=official,
            official_source=source,
            official_draw_at=draw_at,
            winning_number=winner,
            outcome="winner" if assigned else "void",
            participant_name=(
                assigned["name"] if assigned else ""
            ),
            participant_email=(
                assigned["email"] if assigned else ""
            )
        )

    body = (
        '<div class="card">'
        '<h2>Resultado del sorteo</h2>'
        '<p><strong>Sorteo:</strong> ' +
        esc(raffle["title"]) + '</p>'
        '<p><strong>Organismo externo:</strong> ' +
        esc(rule["external_organizer"]) + '</p>'
        '<p><strong>Sorteo externo:</strong> ' +
        esc(rule["external_draw"]) + '</p>'
        '<p><strong>Regla:</strong> ' +
        esc(rule["rule_description"]) + '</p>'
        '<p>Comprueba el resultado oficial antes '
        'de introducirlo. La aplicacion no verifica '
        'automaticamente la fuente externa.</p>'
        '<form method="post">'
        '<input type="hidden" name="_csrf" value="' +
        token() + '">'
        '<label>Resultado oficial'
        '<input name="official_result" required '
        'maxlength="30" inputmode="numeric"></label>'
        '<label>Fuente oficial (URL o referencia)'
        '<input name="official_source" required '
        'maxlength="1000"></label>'
        '<label>Fecha y hora del sorteo'
        '<input type="datetime-local" '
        'name="official_draw_at" required></label>'
        '<button>Calcular vista previa</button>'
        '</form>'
        '<p><a href="' + back +
        '">Volver al sorteo</a></p>'
        '</div>' +
        preview
    )

    return layout(
        "Resultado del sorteo",
        body
    )

from flask import session
from platform_app.raffle_draw_finalize import (
    finalize_draw,
    DrawFinalizationError,
    DrawAlreadyRecorded,
)


@bp.route(
    "/<int:raffle_id>/resultado/confirmar",
    methods=["POST"]
)
@protected
def confirm_result(slug, raffle_id):
    """Registra definitivamente el resultado externo."""

    back = url_for(
        "raffle_draw_results.result",
        slug=slug,
        raffle_id=raffle_id
    )

    if request.form.get("official_confirmed") != "yes":
        flash(
            "Debe confirmar que ha comprobado "
            "el resultado oficial."
        )
        return redirect(back)

    official = request.form.get(
        "official_result", ""
    ).strip()

    source = request.form.get(
        "official_source", ""
    ).strip()

    draw_at = request.form.get(
        "official_draw_at", ""
    ).strip()

    preview_number = request.form.get(
        "preview_number", ""
    ).strip()

    preview_outcome = request.form.get(
        "preview_outcome", ""
    ).strip()

    try:
        admin_id = int(session["entity_user_id"])

        with edb(slug) as db:
            result = finalize_draw(
                db,
                raffle_id,
                admin_id,
                official,
                source,
                draw_at,
                confirmed=True,
                preview_number=preview_number,
                preview_outcome=preview_outcome
            )

            db.commit()

        # La adjudicacion ya esta confirmada.
        # Un fallo en la notificacion no debe anularla.
        if result["outcome"] == "winner":
            try:
                from platform_app.winner_email_coordinator import (
                    queue_after_draw
                )

                with edb(slug) as notification_db:
                    queue_after_draw(
                        notification_db,
                        raffle_id
                    )

            except Exception:
                # No modificar la adjudicacion por un
                # problema en el sistema de notificaciones.
                import logging
                logging.getLogger(__name__).exception(
                    "No se pudo preparar la notificacion "
                    "del sorteo %s",
                    raffle_id
                )

    except DrawAlreadyRecorded:
        flash(
            "Este sorteo ya tiene una "
            "adjudicacion definitiva."
        )
        return redirect(back)

    except (DrawFinalizationError, ValueError) as exc:
        flash(str(exc))
        return redirect(back)

    if result["outcome"] == "winner":
        flash(
            "Premio adjudicado definitivamente "
            "al numero ganador."
        )
    else:
        flash(
            "Resultado registrado definitivamente. "
            "El premio ha quedado desierto."
        )

    return redirect(back)
