"""Recuperación segura de contraseñas de administradores de entidad."""

import hashlib
import secrets
import sqlite3
import time

from flask import (
    Blueprint, abort, flash, redirect,
    request, url_for,
)
from werkzeug.security import generate_password_hash

from platform_app.entity_routes import (
    edb, get_entity, layout, token,
)
from platform_app.entity_mailer import (
    send_entity_email, EntityMailError,
)
from platform_app.security import (
    allow_attempt, record_failure,
)

bp = Blueprint(
    "admin_password_recovery",
    __name__,
    url_prefix="/e/<slug>/admin",
)

EXPIRATION_SECONDS = 1800


def hash_token(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@bp.route("/recuperar", methods=["GET", "POST"])
def request_recovery(slug):
    entity = get_entity(slug)

    if entity["status"] != "active":
        abort(403)

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:254]

        if not allow_attempt(
            "admin_recovery:" + slug,
            email,
            max_attempts=5,
            window_seconds=900,
        ):
            abort(429)

        record_failure("admin_recovery:" + slug, email)

        if email:
            with edb(slug) as db:
                admin = db.execute(
                    """
                    SELECT id, email
                    FROM entity_admins
                    WHERE lower(email)=?
                      AND active=1
                    LIMIT 1
                    """,
                    (email,),
                ).fetchone()

                if admin:
                    raw_token = secrets.token_urlsafe(32)
                    now = int(time.time())

                    db.execute(
                        """
                        DELETE FROM admin_password_reset_tokens
                        WHERE admin_id=?
                           OR expires_at<?
                        """,
                        (admin["id"], now),
                    )

                    db.execute(
                        """
                        INSERT INTO admin_password_reset_tokens
                        (admin_id,token_hash,expires_at,created_at)
                        VALUES (?,?,?,?)
                        """,
                        (
                            admin["id"],
                            hash_token(raw_token),
                            now + EXPIRATION_SECONDS,
                            now,
                        ),
                    )

                    db.commit()

                    recovery_url = url_for(
                        "admin_password_recovery.reset_password",
                        slug=slug,
                        recovery_token=raw_token,
                        _external=True,
                        _scheme="https",
                    )

                    try:
                        send_entity_email(
                            db,
                            admin["email"],
                            "Recuperación de contraseña - Rifas Benéficas",
                            (
                                "Se ha solicitado restablecer la contraseña "
                                "de administración de tu entidad.\n\n"
                                "Utiliza este enlace:\n"
                                + recovery_url
                                + "\n\nEl enlace caduca en 30 minutos "
                                "y solo puede utilizarse una vez.\n\n"
                                "Si no has solicitado este cambio, "
                                "ignora este mensaje."
                            ),
                        )
                    except EntityMailError:
                        db.execute(
                            """
                            DELETE FROM admin_password_reset_tokens
                            WHERE token_hash=?
                            """,
                            (hash_token(raw_token),),
                        )

        flash(
            "Si existe una cuenta activa asociada al correo "
            "y el envío está disponible, recibirás instrucciones."
        )

        return redirect(
            url_for(
                "admin_password_recovery.request_recovery",
                slug=slug,
            )
        )

    return layout(
        "Recuperar contraseña",
        '<div class="card">'
        '<h2>Recuperar acceso de administrador</h2>'
        '<p>Introduce el correo electrónico asociado '
        'a tu cuenta de administrador.</p>'
        '<form method="post">'
        f'<input type="hidden" name="_csrf" value="{token()}">'
        '<label>Correo electrónico'
        '<input type="email" name="email" required>'
        '</label>'
        '<button>Enviar enlace de recuperación</button>'
        '</form>'
        '</div>',
    )


@bp.route(
    "/restablecer/<recovery_token>",
    methods=["GET", "POST"],
)
def reset_password(slug, recovery_token):
    entity = get_entity(slug)

    if entity["status"] != "active":
        abort(403)

    digest = hash_token(recovery_token)
    now = int(time.time())

    with edb(slug) as db:
        record = db.execute(
            """
            SELECT t.id, t.admin_id
            FROM admin_password_reset_tokens t
            JOIN entity_admins a ON a.id=t.admin_id
            WHERE t.token_hash=?
              AND t.used_at IS NULL
              AND t.expires_at>?
              AND a.active=1
            """,
            (digest, now),
        ).fetchone()

    if not record:
        return layout(
            "Enlace no válido",
            '<div class="card">'
            '<p>El enlace ha caducado o ya se ha utilizado.</p>'
            f'<a href="{url_for("admin_password_recovery.request_recovery", slug=slug)}">'
            'Solicitar otro enlace</a></div>',
        ), 400

    if request.method == "POST":
        password = request.form.get("password", "")
        repeat = request.form.get("password_repeat", "")

        if len(password) < 12 or password != repeat:
            flash(
                "La contraseña debe tener al menos "
                "12 caracteres y coincidir."
            )
        else:
            with edb(slug) as db:
                db.execute("BEGIN IMMEDIATE")

                valid = db.execute(
                    """
                    SELECT id
                    FROM admin_password_reset_tokens
                    WHERE id=?
                      AND token_hash=?
                      AND used_at IS NULL
                      AND expires_at>?
                    """,
                    (record["id"], digest, int(time.time())),
                ).fetchone()

                if not valid:
                    abort(400)

                updated = db.execute(
                    """
                    UPDATE entity_admins
                    SET password_hash=?
                    WHERE id=? AND active=1
                    """,
                    (
                        generate_password_hash(
                            password,
                            method="scrypt",
                        ),
                        record["admin_id"],
                    ),
                )

                if updated.rowcount != 1:
                    db.rollback()
                    abort(400)

                db.execute(
                    """
                    UPDATE admin_password_reset_tokens
                    SET used_at=?
                    WHERE id=?
                    """,
                    (int(time.time()), record["id"]),
                )

            flash("Contraseña actualizada correctamente.")

            return redirect(
                url_for("entity.login", slug=slug)
            )

    return layout(
        "Establecer nueva contraseña",
        '<div class="card">'
        '<h2>Nueva contraseña</h2>'
        '<form method="post">'
        f'<input type="hidden" name="_csrf" value="{token()}">'
        '<label>Contraseña nueva'
        '<input type="password" name="password" '
        'minlength="12" required></label>'
        '<label>Repetir contraseña'
        '<input type="password" name="password_repeat" '
        'minlength="12" required></label>'
        '<button>Guardar nueva contraseña</button>'
        '</form></div>',
    )
