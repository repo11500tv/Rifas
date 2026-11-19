"""Plantilla de notificacion de premios por correo electronico."""

from html import escape


def build_winner_email(
    entity_name,
    raffle_title,
    winning_number,
    prize_description,
    collection_instructions,
):
    """Devuelve asunto, texto y HTML. No envia correos."""

    values = {
        "entity_name": str(entity_name or "").strip(),
        "raffle_title": str(raffle_title or "").strip(),
        "winning_number": str(winning_number or "").strip(),
        "prize_description": str(prize_description or "").strip(),
        "collection_instructions": str(
            collection_instructions or ""
        ).strip(),
    }

    if not all(values.values()):
        raise ValueError(
            "Faltan datos obligatorios para preparar el aviso."
        )

    subject = (
        "Premio adjudicado - "
        + values["entity_name"]
        + " - "
        + values["raffle_title"]
    )

    text = (
        "ENHORABUENA\n\n"
        "Le comunicamos que ha resultado ganador "
        "de un premio en nuestro sorteo benefico.\n\n"
        "Entidad: {entity_name}\n"
        "Sorteo: {raffle_title}\n"
        "Numero premiado: {winning_number}\n"
        "Premio: {prize_description}\n\n"
        "INSTRUCCIONES PARA RECOGER EL PREMIO\n"
        "{collection_instructions}\n\n"
        "Para cualquier consulta, contacte con "
        "la entidad organizadora.\n\n"
        "Muchas gracias por su colaboracion."
    ).format(**values)

    safe = {
        key: escape(value).replace("\n", "<br>")
        for key, value in values.items()
    }

    html = (
        '<div style="font-family:Arial,sans-serif;'
        'max-width:640px;margin:auto;line-height:1.6">'
        '<h2>Enhorabuena</h2>'
        '<p>Le comunicamos que ha resultado ganador '
        'de un premio en nuestro sorteo benefico.</p>'
        '<p><strong>Entidad:</strong> {entity_name}</p>'
        '<p><strong>Sorteo:</strong> {raffle_title}</p>'
        '<p><strong>Numero premiado:</strong> '
        '{winning_number}</p>'
        '<p><strong>Premio:</strong> '
        '{prize_description}</p>'
        '<h3>Instrucciones para recoger el premio</h3>'
        '<p>{collection_instructions}</p>'
        '<p>Para cualquier consulta, contacte con '
        'la entidad organizadora.</p>'
        '<p>Muchas gracias por su colaboracion.</p>'
        '</div>'
    ).format(**safe)

    return {
        "subject": subject,
        "text": text,
        "html": html,
    }
