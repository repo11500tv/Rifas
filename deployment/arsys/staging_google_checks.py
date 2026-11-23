"""Sondas HTTP y de compatibilidad para el release Google OAuth de PRUEBAS."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import ProxyHandler, build_opener

from deployment import schema
from deployment.smoke import NoRedirect, fetch


STAGE = Path("/var/www/vhosts/dealfonso.com/rifas/staging/prueba_231")
BASE_URL = "http://127.0.0.1:8768"
GOOGLE_CONFIG = Path("/var/www/vhosts/dealfonso.com/rifas-deployment/staging/config/google-oauth.env")
CALLBACK = "https://dealfonso.com/rifas-pruebas/participantes/google/retorno"


def google_expected():
    if not GOOGLE_CONFIG.exists():
        return False
    with GOOGLE_CONFIG.open(encoding="ascii") as config:
        flags = [line.split("=", 1)[1].strip() for line in config
                 if line.startswith("RIFAS_GOOGLE_OAUTH_ENABLED=")]
    if flags in (["1"], ['"1"']):
        return True
    if flags in (["0"], ['"0"']):
        return False
    raise ValueError("Estado de Google OAuth de PRUEBAS indeterminado")


def check_google_redirect(opener, path):
    try:
        fetch(opener, BASE_URL, path)
    except HTTPError as error:
        with error:
            target = urlsplit(error.headers.get("Location", ""))
            values = parse_qs(target.query)
            if (error.code in {302, 303} and target.scheme == "https" and target.hostname == "accounts.google.com"
                    and values.get("redirect_uri") == [CALLBACK]
                    and values.get("code_challenge_method") == ["S256"]):
                return
            raise ValueError("Redirección de Google OAuth de PRUEBAS inesperada") from None
    raise ValueError("El acceso con Google no devolvió una redirección")


def check(action):
    if os.environ.get("RIFAS_DEPLOY_ENVIRONMENT") != "staging" or os.environ.get("RIFAS_DATA_ROOT") != str(STAGE):
        raise ValueError("Las sondas Google requieren el entorno PRUEBAS")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    if json.loads(fetch(opener, BASE_URL, "/health")) != {"status": "ok", "version": "2.3.1"}:
        raise ValueError("Identidad o versión inesperada en PRUEBAS")
    if action == "ready":
        return
    enabled = google_expected()
    if not enabled:
        try:
            fetch(opener, BASE_URL, "/participantes/google/retorno")
        except HTTPError as error:
            with error:
                if error.code != 404:
                    raise
        else:
            raise ValueError("Google OAuth responde aunque está desactivado en PRUEBAS")
    central = schema.safe_database(STAGE, schema.CENTRAL, dry=False)
    with closing(schema.connect(central, "mode=ro")) as connection:
        active = connection.execute("SELECT slug FROM entities WHERE status = 'active' ORDER BY slug").fetchall()
    if not active:
        raise ValueError("PRUEBAS necesita una entidad activa para comprobar el acceso por correo")
    for (slug,) in active:
        prefix = "/e/" + quote(slug, safe="") + "/participantes"
        fetch(opener, BASE_URL, prefix + "/acceso-codigo")
        if enabled:
            check_google_redirect(opener, prefix + "/google/iniciar")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("ready", "google-oidc"))
    check(parser.parse_args().action)


if __name__ == "__main__":
    main()
