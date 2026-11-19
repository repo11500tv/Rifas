"""Formulario de confirmacion de adjudicaciones."""

import html


def esc(value):
    return html.escape(str(value or ""), quote=True)


def confirmation_form(
    action_url,
    csrf_token,
    official_result,
    official_source,
    official_draw_at,
    winning_number,
    outcome,
    participant_name="",
    participant_email="",
):
    if outcome not in ("winner", "void"):
        raise ValueError("Estado de adjudicacion invalido.")

    if outcome == "winner":
        outcome_html = (
            '<p><strong>PREMIO ADJUDICABLE</strong></p>'
            '<p>Participante: ' +
            esc(participant_name) + '</p>'
            '<p>Correo: ' +
            esc(participant_email) + '</p>'
        )
    else:
        outcome_html = (
            '<p><strong>PREMIO DESIERTO</strong></p>'
            '<p>El numero ganador no ha sido vendido.</p>'
        )

    fields = {
        "_csrf": csrf_token,
        "official_result": official_result,
        "official_source": official_source,
        "official_draw_at": official_draw_at,
        "preview_number": winning_number,
        "preview_outcome": outcome,
    }

    hidden = "".join(
        '<input type="hidden" name="' +
        esc(name) + '" value="' +
        esc(value) + '">'
        for name, value in fields.items()
    )

    return (
        '<div class="card">'
        '<h3>Confirmacion definitiva</h3>'
        '<p><strong>Resultado oficial:</strong> ' +
        esc(official_result) + '</p>'
        '<p><strong>Fuente:</strong> ' +
        esc(official_source) + '</p>'
        '<p><strong>Fecha:</strong> ' +
        esc(official_draw_at) + '</p>'
        '<p><strong>Numero ganador:</strong> ' +
        esc(winning_number) + '</p>' +
        outcome_html +
        '<p><strong>Atencion:</strong> '
        'esta operacion registrara el resultado '
        'definitivo y finalizara el sorteo.</p>'
        '<form method="post" action="' +
        esc(action_url) + '">' +
        hidden +
        '<label>'
        '<input type="checkbox" '
        'name="official_confirmed" '
        'value="yes" required>'
        ' He comprobado personalmente el resultado '
        'y su fuente oficial.'
        '</label>'
        '<p><button type="submit">'
        'Confirmar adjudicacion definitiva'
        '</button></p>'
        '</form>'
        '</div>'
    )
