"""Flask, Authlib y SQLite locales. Sin Google real, red ni bases activas."""

from contextlib import closing
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from flask import redirect
from joserfc import jwt
from joserfc.jwk import RSAKey

import platform_app
from deployment import schema
from platform_app.participant_google_flow import KEY
from platform_app.participant_google_schema import validate_google_schema
from platform_app.participant_schema_complete import initialize_participant_schema
from platform_app.raffle_schema import SCHEMA_RAFFLES

PROJECT = Path(__file__).resolve().parents[1]
CALLBACK = "/participantes/google/retorno"
ISSUER = "https://accounts.google.com"


class FakeGoogle:
    def __init__(self):
        self.claims = {"iss": ISSUER, "sub": "fixture-google-subject", "email": "member@example.invalid",
                       "email_verified": True, "name": "Participante de prueba"}
        self.exchanges = 0

    def authorize_redirect(self, redirect_uri, *, state, nonce):
        assert redirect_uri == "https://rifas.example.invalid" + CALLBACK and nonce
        return redirect("https://google.example.invalid/auth?state=" + state)

    def authorize_access_token(self):
        self.exchanges += 1
        return {"id_token": "verified-fixture", "userinfo": self.claims.copy()}


class GoogleOAuthTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="rifas-google-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.central = self.root / schema.CENTRAL
        self.template = self.root / schema.TEMPLATE
        self.entities = self.root / "entidades"
        self.central.parent.mkdir()
        (self.central.parent / "secret.key").write_text(secrets.token_urlsafe(48))
        with closing(sqlite3.connect(self.central)) as db:
            db.executescript(platform_app.SCHEMA)
            for field in ("logo_path", "public_name", "primary_color", "secondary_color"):
                db.execute(f"ALTER TABLE entities ADD COLUMN {field} TEXT")
            db.executemany("INSERT INTO entities(slug,name,admin_email,status) VALUES (?,?,?,?)", [
                ("alpha", "Entidad de prueba A", "admin@example.invalid", "active"),
                ("beta", "Entidad de prueba B", "admin@example.invalid", "active"),
                ("disabled", "Entidad suspendida", "admin@example.invalid", "suspended"),
            ])
            db.commit()
        for path in [self.template, *(self.path(slug) for slug in ("alpha", "beta", "disabled"))]:
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path)) as db:
                initialize_participant_schema(db)
                db.executescript(SCHEMA_RAFFLES + """
                    CREATE TABLE module_versions(module TEXT PRIMARY KEY, version TEXT, updated_at TEXT);
                    INSERT INTO module_versions VALUES ('sorteos','2.4.0',CURRENT_TIMESTAMP);
                """)
        settings = patch.multiple(platform_app, ROOT=self.root, DB=self.central, ENTITIES=self.entities)
        settings.start()
        self.addCleanup(settings.stop)
        self.recipe = json.loads((PROJECT / "deployment/packages/google_oauth_2.4.2.json").read_text())
        self.contract = self.recipe["schema"]

    def path(self, slug):
        return self.entities / slug / "data" / "rifas.sqlite3"

    def test_access_shows_google_button_and_leaves_registration_on_portal(self):
        self.migrate()
        for enabled in (False, True):
            with self.subTest(google=enabled):
                client = self.app(enabled=enabled).test_client()
                access = client.get("/e/alpha/participantes/acceso").get_data(as_text=True)
                self.assertIn("Acceder con código por correo", access)
                self.assertNotIn("Nuevo participante", access)
                if enabled:
                    self.assertRegex(access, r'<a href="[^"]+/google/iniciar" style="display:block;[^"]+">Acceder con Google</a>')
                else:
                    self.assertNotIn("Acceder con Google", access)
                portal = client.get("/e/alpha/").get_data(as_text=True)
                self.assertIn("Nuevo participante", portal)

    def migrate(self):
        contract = self.contract
        expected = schema.expected_schema(PROJECT, contract)
        paths = schema.validate(self.root, contract, expected=expected, dry=True)
        results = []
        schema.migrate(self.root, paths, contract, self.recipe["migration"], PROJECT,
                       lambda name, **fields: results.append(name))
        self.assertEqual(results, ["migrated"] * 4)
        self.assertEqual(schema.validate(self.root, contract, expected=expected, target=True), paths)
        results.clear()
        schema.migrate(self.root, paths, contract, self.recipe["migration"], PROJECT,
                       lambda name, **fields: results.append(name))
        self.assertEqual(results, ["migration_skipped"] * 4)

    def app(self, enabled=True, fake=True):
        env = {
            "RIFAS_GOOGLE_OAUTH_ENABLED": "1" if enabled else "0",
            "RIFAS_SESSION_COOKIE_PATH": "/",
            "GOOGLE_CLIENT_ID": "fixture-client-id",
            "GOOGLE_CLIENT_SECRET": "fixture-client-secret",
            "GOOGLE_REDIRECT_URI": "https://rifas.example.invalid" + CALLBACK,
            "GOOGLE_BINDING_OTP_SECRET": secrets.token_urlsafe(48),
        }
        with patch.dict(os.environ, env):
            application = platform_app.create_app()
        application.testing = True
        if enabled and fake:
            self.fake = FakeGoogle()
            application.extensions["participant_google_oauth"] = type("FakeOAuth", (), {"google": self.fake})()
        return application

    def start(self, client, slug, operation="login"):
        if operation == "register":
            url = f"/e/{slug}/participantes/google/registro/iniciar"
            response = client.get(url)
        elif operation in ("link", "replace"):
            url = f"/e/{slug}/participantes/google/cuenta/{operation}/iniciar"
            response = client.post(url, data={"_csrf": self.csrf(client)})
        else:
            response = client.get(f"/e/{slug}/participantes/google/iniciar")
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response.location).query)
        return query["state"][0]

    def csrf(self, client):
        with client.session_transaction() as state:
            if "_csrf" not in state:
                state["_csrf"] = secrets.token_urlsafe(32)
            return state["_csrf"]

    def callback(self, client, state):
        return client.get(CALLBACK, query_string={"state": state, "code": "fixture-exchange"})

    def finish(self, client, slug, phone="+12025550101", csrf=True):
        return client.post(f"/e/{slug}/participantes/google/registro/finalizar",
                           data={"phone": phone, "_csrf": self.csrf(client) if csrf else ""})

    def register(self, client, slug="alpha"):
        response = self.callback(client, self.start(client, slug, "register"))
        self.assertTrue(response.location.endswith("/movil"))
        self.assertEqual(self.finish(client, slug).status_code, 302)
        with client.session_transaction() as state:
            self.assertEqual(state["participant_slug"], slug)
            return state["participant_id"]

    def test_disabled_by_default_and_legacy_routes_remain(self):
        with patch.dict(os.environ):
            os.environ.pop("RIFAS_GOOGLE_OAUTH_ENABLED", None)
            app = platform_app.create_app()
        client = app.test_client()
        self.assertEqual(client.get(CALLBACK).status_code, 404)
        self.assertEqual(client.get("/e/alpha/participantes/acceso-codigo").status_code, 200)
        self.assertEqual(client.get("/e/alpha/participantes/registro").status_code, 302)

    def test_requires_template_and_canonical_callback_before_activation(self):
        with self.assertRaisesRegex(RuntimeError, "tablas de identidad"):
            self.app()
        self.migrate()
        with patch.dict(os.environ, {"RIFAS_GOOGLE_OAUTH_ENABLED": "1",
                                     "GOOGLE_REDIRECT_URI": "http://fixture.invalid" + CALLBACK}):
            with self.assertRaisesRegex(RuntimeError, "configuración válida"):
                platform_app.create_app()

    def test_google_primary_and_email_links_available(self):
        self.migrate()
        client = self.app().test_client()
        response = client.get("/e/alpha/participantes/acceso")
        self.assertLess(response.data.index(b"Acceder con Google"), response.data.index("código por correo".encode()))
        self.assertIn(b"Registrarse por correo", client.get("/e/alpha/participantes/registro").data)
        self.assertEqual(client.get("/e/alpha/participantes/acceso-codigo").status_code, 200)

    def test_registration_phone_required_csrf_and_no_sms(self):
        self.migrate()
        client = self.app().test_client()
        self.callback(client, self.start(client, "alpha", "register"))
        self.assertEqual(self.finish(client, "alpha", csrf=False).status_code, 400)
        self.assertEqual(self.finish(client, "alpha", phone="").status_code, 400)
        self.assertEqual(self.finish(client, "beta").status_code, 403)
        self.assertEqual(self.finish(client, "alpha").status_code, 302)
        with client.session_transaction() as state:
            participant = state["participant_id"]
        self.assertEqual(self.finish(client, "alpha").status_code, 403)
        with closing(sqlite3.connect(self.path("alpha"))) as db:
            row = db.execute("SELECT email_verified,phone_verified,phone FROM participants WHERE id=?", (participant,))
            self.assertEqual(row.fetchone(), (1, 0, "+12025550101"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM participant_codes WHERE channel='sms'").fetchone()[0], 0)

    def test_login_rejects_unlinked_and_keeps_identities_per_entity(self):
        self.migrate()
        app = self.app()
        client = app.test_client()
        first = self.register(client)
        client = app.test_client()
        self.assertEqual(self.callback(client, self.start(client, "beta")).status_code, 403)
        second = self.register(client, "beta")
        client = app.test_client()
        self.assertEqual(self.callback(client, self.start(client, "alpha")).status_code, 302)
        with client.session_transaction() as state:
            self.assertEqual((state["participant_slug"], state["participant_id"]), ("alpha", first))
        self.assertEqual(self.callback(client, self.start(client, "beta")).status_code, 302)
        with client.session_transaction() as state:
            self.assertEqual((state["participant_slug"], state["participant_id"]), ("beta", second))
        self.assertEqual(client.get("/e/disabled/participantes/google/iniciar").status_code, 404)

    def test_state_wrong_expired_and_replayed(self):
        self.migrate()
        client = self.app().test_client()
        state = self.start(client, "alpha", "register")
        self.assertEqual(self.callback(client, "falso").status_code, 400)
        self.assertEqual(self.callback(client, "inválido").status_code, 400)
        self.assertEqual(self.fake.exchanges, 0)
        self.assertEqual(self.callback(client, state).status_code, 302)
        self.assertEqual(self.callback(client, state).status_code, 400)
        self.assertEqual(self.fake.exchanges, 1)
        state = self.start(client, "alpha", "register")
        with client.session_transaction() as stored:
            stored[KEY] = {**stored[KEY], "expires": 1}
        self.assertEqual(self.callback(client, state).status_code, 400)

    def test_existing_email_requires_explicit_link_and_otp(self):
        self.migrate()
        with closing(sqlite3.connect(self.path("alpha"))) as db:
            db.execute("INSERT INTO participants(name,email,phone,email_verified) VALUES (?,?,?,1)",
                       ("Cuenta previa", self.fake_email, "+12025550102"))
            db.commit()
        app = self.app()
        client = app.test_client()
        self.assertEqual(self.callback(client, self.start(client, "alpha")).status_code, 403)
        self.callback(client, self.start(client, "alpha", "register"))
        self.assertEqual(self.finish(client, "alpha").status_code, 409)
        with closing(sqlite3.connect(self.path("alpha"))) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM participant_external_identities").fetchone()[0], 0)
        path = "/e/alpha/participantes/google/cuenta/link/iniciar"
        self.assertEqual(client.post(path, data={"_csrf": self.csrf(client)}).status_code, 403)
        with client.session_transaction() as state:
            state["participant_slug"] = "alpha"
            state["participant_id"] = 1
        self.assertEqual(client.post(path, data={"_csrf": "inválido"}).status_code, 400)
        codes = []

        def email(_db, _recipient, _subject, message):
            codes.append(re.search(r"\b[0-9]{6}\b", message)[0])

        with patch("platform_app.participant_google_binding_email.send_entity_email", side_effect=email):
            state = self.start(client, "alpha", "link")
            self.assertEqual(self.callback(client, state).status_code, 302)
            verify = "/e/alpha/participantes/google/cuenta/verificar"
            wrong = "000000" if codes[0] != "000000" else "000001"
            self.assertEqual(client.post(verify, data={"code": wrong, "_csrf": self.csrf(client)}).status_code, 200)
            self.assertEqual(client.post("/e/beta/participantes/google/cuenta/verificar",
                                         data={"code": codes[0], "_csrf": self.csrf(client)}).status_code, 403)
            with client.session_transaction() as stored:
                previous_session = dict(stored)
            self.assertEqual(client.post(verify, data={"code": codes[0], "_csrf": self.csrf(client)}).status_code, 302)
            self.assertEqual(client.post(verify, data={"code": codes[0], "_csrf": self.csrf(client)}).status_code, 403)
            # Even a stale signed cookie cannot consume the same database OTP.
            with client.session_transaction() as stored:
                stored.update(previous_session)
            replay = client.post(verify, data={"code": codes[0], "_csrf": self.csrf(client)})
            self.assertEqual(replay.status_code, 200)
            self.assertIn(b"incorrecto", replay.data)
            self.fake.claims["sub"] = "fixture-replacement"
            state = self.start(client, "alpha", "replace")
            self.assertEqual(self.callback(client, state).status_code, 302)
            self.assertEqual(client.post(verify, data={"code": codes[1], "_csrf": self.csrf(client)}).status_code, 302)
        fresh = app.test_client()
        self.assertEqual(self.callback(fresh, self.start(fresh, "alpha")).status_code, 302)

    fake_email = "member@example.invalid"

    def test_existing_email_otp_authenticates_and_clears_google_pending(self):
        self.migrate()
        app = self.app()
        client = app.test_client()
        self.register(client)
        client = app.test_client()
        self.start(client, "alpha", "register")
        codes = []
        with patch("platform_app.participant_login_service_v2.send_login_code",
                   side_effect=lambda _db, _address, code: codes.append(code)):
            client.post("/e/alpha/participantes/acceso-codigo",
                        data={"email": self.fake_email, "_csrf": self.csrf(client)})
        self.assertEqual(len(codes), 1)
        response = client.post("/e/alpha/participantes/verificar-acceso",
                               data={"code": codes[0], "_csrf": self.csrf(client)})
        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as state:
            self.assertEqual(state["participant_slug"], "alpha")
            self.assertNotIn(KEY, state)
        self.assertEqual(client.post("/e/alpha/participantes/salir",
                                     data={"_csrf": self.csrf(client)}).status_code, 302)
        with client.session_transaction() as state:
            self.assertNotIn("participant_id", state)

    def test_failed_google_migration_does_not_leave_tables_or_stamp(self):
        from platform_app.participant_google_schema import migrate_google_schema
        with closing(sqlite3.connect(":memory:")) as db:
            db.execute("CREATE TABLE participants(id INTEGER PRIMARY KEY)")
            db.execute("CREATE TABLE module_versions(module TEXT PRIMARY KEY, version TEXT, updated_at TEXT)")
            with self.assertRaisesRegex(RuntimeError, "esquema de participantes"):
                migrate_google_schema(db)
            self.assertFalse(db.in_transaction)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM module_versions").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_schema WHERE name LIKE 'participant_google_%'")
                             .fetchone(), (0,))

    def test_master_template_clones_prepared_google_schema(self):
        self.migrate()
        client = self.app().test_client()
        with client.session_transaction() as state:
            state["admin"] = "fixture"
        response = client.post("/entidades/nueva", data={
            "slug": "new", "name": "Nueva", "email": "creator@example.invalid", "_csrf": self.csrf(client),
        })
        self.assertEqual(response.status_code, 302)
        with closing(sqlite3.connect(self.path("new"), uri=False)) as db:
            validate_google_schema(db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM participant_external_identities").fetchone(), (0,))

    def test_authlib_validates_signed_token_pkce_issuer_audience_nonce_and_expiry(self):
        self.migrate()
        application = self.app(fake=False)
        remote = application.extensions["participant_google_oauth"].google
        signing = RSAKey.generate_key(2048, parameters={"kid": "synthetic"})
        wrong_key = RSAKey.generate_key(2048, parameters={"kid": "synthetic"})
        metadata = {
            "issuer": ISSUER, "authorization_endpoint": "https://google.example.invalid/auth",
            "token_endpoint": "https://google.example.invalid/token",
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        cases = [
            ({}, signing, 302), ({"aud": "wrong"}, signing, 401),
            ({"iss": "https://issuer.example.invalid"}, signing, 401),
            ({"nonce": "wrong"}, signing, 401), ({"exp": 1}, signing, 401), ({}, wrong_key, 401),
        ]
        with (patch.object(remote, "load_server_metadata", return_value=metadata),
              patch.object(remote, "fetch_jwk_set", return_value={"keys": [signing.as_dict(private=False)]})):
            for changes, key, expected in cases:
                with self.subTest(changes=changes, signature=key is signing):
                    client = application.test_client()
                    response = client.get("/e/alpha/participantes/google/registro/iniciar",
                                          base_url="https://untrusted.example.invalid")
                    query = parse_qs(urlsplit(response.location).query)
                    self.assertEqual(query["redirect_uri"], ["https://rifas.example.invalid" + CALLBACK])
                    self.assertEqual(query["code_challenge_method"], ["S256"])
                    now = int(time.time())
                    claims = {
                        "iss": ISSUER, "sub": "fixture-token-subject", "email": self.fake_email,
                        "email_verified": True, "name": "Nombre de prueba", "aud": "fixture-client-id",
                        "iat": now, "exp": now + 300, "nonce": query["nonce"][0], **changes,
                    }
                    encoded = jwt.encode({"alg": "RS256", "kid": "synthetic"}, claims, key)
                    with patch.object(remote, "fetch_access_token", return_value={"id_token": encoded}) as fetch:
                        response = client.get(CALLBACK, base_url="https://untrusted.example.invalid",
                                              query_string={"code": "fixture", "state": query["state"][0]})
                    self.assertEqual(response.status_code, expected)
                    self.assertTrue(fetch.call_args.kwargs.get("code_verifier"))


if __name__ == "__main__":
    unittest.main()
