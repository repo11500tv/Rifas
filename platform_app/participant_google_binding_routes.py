"""Vincular o sustituir Google con OIDC y OTP por correo.

La identidad Google se obtiene exclusivamente del ID token verificado por Authlib.
"""
import hashlib
import os
import secrets
import time
from html import escape

from flask import Blueprint, abort, current_app, redirect, request, session, url_for
from platform_app.entity_routes import get_entity, layout, token
from platform_app.participant_account_access_v2 import participant_can_access
from platform_app.participant_google_flow import consume_flow
from platform_app.participant_google_oidc_routes import google_connection, start_authorization, verified_claims
from platform_app.participant_google_binding_email import request_google_binding_code, GoogleBindingResendTooSoon
from platform_app.participant_combined_guard import CombinedLimitExceeded
from platform_app.participant_google_binding_core import bind_verified_identity

bp = Blueprint('participant_google_binding', __name__, url_prefix='/e/<slug>/participantes/google/cuenta')
PENDING_KEY = '_google_binding_pending'
TTL = 300


def _entity_and_participant(slug):
    entity = get_entity(slug)
    if entity is None or entity['status'] != 'active':
        abort(404)
    pid = session.get('participant_id')
    if session.get('participant_slug') != slug or type(pid) is not int or pid <= 0:
        abort(403)
    connection = google_connection(slug)
    try:
        if not participant_can_access(connection, pid):
            abort(403)
    finally:
        connection.close()
    return entity, pid


def _secret():
    # Prefer an independent secret from the Flask session signing key.
    raw = current_app.config.get('GOOGLE_BINDING_OTP_SECRET') or os.environ.get('GOOGLE_BINDING_OTP_SECRET')
    if not isinstance(raw, str) or len(raw.encode('utf-8')) < 32:
        abort(503)
    return raw.encode('utf-8')


def _digest(slug, participant_id, purpose, flow_id, subject):
    # Entity, participant, purpose, flow and verified subject are all bound.
    message = '\x00'.join((slug, str(participant_id), purpose, flow_id, subject))
    return hashlib.sha256(message.encode('utf-8')).hexdigest()


def _pending(slug, pid):
    pending = session.get(PENDING_KEY)
    if not isinstance(pending, dict) or pending.get('slug') != slug or pending.get('participant_id') != pid:
        return None
    if pending.get('expires', 0) <= int(time.time()):
        session.pop(PENDING_KEY, None)
        return None
    if pending.get('purpose') not in ('link', 'replace') or not isinstance(pending.get('subject'), str):
        return None
    return pending


@bp.post('/<purpose>/iniciar')
def start(slug, purpose):
    _, pid = _entity_and_participant(slug)
    if purpose not in ('link', 'replace'):
        abort(404)
    session.pop(PENDING_KEY, None)
    return start_authorization(slug, purpose, pid)


def callback(slug):
    _, pid = _entity_and_participant(slug)
    flow = consume_flow(session, slug, request.args.get('state', ''))
    if flow is None or flow['operation'] not in ('link', 'replace') or flow['participant_id'] != pid:
        abort(400)
    claims = verified_claims()
    subject = claims.get('sub') if claims is not None else None
    if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
        abort(401)
    flow_id = secrets.token_urlsafe(32)
    purpose = flow['operation']
    digest = _digest(slug, pid, purpose, flow_id, subject)
    session[PENDING_KEY] = {'slug': slug, 'participant_id': pid, 'purpose': purpose,
                            'subject': subject, 'digest': digest, 'expires': int(time.time()) + TTL}
    connection = google_connection(slug)
    try:
        request_google_binding_code(connection, secret=_secret(), participant_id=pid,
                                    purpose=purpose, context_digest=digest,
                                    ip_address=request.remote_addr or 'unknown')
    except (GoogleBindingResendTooSoon, CombinedLimitExceeded):
        session.pop(PENDING_KEY, None)
        abort(429)
    except Exception:
        session.pop(PENDING_KEY, None)
        current_app.logger.warning('No se pudo emitir OTP de vinculación Google')
        abort(503)
    finally:
        connection.close()
    return redirect(url_for('participant_google_binding.verify', slug=slug))


@bp.route('/verificar', methods=['GET', 'POST'])
def verify(slug):
    entity, pid = _entity_and_participant(slug)
    pending = _pending(slug, pid)
    if pending is None:
        abort(403)
    message = ''
    if request.method == 'POST':
        code = request.form.get('code', '')
        connection = google_connection(slug)
        try:
            result = bind_verified_identity(
                connection, secret=_secret(), participant_id=pid,
                purpose=pending['purpose'], context_digest=pending['digest'],
                code=code, verified_google_subject=pending['subject'])
        finally:
            connection.close()
        if result in ('link', 'replace'):
            session.pop(PENDING_KEY, None)
            return redirect(url_for('participants.account', slug=slug))
        if result in ('already_linked', 'already_linked_elsewhere', 'not_linked', 'unchanged'):
            session.pop(PENDING_KEY, None)
            abort(409)
        message = 'Código incorrecto o caducado.'
    body = ('<div class="card"><h2>Confirmar cuenta Google</h2>'
            '<p>Introduce el código enviado al correo de tu cuenta de participante.</p>'
            '<p>' + escape(message) + '</p><form method="post">'
            '<input type="hidden" name="_csrf" value="' + escape(str(token()), quote=True) + '">'
            '<input name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required>'
            '<button type="submit">Confirmar</button></form></div>')
    return layout('Confirmar Google - ' + entity['name'], body)
