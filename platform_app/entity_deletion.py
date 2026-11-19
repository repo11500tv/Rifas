"""Validaciones de seguridad para eliminar entidades."""

import re
from pathlib import Path

from flask import abort, session

from platform_app import ENTITIES


def require_superadmin():
    """Impide el acceso a usuarios sin sesion central."""
    if not session.get("admin"):
        abort(403)


def validate_entity_path(slug):
    """Valida el codigo y la ubicacion de una entidad."""

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,49}", slug):
        raise ValueError("Codigo de entidad no valido")

    base = Path(ENTITIES).resolve(strict=True)
    target = base / slug

    if target.is_symlink():
        raise ValueError("Directorio simbolico no permitido")

    if not target.is_dir():
        raise ValueError("Directorio de entidad inexistente")

    if target.resolve(strict=True).parent != base:
        raise ValueError("Ruta de entidad no autorizada")

    for item in target.rglob("*"):
        if item.is_symlink():
            raise ValueError(
                "La entidad contiene enlaces simbolicos"
            )

    return target


def validate_confirmation(slug, confirmation):
    """Exige escribir exactamente el codigo de entidad."""
    if confirmation != slug:
        raise ValueError(
            "La confirmacion no coincide con el codigo"
        )


def lock_entity_for_deletion(connection, slug):
    """Comprueba la entidad bajo un bloqueo exclusivo de escritura.

    La transaccion permanece abierta hasta que el llamante
    realiza COMMIT o ROLLBACK.
    """
    connection.execute("BEGIN IMMEDIATE")

    entity = connection.execute(
        "SELECT id, slug, name, status FROM entities WHERE slug=?",
        (slug,)
    ).fetchone()

    if entity is None:
        connection.rollback()
        raise ValueError("La entidad ya no esta registrada")

    return entity


def delete_entity_safely(slug, confirmation, actor):
    """Elimina una entidad registrada con controles de seguridad.

    Debe invocarse exclusivamente desde una ruta protegida
    mediante require_superadmin().
    """
    import os
    import shutil
    import sqlite3
    import uuid
    from platform_app import DB

    validate_confirmation(slug, confirmation)
    target = validate_entity_path(slug)

    if not actor or not isinstance(actor, str):
        raise ValueError("Administrador central no identificado")

    base = Path(ENTITIES).resolve(strict=True)
    quarantine = base / (".eliminando_" + uuid.uuid4().hex)

    if quarantine.exists() or quarantine.is_symlink():
        raise ValueError("Ubicacion temporal no disponible")

    connection = sqlite3.connect(
        "file:" + str(DB) + "?mode=rw",
        uri=True,
        timeout=15
    )

    moved = False
    committed = False

    try:
        entity = lock_entity_for_deletion(connection, slug)
        entity_id = entity[0]

        target = validate_entity_path(slug)

        os.rename(target, quarantine)
        moved = True

        connection.execute(
            "INSERT INTO audit(actor,action,entity_id) "
            "VALUES(?,?,?)",
            (actor, "delete_entity:" + slug, entity_id)
        )

        deleted = connection.execute(
            "DELETE FROM entities WHERE id=? AND slug=?",
            (entity_id, slug)
        )

        if deleted.rowcount != 1:
            raise RuntimeError(
                "No se ha eliminado exactamente un registro"
            )

        connection.commit()
        committed = True

    except Exception:
        if not committed:
            connection.rollback()

            if moved and quarantine.exists():
                if target.exists():
                    raise RuntimeError(
                        "No es posible restaurar el directorio: "
                        "la ruta original esta ocupada"
                    )

                os.rename(quarantine, target)

        raise

    finally:
        connection.close()

    try:
        shutil.rmtree(quarantine)
    except OSError as exc:
        raise RuntimeError(
            "Registro central eliminado, pero quedan archivos "
            "pendientes de limpieza en: " + str(quarantine)
        ) from exc

    return entity_id


def deletion_confirmation_page(slug):
    """Muestra la confirmacion de eliminacion al superadministrador."""
    import html
    import sqlite3
    from flask import url_for
    from platform_app import DB
    from platform_app.entity_routes import layout, token

    require_superadmin()

    with sqlite3.connect(
        "file:" + str(DB) + "?mode=ro",
        uri=True
    ) as db:
        entity = db.execute(
            "SELECT name, slug FROM entities WHERE slug=?",
            (slug,)
        ).fetchone()

    if entity is None:
        abort(404)

    name = html.escape(entity[0])
    code = html.escape(entity[1])
    csrf = html.escape(token(), quote=True)

    action = url_for("central21.delete_entity", slug=slug)
    back = url_for("index")

    body = (
        '<div class="card">'
        '<h2>Eliminar entidad</h2>'
        f'<p><strong>Entidad:</strong> {name}</p>'
        f'<p><strong>Codigo:</strong> {code}</p>'
        '<p><strong>ADVERTENCIA:</strong> Esta operacion '
        'eliminara definitivamente la entidad, sus datos, '
        'archivos, configuracion y copias de seguridad.</p>'
        '<p>La operacion no se puede deshacer.</p>'
        '<p>Para confirmar, escribe exactamente el codigo '
        'de la entidad:</p>'
        f'<form method="post" action="{action}">'
        f'<input type="hidden" name="_csrf" value="{csrf}">'
        '<label>Codigo de confirmacion'
        '<input name="confirmation" required '
        'autocomplete="off"></label>'
        '<label><input type="checkbox" name="acknowledge" '
        'value="yes" required> '
        'Comprendo que la eliminacion es irreversible'
        '</label>'
        '<button type="submit">Eliminar definitivamente</button>'
        '</form>'
        f'<p><a href="{back}">Cancelar y volver</a></p>'
        '</div>'
    )

    return layout("Confirmar eliminacion de entidad", body)
