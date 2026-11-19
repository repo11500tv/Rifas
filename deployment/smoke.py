"""Consultas HTTP de solo lectura para hooks de disponibilidad y Sorteos."""

import argparse
import json
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def fetch(opener, base, path):
    request = Request(base + path, headers={"User-Agent": "rifas-deploy-smoke/1"})
    with opener.open(request, timeout=10) as response:
        data = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(data) > 1024 * 1024:
            raise ValueError(f"Respuesta inesperada: {path}")
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--raffle-id", type=int)
    parser.add_argument("--marker")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        parser.error("--base requiere una URL explícita del servicio sin credenciales")
    if args.raffle_id is not None and (args.raffle_id < 1 or not args.marker):
        parser.error("--raffle-id requiere un ID positivo y --marker")
    if args.marker and args.raffle_id is None:
        parser.error("--marker requiere --raffle-id")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    prefix = "/e/" + quote(args.slug, safe="")
    if args.raffle_id is None:
        health = json.loads(fetch(opener, base, "/health"))
        if health != {"status": "ok", "version": args.version}:
            raise ValueError("Aplicación o versión incorrecta")
        fetch(opener, base, prefix + "/")
    elif args.marker.encode() not in fetch(opener, base, f"{prefix}/sorteos/{args.raffle_id}/informacion"):
        raise ValueError("Falta el contenido esperado de Sorteos")


if __name__ == "__main__":
    main()
