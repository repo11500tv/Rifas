"""Formulario administrativo de edicion de participantes."""

from html import escape


def participant_edit_form(
    participant,
    csrf_token,
    action_url,
    back_url,
    balance_cents,
    message="",
):
    """Construye el formulario sin ejecutar modificaciones."""

    def safe(value):
        return escape(str(value), quote=True)

    participant_id = int(participant["id"])
    active = bool(participant["active"])
    verified = bool(participant["email_verified"])

    status = (
        "Verificado" if verified else "Pendiente de verificar"
    )

    selected_active = " selected" if active else ""
    selected_inactive = "" if active else " selected"

    content = '<div class="card">'
    content += '<h2>Editar participante</h2>'

    if message:
        content += (
            '<p role="alert">' + safe(message) + '</p>'
        )

    content += (
        '<p><strong>Identificador:</strong> ' +
        str(participant_id) + '</p>'
        '<p><strong>Correo:</strong> ' +
        safe(status) + '</p>'
        '<p><strong>Creditos disponibles:</strong> ' +
        f'{balance_cents / 100:.2f}' + ' EUR</p>'
    )

    content += (
        '<form method="post" action="' +
        safe(action_url) + '">'
        '<input type="hidden" name="_csrf" value="' +
        safe(csrf_token) + '">'

        '<p><label>Nombre y apellidos'
        '<input name="name" maxlength="150" required value="' +
        safe(participant["name"]) + '"></label></p>'

        '<p><label>Correo electronico'
        '<input type="email" name="email" maxlength="254" '
        'required value="' +
        safe(participant["email"]) + '"></label></p>'

        '<p><label>Telefono movil'
        '<input type="tel" name="phone" required value="' +
        safe(participant["phone"]) + '"></label></p>'

        '<p><label>Estado de la cuenta'
        '<select name="active">'
        '<option value="1"' + selected_active +
        '>Activa</option>'
        '<option value="0"' + selected_inactive +
        '>Inactiva</option>'
        '</select></label></p>'

        '<p>Si cambias el correo electronico, '
        'el participante debera verificar la nueva direccion '
        'antes de volver a acceder a su cuenta.</p>'

        '<button type="submit">Guardar cambios</button>'
        '</form>'
    )

    content += (
        '<p><a href="' + safe(back_url) +
        '">Cancelar y volver</a></p>'
        '</div>'
    )

    return content
