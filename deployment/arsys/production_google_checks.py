"""Read-only health and participant access checks for production."""

import argparse
from contextlib import closing
import json
import os
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import ProxyHandler, build_opener

from deployment import schema
from deployment.arsys.production_serve import CALLBACK, COORDINATOR, ROOT, google_settings
from deployment.smoke import NoRedirect, fetch


BASE = "http://127.0.0.1:8767"


def check(action):
    if os.environ.get("RIFAS_DEPLOY_ENVIRONMENT") != "production" or os.environ.get("RIFAS_DATA_ROOT") != str(ROOT):
        raise ValueError("Las sondas solo admiten PRODUCCIÓN")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    if json.loads(fetch(opener, BASE, "/health")) != {"status": "ok", "version": "2.3.1"}:
        raise ValueError("Versión inesperada del servicio de PRODUCCIÓN")
    if action == "ready":
        return
    enabled = google_settings(COORDINATOR / "config/google-oauth.env")["RIFAS_GOOGLE_OAUTH_ENABLED"] == "1"
    if not enabled:
        try:
            fetch(opener, BASE, "/participantes/google/retorno")
        except HTTPError as error:
            with error:
                if error.code != 404:
                    raise
        else:
            raise ValueError("Google OAuth responde aunque está desactivado")
    with closing(schema.connect(schema.safe_database(ROOT, schema.CENTRAL, dry=False), "mode=ro")) as connection:
        entities = connection.execute("SELECT slug FROM entities WHERE status = 'active' ORDER BY slug").fetchall()
    if not entities:
        raise ValueError("No se pudo verificar el acceso de ninguna entidad activa")
    for (slug,) in entities:
        prefix = "/e/" + quote(slug, safe="") + "/participantes"
        fetch(opener, BASE, prefix + "/acceso-codigo")
        if enabled:
            try:
                fetch(opener, BASE, prefix + "/google/iniciar")
            except HTTPError as error:
                with error:
                    target = urlsplit(error.headers.get("Location", ""))
                    params = parse_qs(target.query)
                    if (error.code in {302, 303} and target.scheme == "https"
                            and target.hostname == "accounts.google.com" and params.get("redirect_uri") == [CALLBACK]
                            and params.get("code_challenge_method") == ["S256"]):
                        continue
            raise ValueError("Redirección de Google OAuth de PRODUCCIÓN inesperada")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("ready", "google-oidc"))
    check(parser.parse_args().action)
