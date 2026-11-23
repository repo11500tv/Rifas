"""Participantes: cuenta y administracion sin contrasenas."""

from functools import wraps
from html import escape

from flask import (
    Blueprint, abort, current_app, redirect, request,
    session, url_for
)

from platform_app.entity_routes import (
    edb, get_entity, layout, token, protected
)
from platform_app.participant_account_access_v2 import (
    participant_can_access
)

bp = Blueprint(
    "participants",
    __name__,
    url_prefix="/e/<slug>/participantes"
)


def google_enabled():
    return "participant_google_oauth" in current_app.extensions


def active_entity(slug):
    entity = get_entity(slug)
    if entity is None or entity["status"] != "active":
        abort(404)
    return entity


def member_only(fn):
    @wraps(fn)
    def wrapped(slug, *args, **kwargs):
        active_entity(slug)

        if session.get("participant_slug") != slug:
            return redirect(
                url_for(
                    "participant_access_v2.request_code",
                    slug=slug
                )
            )

        participant_id = session.get("participant_id")

        with edb(slug) as connection:
            allowed = participant_can_access(
                connection, participant_id
            )

        if not allowed:
            session.pop("participant_slug", None)
            session.pop("participant_id", None)
            return redirect(
                url_for(
                    "participant_access_v2.request_code",
                    slug=slug
                )
            )

        return fn(slug, *args, **kwargs)

    return wrapped


@bp.get("/registro")
def register(slug):
    entity = active_entity(slug)
    email = url_for("participant_registration_v2.registration_form", slug=slug)
    if not google_enabled():
        return redirect(email)
    google = url_for("participant_google_registration.begin", slug=slug)
    return layout(
        "Registro de participantes · " + entity["name"],
        f'<div class="card"><h2>Nuevo participante</h2>'
        f'<p><a href="{google}">Registrarse con Google</a></p>'
        f'<p><a href="{email}">Registrarse por correo</a></p></div>',
    )


@bp.route("/acceso", methods=["GET"])
def login(slug):
    ent = active_entity(slug)
    from html import escape as html_escape

    logo = (
        f'<img src="{url_for("entity.public_logo",slug=slug)}" '
        'alt="Logotipo de la entidad" '
        'style="display:block;max-width:180px;max-height:140px;'
        'width:auto;height:auto;object-fit:contain;margin:0 auto 22px">'
        if ent['logo_path'] else
        f'<h2 style="text-align:center">{html_escape(ent["name"])}</h2>'
    )

    access_url = url_for(
        'participant_access_v2.request_code', slug=slug
    )
    register_url = url_for(
        'participants.register' if google_enabled() else 'participant_registration_v2.registration_form', slug=slug
    )
    google_access = ''
    if google_enabled():
        google_url = url_for("participant_google_oidc.start_google_login", slug=slug)
        google_access = f'<p><a href="{google_url}">Acceder con Google</a></p>'

    body = (
        '<div class="card" style="text-align:center">'
        + logo +
        '<h2>Acceso de participantes</h2>'
        '<p>Selecciona una opción para continuar.</p>'
        + google_access +
        f'<p><a href="{access_url}" '
        'style="display:block;padding:13px;background:#17365a;'
        'color:white;border-radius:7px;text-decoration:none">'
        'Acceder con código por correo</a></p>'
        f'<p><a href="{register_url}" '
        'style="display:block;padding:13px;border:1px solid #17365a;'
        'border-radius:7px;text-decoration:none">'
        'Nuevo participante</a></p>'
        '</div>'
    )
    return layout('Participantes · ' + ent['name'], body)


@bp.get("/cuenta")
@member_only
def account(slug):
    entity = active_entity(slug)
    participant_id = session["participant_id"]

    with edb(slug) as connection:
        user = connection.execute(
            "SELECT name,email,phone "
            "FROM participants WHERE id=?",
            (participant_id,)
        ).fetchone()

        balance = connection.execute(
            "SELECT COALESCE(SUM(amount_cents),0) "
            "FROM credit_movements WHERE participant_id=?",
            (participant_id,)
        ).fetchone()[0]

        movements = connection.execute(
            "SELECT movement_type,amount_cents,"
            "created_at,notes "
            "FROM credit_movements "
            "WHERE participant_id=? "
            "ORDER BY id DESC LIMIT 50",
            (participant_id,)
        ).fetchall()

    if user is None:
        abort(403)

    rows = "".join(
        "<tr><td>" + escape(str(m["created_at"])) +
        "</td><td>" + escape(str(m["movement_type"])) +
        "</td><td>" +
        f'{m["amount_cents"]/100:.2f}' +
        "</td><td>" + escape(str(m["notes"] or "")) +
        "</td></tr>"
        for m in movements
    )


    def link(endpoint):
        return escape(
            url_for(endpoint, slug=slug),
            quote=True
        )

    google_options = ""
    if google_enabled():
        for purpose, label in (("link", "Vincular Google"), ("replace", "Cambiar cuenta Google")):
            url = url_for("participant_google_binding.start", slug=slug, purpose=purpose)
            google_options += (
                f'<form method="post" action="{url}">'
                f'<input type="hidden" name="_csrf" value="{escape(str(token()), quote=True)}">'
                f'<button type="submit">{label}</button></form>'
            )

    body = (
        '<style>'
        '.account-header{display:flex;flex-wrap:wrap;'
        'gap:18px;align-items:center;'
        'justify-content:space-between}'
        '.account-details{flex:2;min-width:220px}'
        '.account-balance{flex:1;min-width:180px;'
        'padding:18px;background:#eef6f0;'
        'border-radius:10px;text-align:center}'
        '.account-balance strong{display:block;'
        'font-size:28px;color:#17633b}'
        '.account-actions{display:grid;'
        'grid-template-columns:repeat(3,minmax(0,1fr));'
        'gap:12px;margin:18px 0}'
        '.account-action{display:flex;'
        'align-items:center;justify-content:center;'
        'text-align:center;min-height:65px;'
        'padding:12px;border-radius:8px;'
        'background:#17633b;color:white!important;'
        'font-weight:600;text-decoration:none!important}'
        '.account-action.secondary{'
        'background:#365b7a}'
        '@media(max-width:650px){'
        '.account-actions{grid-template-columns:1fr}'
        '}'
        '</style>'

        '<div class="card">'
        '<h2>Mi cuenta</h2>'
        '<div class="account-header">'
        '<div class="account-details">'
        '<h3>' + escape(user["name"]) + '</h3>'
        '<p><strong>Correo:</strong> ' +
        escape(user["email"]) + '</p>'
        '<p><strong>Movil:</strong> ' +
        escape(user["phone"] or "") + '</p>'
        '</div>'
        '<div class="account-balance">'
        '<span>Saldo disponible</span>'
        '<strong>' + f'{balance/100:.2f}' +
        ' creditos</strong>'
        '<span>1 credito = 1 euro</span>'
        '</div>'
        '</div>'
        '</div>'

        '<div class="card">'
        '<h3>Operaciones</h3>'
        '<div class="account-actions">'
        '<a class="account-action" href="' +
        link("participant_topup_requests.requests_page") +
        '">Solicitar recarga de creditos</a>'
        '<a class="account-action" href="' +
        link("participant_raffle_purchases.list_raffles") +
        '">Comprar participaciones</a>'
        '<a class="account-action secondary" href="' +
        link("participant_raffle_purchases.my_purchases") +
        '">Mis participaciones</a>'
        '</div>'
        '</div>'

        '<div class="card">'
        '<h3>Movimientos de creditos</h3>'
        '<table><tr><th>Fecha</th><th>Tipo</th>'
        '<th>Creditos</th><th>Detalle</th></tr>' +
        rows +
        '</table>'
        '</div>'

        '<div class="card">'
        '<h3>Opciones de cuenta</h3>'
        + google_options +
        '<p>Las solicitudes de baja se habilitaran '
        'con verificacion de seguridad.</p>'
        '<form method="post" action="' +
        link("participants.logout") + '">'
        '<input type="hidden" name="_csrf" value="' +
        escape(str(token()), quote=True) + '">'
        '<button type="submit">Cerrar sesion</button>'
        '</form>'
        '</div>'
    )

    return layout(
        "Mi cuenta - " + entity["name"],
        body
    )


@bp.post("/salir")
@member_only
def logout(slug):
    from platform_app.participant_session_shared import clear_participant_flows
    clear_participant_flows(session)
    session.pop("participant_slug", None)
    session.pop("participant_id", None)
    return redirect(
        url_for(
            "participants.login" if google_enabled() else "participant_access_v2.request_code",
            slug=slug
        )
    )


@bp.get("/administracion")
@protected
def admin_list(slug):
    entity = active_entity(slug)

    with edb(slug) as connection:
        users = connection.execute(
            "SELECT p.id,p.name,p.email,p.phone,"
            "p.email_verified,p.active,"
            "COALESCE(SUM(m.amount_cents),0) balance "
            "FROM participants p "
            "LEFT JOIN credit_movements m "
            "ON m.participant_id=p.id "
            "GROUP BY p.id ORDER BY p.id DESC"
        ).fetchall()

    rows = "".join(
        "<tr><td>" + str(u["id"]) +
        "</td><td>" + escape(u["name"]) +
        "</td><td>" + escape(u["email"]) +
        "</td><td>" + escape(u["phone"]) +
        "</td><td>" +
        ("Si" if u["email_verified"] else "No") +
        "</td><td>" +
        ("Si" if u["active"] else "No") +
        "</td><td>" +
        f'{u["balance"]/100:.2f}' +
        '</td><td><a href="' +
        escape(
            url_for(
                "participant_edit_admin.edit_participant",
                slug=slug,
                participant_id=u["id"],
            ),
            quote=True,
        ) +
        '">Editar</a></td></tr>'
        for u in users
    )

    body = (
        '<div class="card">'
        '<h2>Participantes registrados</h2>'
        '<table><tr><th>ID</th><th>Nombre</th>'
        '<th>Correo</th><th>Movil</th>'
        '<th>Correo verificado</th><th>Activo</th>'
        '<th>Creditos</th><th>Acciones</th></tr>' +
        rows + '</table>'
        '<p><a href="' +
        escape(
            url_for("entity.admin", slug=slug),
            quote=True
        ) +
        '">Volver a administracion</a></p>'
        '</div>'
    )

    return layout(
        "Participantes - " + entity["name"],
        body
    )
