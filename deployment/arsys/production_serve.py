"""Start the production baseline or a release selected by the coordinator."""

import json
import os
from pathlib import Path
import pwd
import re
import stat


ROOT = Path("/var/www/vhosts/dealfonso.com/rifas")
COORDINATOR = ROOT.parent / "rifas-deployment/production"
CONTROL = Path("/var/lib/rifas-production-control")
CALLBACK = "https://dealfonso.com/rifas/participantes/google/retorno"
ARGUMENTS = [
    "--workers", "2", "--bind", "127.0.0.1:8767",
    "--access-logfile", "-", "--error-logfile", "-", "wsgi:app",
]
GOOGLE_KEYS = {
    "RIFAS_GOOGLE_OAUTH_ENABLED", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI", "GOOGLE_BINDING_OTP_SECRET",
}


def google_settings(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {"RIFAS_GOOGLE_OAUTH_ENABLED": "0"}
    with os.fdopen(fd, encoding="ascii") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 8192):
            raise ValueError("Archivo privado de Google de PRODUCCIÓN inválido")
        values = {}
        for line in stream:
            key, sep, encoded = line.rstrip("\n").partition("=")
            if not sep or key not in GOOGLE_KEYS or key in values:
                raise ValueError("Entrada de Google inesperada")
            try:
                value = json.loads(encoded)
            except ValueError:
                raise ValueError("Formato inválido en la configuración de Google") from None
            if not isinstance(value, str) or not value or any(ord(ch) < 32 for ch in value):
                raise ValueError("Valor de Google inválido")
            values[key] = value
    if (values.keys() != GOOGLE_KEYS or values["RIFAS_GOOGLE_OAUTH_ENABLED"] not in {"0", "1"}
            or values["GOOGLE_REDIRECT_URI"] != CALLBACK or len(values["GOOGLE_BINDING_OTP_SECRET"]) < 32):
        raise ValueError("Configuración de Google incompleta o ajena a PRODUCCIÓN")
    return values


def selected_release():
    path = CONTROL / "release.json"
    if path.is_symlink():
        raise ValueError("Selector de PRODUCCIÓN no regular")
    if not path.exists():
        return ROOT
    if not path.is_file():
        raise ValueError("Selector de PRODUCCIÓN no regular")
    target = json.loads(path.read_text())
    if target["data"] != str(ROOT):
        raise ValueError("Raíz de datos ajena a PRODUCCIÓN")
    release = Path(target["release"])
    if release.resolve(strict=True) != release or not release.is_dir():
        raise ValueError("Ruta de release inválida")
    if release != ROOT and (
        release.parent.parent != ROOT / ".rifas-deploy/runs" or release.name != "payload"
        or not re.fullmatch(r"[a-f0-9]{32}", release.parent.name)
    ):
        raise ValueError("Release ajeno a PRODUCCIÓN")
    return release


def main():
    if os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "dealfonsocom":
        raise SystemExit("El selector de PRODUCCIÓN debe ejecutarse como dealfonsocom")
    release = selected_release()
    os.chdir(release)
    if release == ROOT:
        gunicorn = str(ROOT / "venv/bin/gunicorn")
        os.execv(gunicorn, [gunicorn, *ARGUMENTS])

    runtimes = COORDINATOR / "runtime"
    runtime = (runtimes / "current").resolve(strict=True)
    if runtime.parent != runtimes or not runtime.is_dir():
        raise ValueError("Entorno Python ajeno a PRODUCCIÓN")
    environment = {
        **os.environ, **google_settings(COORDINATOR / "config/google-oauth.env"),
        "RIFAS_DATA_ROOT": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
        "RIFAS_SESSION_COOKIE_NAME": "rifas_produccion_session",
        "RIFAS_SESSION_COOKIE_PATH": "/rifas",
    }
    python = str(runtime / "bin/python")
    os.execve(python, [python, "-B", "-m", "gunicorn", *ARGUMENTS], environment)


if __name__ == "__main__":
    main()
