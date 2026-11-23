"""Registration after a verified Google OIDC callback.

Security prerequisites: verified Authlib ID token; session-bound flow; global CSRF
protection on POST; migrated per-entity database and master template.
"""
import secrets
from contextlib import closing
from flask import Blueprint, abort, redirect, render_template_string, request, session, url_for

from platform_app.entity_routes import get_entity, token
from platform_app.participant_google_flow import consume_flow
from platform_app.participant_google_oidc_routes import google_connection, start_authorization, verified_claims
from platform_app.participant_google_pending_registration import start, finish, PendingRegistrationInvalid
from platform_app.participant_google_registration_core import RegistrationConflict, InvalidRegistration
from platform_app.participant_session_shared import finish_verified_participant_session

bp = Blueprint('participant_google_registration', __name__, url_prefix='/e/<slug>/participantes/google/registro')
HANDLE_KEY = '_google_registration_handle'
BINDING_KEY = '_google_registration_binding'


def _active(slug):
    ent = get_entity(slug)
    if ent is None or ent['status'] != 'active':
        abort(404)


@bp.get('/iniciar')
def begin(slug):
    _active(slug)
    session.pop(HANDLE_KEY, None)
    session.pop(BINDING_KEY, None)
    return start_authorization(slug, "register")


def callback(slug):
    _active(slug)
    flow = consume_flow(session, slug, request.args.get('state', ''))
    if flow is None or flow['operation'] != 'register':
        abort(400)
    claims = verified_claims()
    if not claims or claims.get('email_verified') is not True:
        abort(403)
    # Handle + binding are kept in the server-signed session; browser POST never
    # supplies sub/email. Fresh random binding invalidates any previous flow.
    binding = secrets.token_urlsafe(32)
    with closing(google_connection(slug)) as con:
        try:
            handle = start(con, subject=claims["sub"], email=claims.get("email"),
                           email_verified=claims.get("email_verified"),
                           name=claims.get("name") or claims.get("email"),
                           session_binding=binding)
        except PendingRegistrationInvalid:
            abort(403)
    session[HANDLE_KEY] = {'slug': slug, 'handle': handle}
    session[BINDING_KEY] = binding
    return redirect(url_for('participant_google_registration.phone_form', slug=slug))


@bp.get('/movil')
def phone_form(slug):
    _active(slug)
    pending = session.get(HANDLE_KEY)
    if not isinstance(pending, dict) or pending.get('slug') != slug or not session.get(BINDING_KEY):
        abort(403)
    return render_template_string('''<!doctype html><html lang="es"><meta charset="utf-8">
    <title>Completar registro Google</title><h1>Completar registro</h1>
    <p>Indica tu móvil obligatorio. Actualmente no se envían códigos SMS;
    el teléfono permanecerá registrado como no verificado.</p>
    <form method="post" action="{{ action }}">
    <input type="hidden" name="_csrf" value="{{ csrf }}">
    <label>Móvil <input name="phone" autocomplete="tel" required maxlength="20"></label>
    <button type="submit">Finalizar registro</button></form></html>''',
    action=url_for('.complete', slug=slug), csrf=token())


@bp.post('/finalizar')
def complete(slug):
    _active(slug)
    pending = session.get(HANDLE_KEY)
    binding = session.get(BINDING_KEY)
    if not isinstance(pending, dict) or pending.get('slug') != slug or not isinstance(binding, str):
        abort(403)
    with closing(google_connection(slug)) as con:
        try:
            participant_id = finish(con, handle=pending['handle'], session_binding=binding,
                                    phone=request.form.get('phone', ''))
        except InvalidRegistration:
            abort(400)
        except (PendingRegistrationInvalid, RegistrationConflict):
            abort(409)
        # Google ya ha acreditado el correo. El teléfono se almacena como
        # no verificado (phone_verified=0), sin simular envío de SMS.
        finish_verified_participant_session(session, con, slug, participant_id)
    return redirect(url_for('participants.account', slug=slug))
