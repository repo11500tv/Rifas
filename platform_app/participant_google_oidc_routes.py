"""Google OIDC para participantes, habilitado explícitamente por instalación."""

import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from urllib.parse import urlsplit

from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client import OAuthError
from joserfc.errors import JoseError
from requests import RequestException
from flask import Blueprint, abort, current_app, redirect, request, session, url_for

from platform_app.entity_routes import edb
from platform_app.participant_google_flow import begin_flow, consume_flow
from platform_app.participant_google_login_core import (
    GoogleIdentityNotEligible, GoogleIdentityNotLinked, resolve_verified_google_login,
)
from platform_app.participant_google_schema import validate_google_schema
from platform_app.participant_routes import active_entity
from platform_app.participant_session_shared import finish_verified_participant_session

bp = Blueprint("participant_google_oidc", __name__, url_prefix="/e/<slug>/participantes/google")


def configure_google(app):
    keys = ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "GOOGLE_BINDING_OTP_SECRET")
    settings = {key: app.config.get(key) or os.environ.get(key) for key in keys}
    if not all(isinstance(value, str) and value.strip() for value in settings.values()):
        return False
    redirect_uri = urlsplit(settings["GOOGLE_REDIRECT_URI"])
    binding_key = settings["GOOGLE_BINDING_OTP_SECRET"]
    if (redirect_uri.scheme != "https" or not redirect_uri.hostname or redirect_uri.username is not None
            or redirect_uri.query or redirect_uri.fragment
            or not redirect_uri.path.endswith("/participantes/google/retorno")
            or len(binding_key.encode()) < 32 or binding_key == app.secret_key):
        return False
    app.config["GOOGLE_REDIRECT_URI"] = settings["GOOGLE_REDIRECT_URI"]
    app.config["GOOGLE_BINDING_OTP_SECRET"] = binding_key
    oauth = OAuth(app)
    oauth.register(
        name="google", client_id=settings["GOOGLE_CLIENT_ID"], client_secret=settings["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )
    app.extensions["participant_google_oauth"] = oauth
    return True


def google_connection(slug):
    connection = edb(slug)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        validate_google_schema(connection)
    except (RuntimeError, sqlite3.Error):
        connection.close()
        abort(503)
    return connection


def start_authorization(slug, operation, participant_id=None):
    with closing(google_connection(slug)):
        pass
    state, nonce = begin_flow(session, slug, operation, participant_id)
    try:
        return current_app.extensions["participant_google_oauth"].google.authorize_redirect(
            current_app.config["GOOGLE_REDIRECT_URI"], state=state, nonce=nonce,
        )
    except (OAuthError, RequestException):
        abort(503)


def verified_claims():
    # Authlib exchanges the one-time code with PKCE and validates the ID token
    # with the saved nonce. Never accept claims from an unverified profile call.
    try:
        response = current_app.extensions["participant_google_oauth"].google.authorize_access_token()
    except (OAuthError, JoseError, ValueError):
        abort(401)
    except RequestException:
        abort(503)
    claims = response.get("userinfo") if response.get("id_token") else None
    if (not isinstance(claims, Mapping)
            or claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}
            or not isinstance(claims.get("sub"), str) or not 1 <= len(claims["sub"]) <= 255):
        abort(401)
    return claims


@bp.get("/iniciar")
def start_google_login(slug):
    active_entity(slug)
    return start_authorization(slug, "login")


def google_callback(slug):
    active_entity(slug)
    flow = consume_flow(session, slug, request.args.get("state", ""))
    if flow is None or flow["operation"] != "login":
        abort(400)
    claims = verified_claims()
    with closing(google_connection(slug)) as connection:
        try:
            participant_id = resolve_verified_google_login(connection, claims["sub"])
            finish_verified_participant_session(session, connection, slug, participant_id)
        except (GoogleIdentityNotLinked, GoogleIdentityNotEligible, PermissionError):
            abort(403)
    return redirect(url_for("participants.account", slug=slug))
