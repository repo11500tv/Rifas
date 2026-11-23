"""Single OAuth return endpoint, dispatching to the verified per-operation handlers.

The session is the only source for entity and operation; query parameters cannot
select a participant, entity or operation. The individual handlers consume state.
"""
from flask import Blueprint, abort, request, session
from platform_app.participant_google_flow import KEY

bp = Blueprint('participant_google_callback_shared', __name__, url_prefix='/participantes/google')


def resolve_callback(session_data, state):
    from platform_app.participant_google_flow import valid_flow
    pending = session_data.get(KEY)
    if not isinstance(pending, dict) or not isinstance(pending.get('slug'), str):
        return None
    slug = pending['slug']
    flow = valid_flow(session_data, slug, state)
    if flow is None:
        return None
    return slug, flow['operation']


@bp.get('/retorno')
def callback():
    destination = resolve_callback(session, request.args.get('state', ''))
    if destination is None:
        # An unsolicited invalid callback must not cancel a legitimate pending
        # authorization in this browser session. The valid callback is consumed
        # by consume_flow before token exchange.
        abort(400)
    slug, operation = destination
    if operation == 'login':
        from platform_app.participant_google_oidc_routes import google_callback
        return google_callback(slug)
    if operation == 'register':
        from platform_app.participant_google_registration_routes import callback as registration_callback
        return registration_callback(slug)
    from platform_app.participant_google_binding_routes import callback as binding_callback
    return binding_callback(slug)
