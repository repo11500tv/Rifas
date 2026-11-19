"""Configuracion de reglas de adjudicacion por sorteo."""

import html
import json
from flask import (
    Blueprint, abort, flash, redirect,
    render_template_string, request, url_for
)
from platform_app.entity_routes import (
    edb, get_entity, layout, protected, token
)

bp = Blueprint(
    "raffle_draw_rules",
    __name__,
    url_prefix="/e/<slug>/admin/sorteos"
)


def esc(value):
    return html.escape(str(value or ""), quote=True)


def can_configure(raffle, sold):
    return raffle["status"] == "draft" and sold == 0


def validate_rule(form, raffle):
    organizer = form.get("external_organizer", "").strip()
    external_draw = form.get("external_draw", "").strip()
    rule_type = form.get("rule_type", "").strip()
    description = form.get("rule_description", "").strip()

    if not organizer or len(organizer) > 150:
        raise ValueError("Indica el organismo externo.")

    if not external_draw or len(external_draw) > 200:
        raise ValueError("Indica el sorteo externo.")

    if not description or len(description) > 1000:
        raise ValueError("Describe la regla de adjudicacion.")

    if rule_type not in (
        "last_digits", "modulo", "exact_number"
    ):
        raise ValueError("Metodo de calculo no valido.")

    start = raffle["number_start"]
    end = raffle["number_end"]
    width = raffle["number_width"]
    total = end - start + 1

    parameters = {}

    if rule_type == "last_digits":
        if start != 0 or total != 10 ** width:
            raise ValueError(
                "Ultimas cifras exige numeracion completa "
                "desde cero: 00-99, 000-999, etc."
            )
        parameters = {"digits": width}

    elif rule_type == "modulo":
        if start != 0:
            raise ValueError(
                "El metodo modulo exige numeracion desde cero."
            )
        parameters = {"divisor": total}

    elif rule_type == "exact_number":
        parameters = {
            "minimum": start,
            "maximum": end
        }

    return {
        "external_organizer": organizer,
        "external_draw": external_draw,
        "rule_type": rule_type,
        "rule_parameters": json.dumps(
            parameters, separators=(",", ":")
        ),
        "rule_description": description
    }


@bp.route("/<int:raffle_id>/regla", methods=["GET", "POST"])
@protected
def configure(slug, raffle_id):
    with edb(slug) as db:
        raffle = db.execute(
            "SELECT * FROM raffles WHERE id=?",
            (raffle_id,)
        ).fetchone()

        if raffle is None:
            abort(404)

        sold = db.execute(
            "SELECT COUNT(*) FROM raffle_numbers "
            "WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()[0]

        rule = db.execute(
            "SELECT * FROM raffle_draw_rules "
            "WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()

    editable = can_configure(raffle, sold)

    if request.method == "POST":
        if not editable:
            abort(403)

        try:
            data = validate_rule(request.form, raffle)
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for(
                "raffle_draw_rules.configure",
                slug=slug,
                raffle_id=raffle_id
            ))

        # Revalidar dentro de la transaccion para evitar
        # cambios concurrentes de estado o participaciones.
        with edb(slug) as db:
            db.execute("BEGIN IMMEDIATE")

            current = db.execute(
                "SELECT * FROM raffles WHERE id=?",
                (raffle_id,)
            ).fetchone()

            current_sold = db.execute(
                "SELECT COUNT(*) FROM raffle_numbers "
                "WHERE raffle_id=?",
                (raffle_id,)
            ).fetchone()[0]

            if current is None or not can_configure(
                current, current_sold
            ):
                db.rollback()
                abort(403)

            # Comprobar que la regla sigue siendo valida
            # para la numeracion actual.
            data = validate_rule(request.form, current)

            db.execute(
                """
                INSERT INTO raffle_draw_rules(
                    raffle_id, external_organizer,
                    external_draw, rule_type,
                    rule_parameters, rule_description,
                    created_by
                )
                VALUES(
                    :raffle_id, :external_organizer,
                    :external_draw, :rule_type,
                    :rule_parameters, :rule_description,
                    :created_by
                )
                ON CONFLICT(raffle_id) DO UPDATE SET
                    external_organizer=excluded.external_organizer,
                    external_draw=excluded.external_draw,
                    rule_type=excluded.rule_type,
                    rule_parameters=excluded.rule_parameters,
                    rule_description=excluded.rule_description,
                    updated_at=CURRENT_TIMESTAMP
                """,
                dict(
                    data,
                    raffle_id=raffle_id,
                    created_by=__import__(
                        "flask"
                    ).session["entity_user_id"]
                )
            )

        flash("Regla de adjudicacion guardada.")
        return redirect(url_for(
            "raffle_draw_rules.configure",
            slug=slug,
            raffle_id=raffle_id
        ))

    organizer = esc(
        rule["external_organizer"] if rule else ""
    )
    external_draw = esc(
        rule["external_draw"] if rule else ""
    )
    description = esc(
        rule["rule_description"] if rule else ""
    )
    selected = rule["rule_type"] if rule else "last_digits"

    options = "".join(
        '<option value="' + value + '"' +
        (' selected' if value == selected else '') +
        '>' + label + '</option>'
        for value, label in (
            ("last_digits", "Ultimas cifras"),
            ("modulo", "Modulo"),
            ("exact_number", "Numero exacto")
        )
    )

    back = url_for(
        "raffles.detail", slug=slug, raffle_id=raffle_id
    )

    if not editable:
        reason = (
            "El sorteo ya esta publicado o tiene "
            "participaciones vendidas. "
            "La regla no puede crearse ni modificarse."
        )
        if rule:
            reason += (
                "<p><strong>Organismo:</strong> " +
                organizer + "</p>"
                "<p><strong>Sorteo externo:</strong> " +
                external_draw + "</p>"
                "<p><strong>Regla:</strong> " +
                description + "</p>"
            )

        return layout(
            "Regla de adjudicacion",
            '<div class="card"><h2>Regla de adjudicacion</h2>'
            '<p>' + reason + '</p>'
            '<p><a href="' + back +
            '">Volver al sorteo</a></p></div>'
        )

    body = (
        '<div class="card">'
        '<h2>Regla de adjudicacion</h2>'
        '<p><strong>Sorteo:</strong> ' +
        esc(raffle["title"]) + '</p>'
        '<p>La regla debe definirse antes de publicar '
        'el sorteo.</p>'
        '<form method="post">'
        '<input type="hidden" name="_csrf" value="' +
        token() + '">'
        '<label>Organismo externo'
        '<input name="external_organizer" required '
        'maxlength="150" value="' + organizer + '">'
        '</label>'
        '<label>Sorteo externo de referencia'
        '<input name="external_draw" required '
        'maxlength="200" value="' + external_draw + '">'
        '</label>'
        '<label>Metodo de calculo'
        '<select name="rule_type">' + options +
        '</select></label>'
        '<label>Explicacion publica de la regla'
        '<textarea name="rule_description" '
        'required maxlength="1000" rows="4">' +
        description + '</textarea></label>'
        '<p>El premio sera declarado desierto si '
        'el numero obtenido no esta vendido.</p>'
        '<button>Guardar regla</button>'
        '</form>'
        '<p><a href="' + back +
        '">Volver al sorteo</a></p>'
        '</div>'
    )

    return layout("Regla de adjudicacion", body)
