"""Sondas HTTP y de compatibilidad para el release Google OAuth de PRUEBAS."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

from deployment import schema
from deployment.smoke import NoRedirect, fetch


STAGE = Path("/var/www/vhosts/dealfonso.com/rifas/staging/prueba_231")
BASE_URL = "http://127.0.0.1:8768"


def check(action):
    if os.environ.get("RIFAS_DEPLOY_ENVIRONMENT") != "staging" or os.environ.get("RIFAS_DATA_ROOT") != str(STAGE):
        raise ValueError("Las sondas Google requieren el entorno PRUEBAS")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    if json.loads(fetch(opener, BASE_URL, "/health")) != {"status": "ok", "version": "2.3.1"}:
        raise ValueError("Identidad o versión inesperada en PRUEBAS")
    if action == "ready":
        return
    try:
        fetch(opener, BASE_URL, "/participantes/google/retorno")
    except HTTPError as error:
        with error:
            if error.code != 404:
                raise
    else:
        raise ValueError("La primera instalación debe mantener desactivado Google OAuth")
    central = schema.safe_database(STAGE, schema.CENTRAL, dry=False)
    with closing(schema.connect(central, "mode=ro")) as connection:
        active = connection.execute("SELECT slug FROM entities WHERE status = 'active' ORDER BY slug").fetchall()
    if not active:
        raise ValueError("PRUEBAS necesita una entidad activa para comprobar el acceso por correo")
    for (slug,) in active:
        fetch(opener, BASE_URL, "/e/" + quote(slug, safe="") + "/participantes/acceso-codigo")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("ready", "google-oidc"))
    check(parser.parse_args().action)


if __name__ == "__main__":
    main()
