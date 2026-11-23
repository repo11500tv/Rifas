"""Adaptador reutilizable de barrera de proxy y supervisor local."""

import argparse
import json
import os
import re
import stat
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from deployment.smoke import NoRedirect
from deployment.backup_integral import atomic_json, sync


def probe_status(opener, url):
    try:
        with opener.open(url, timeout=2) as response:
            return response.status
    except HTTPError as error:
        with error:
            if error.code == 401:
                challenges = error.headers.get_all("WWW-Authenticate", [])
                if not any(re.match(r"(?i)^basic(?:[ \t]|$)", value.strip()) for value in challenges):
                    return None
            return error.code
    except (OSError, URLError):
        return None


class Hooks:
    def __init__(self, settings):
        self.gate = Path(settings["gate"])
        self.target = Path(settings["target"])
        self.settings = settings
        for path in (self.gate, self.target):
            if (not path.is_absolute() or path.resolve() != path or path.is_relative_to("/root")
                    or not path.parent.is_dir()):
                raise ValueError("El control requiere rutas locales y directorios preaprovisionados")
        if self.gate == self.target:
            raise ValueError("La barrera y la selección de release deben tener rutas distintas")
        self.scope = settings.get("scope")
        if self.scope is not None:
            if self.scope["environment"] not in {"synthetic", "staging", "production"}:
                raise ValueError("Entorno de hooks inválido")
            self.data_root = Path(self.scope["data_root"])
            self.baseline = Path(self.scope["baseline"])
            for path in (self.data_root, self.baseline):
                if not path.is_absolute() or path.resolve() != path or path.is_relative_to("/root"):
                    raise ValueError("Raíz de hooks no canónica")
        self.control_root = Path(self.scope["control_root"]) if self.scope and "control_root" in self.scope else None
        if self.control_root is not None and (
            not self.control_root.is_absolute() or self.control_root.resolve() != self.control_root
            or self.control_root == Path("/") or self.control_root.is_relative_to("/root")
            or self.control_root.is_relative_to(self.data_root) or self.data_root.is_relative_to(self.control_root)
            or any(path.parent != self.control_root for path in (self.gate, self.target))
        ):
            raise ValueError("Barrera o selector fuera del directorio de control del entorno")
        self.unit = settings.get("systemd_unit")
        if self.unit is not None and (not self.control_root or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\.service", self.unit)
                                      or {"start", "stop"} & settings.keys()):
            raise ValueError("Unidad systemd inválida o combinada con comandos de supervisor")
        self.service_control = settings.get("service_control")
        if self.service_control is not None:
            if (self.unit is None or not isinstance(self.service_control, list)
                    or not self.service_control
                    or any(not isinstance(arg, str) or not arg for arg in self.service_control)
                    or not Path(self.service_control[0]).is_absolute()
                    or not os.access(self.service_control[0], os.X_OK)):
                raise ValueError("service_control exige unidad systemd y argv absoluto")
        gunicorn = settings["gunicorn"]
        self.python = Path(gunicorn["python"])
        self.arguments = gunicorn["arguments"]
        self.environment = gunicorn.get("environment", {})
        if (not self.python.is_absolute() or not os.access(self.python, os.X_OK)
                or not isinstance(self.arguments, list) or not all(isinstance(arg, str) for arg in self.arguments)
                or not isinstance(self.environment, dict)
                or not all(isinstance(value, str) for value in self.environment.values())):
            raise ValueError("Configuración de Gunicorn inválida")
        if not settings["closed_url"] or not settings["private_url"]:
            raise ValueError("Configurar sondas pública y privada del servicio")
        extra_urls = settings.get("additional_closed_urls", [])
        if not isinstance(extra_urls, list):
            raise ValueError("Las sondas públicas adicionales deben ser una lista")
        self.public_urls = [settings["closed_url"], *extra_urls]
        self.public_open_status = settings.get("public_open_status", 200)
        if self.public_open_status not in (200, 401):
            raise ValueError("La reapertura pública debe esperar HTTP 200 o autenticación Basic")
        for url in [*self.public_urls, settings["private_url"]]:
            parsed = urlsplit(url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
                    or parsed.query or parsed.fragment or parsed.port == 0):
                raise ValueError("Las sondas requieren URLs HTTP(S) explícitas sin credenciales")
        if self.unit and urlsplit(settings["private_url"]).hostname not in {"127.0.0.1", "::1"}:
            raise ValueError("La sonda privada de systemd debe usar loopback")
        for key in ("stop", "start", "pause_jobs", "resume_jobs"):
            command = settings.get(key)
            if (key in ("start", "stop") and self.unit is None) or command is not None:
                if (not isinstance(command, list) or not command
                        or not all(isinstance(arg, str) for arg in command)
                        or not Path(command[0]).is_absolute()):
                    raise ValueError(f"El comando {key} requiere argv y ejecutable absoluto")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def run(self, key):
        if self.unit is not None and key in {"start", "stop"}:
            command = ([*self.service_control, key] if self.service_control is not None
                       else ["/usr/bin/systemctl", key, self.unit])
            subprocess.run(command, check=True, timeout=40)
        elif key in self.settings:
            subprocess.run(self.settings[key], check=True, timeout=40)

    def check_scope(self, data, release):
        if self.scope is None:
            return
        if Path(data) != self.data_root:
            raise ValueError("La raíz de datos del hook pertenece a otra instalación")
        if release:
            path = Path(release)
            runs = self.data_root / ".rifas-deploy" / "runs"
            if (path.resolve() != path or (path != self.baseline and not (
                path.parent.parent == runs and path.name == "payload"
                and re.fullmatch(r"[a-f0-9]{32}", path.parent.name)
            ))):
                raise ValueError("El release del hook pertenece a otra instalación")

    def check_invocation(self):
        if self.scope is not None:
            if os.environ.get("RIFAS_DEPLOY_ENVIRONMENT") != self.scope["environment"]:
                raise ValueError("El hook pertenece a otro entorno")
            if self.control_root is not None and os.environ.get("RIFAS_CONTROL_ROOT") != str(self.control_root):
                raise ValueError("Directorio de control distinto del autorizado por el coordinador")
            if self.unit is not None and (
                os.environ.get("RIFAS_SYSTEMD_UNIT") != self.unit
                or os.environ.get("RIFAS_PRIVATE_PORT") != str(urlsplit(self.settings["private_url"]).port)
            ):
                raise ValueError("Unidad o puerto distintos de los validados por el coordinador")
            self.check_scope(os.environ.get("RIFAS_DATA_ROOT", ""), os.environ.get("RIFAS_RELEASE_ROOT"))

    def status(self, url):
        return probe_status(self.opener, url)

    def wait(self, url, expected):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.status(url) == expected:
                return
            time.sleep(0.1)
        raise RuntimeError(f"No se verificó HTTP {expected} en la sonda configurada")

    def close_gate(self):
        fd = os.open(self.gate, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Marcador de mantenimiento compartido o inseguro")
            os.fsync(fd)
        finally:
            os.close(fd)
        sync(self.gate.parent)
        for url in self.public_urls:
            self.wait(url, 503)

    def drain(self):
        self.check_invocation()
        self.close_gate()
        self.run("pause_jobs")
        self.run("stop")

    def activate(self):
        self.check_invocation()
        if os.environ.get("RIFAS_RELEASE_ROOT"):
            if not self.gate.is_file():
                raise RuntimeError("Activación exige una barrera cerrada")
            target = {"release": os.environ["RIFAS_RELEASE_ROOT"], "data": os.environ["RIFAS_DATA_ROOT"]}
            atomic_json(self.target, target)
            self.run("start")
            self.wait(self.settings["private_url"], 200)
        else:
            self.run("stop")
            self.target.unlink(missing_ok=True)
            sync(self.target.parent)

    def serve(self):
        target = json.loads(self.target.read_text())
        self.check_scope(target["data"], target["release"])
        release = Path(target["release"]).resolve(strict=True)
        data = Path(target["data"]).resolve(strict=True)
        if release.is_relative_to("/root") or data.is_relative_to("/root"):
            raise ValueError("Ruta del servicio no admitida")
        environment = {**os.environ, **self.environment, "RIFAS_DATA_ROOT": str(data),
                       "PYTHONDONTWRITEBYTECODE": "1"}
        os.chdir(release)
        os.execve(self.python, [str(self.python), "-B", "-m", "gunicorn", *self.arguments, "wsgi:app"], environment)

    def resume(self):
        self.check_invocation()
        if not os.environ.get("RIFAS_RELEASE_ROOT"):
            return
        self.wait(self.settings["private_url"], 200)
        try:
            self.run("resume_jobs")
            self.gate.unlink(missing_ok=True)
            sync(self.gate.parent)
            for url in self.public_urls:
                self.wait(url, self.public_open_status)
        except Exception:
            if self.public_open_status == 401:
                try:
                    try:
                        self.close_gate()
                    finally:
                        self.run("pause_jobs")
                except Exception as closure:
                    raise RuntimeError(
                        "Falló la reapertura y no se completó el nuevo cierre"
                    ) from closure
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("hook", choices=("drain", "activate", "resume", "serve"))
    args = parser.parse_args()
    hooks = Hooks(json.loads(args.config.read_text()))
    getattr(hooks, args.hook)()


if __name__ == "__main__":
    main()
