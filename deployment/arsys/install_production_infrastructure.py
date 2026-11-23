"""Install the production coordinator infrastructure during a maintenance window."""

import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time

from deployment.arsys.production_serve import ARGUMENTS, CONTROL, COORDINATOR, ROOT
from deployment.arsys.production_service_bridge import LAUNCHER, SERVICE, WRITERS
from deployment.arsys.production_structure import FOREIGN, UNIT


NGINX = Path("/var/www/vhosts/system/dealfonso.com/conf/vhost_nginx.conf")
UNIT_DIR = Path("/etc/systemd/system/rifas-platform.service.d")
DROPIN = UNIT_DIR / "60-isolated-release-selector.conf"
SUDOERS = Path("/etc/sudoers.d/rifas-produccion-deploy")
SELECTOR = Path("/usr/local/sbin/rifas-produccion-serve")
LIBRARY = Path("/usr/local/lib/rifas-produccion")
CURRENT = COORDINATOR / "runtime/current"
MARKER = CONTROL / "maintenance"
PRIVATE = "http://127.0.0.1:8767/health"
PUBLIC = "https://dealfonso.com/rifas/health"
STAGING = "https://dealfonso.com/rifas-pruebas/health"


def call(*args, capture=False, check=True):
    return subprocess.run(args, check=check, capture_output=capture, text=True, timeout=90)


def show(name):
    return call("/usr/bin/systemctl", "show", UNIT, "-p", name, "--value", capture=True).stdout.strip()


def health(url):
    return call("/usr/bin/curl", "-s", "--max-time", "4", "-o", "/dev/null", "-w", "%{http_code}",
                url, capture=True, check=False).stdout


def wait_health(url, expected):
    for _ in range(15):
        if health(url) == expected:
            return
        time.sleep(1)
    raise ValueError(f"No se obtuvo HTTP {expected} en {url}")


def managed(path):
    info = path.lstat()
    if (path.resolve() != path or info.st_uid != 0 or info.st_mode & 0o022
            or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))):
        raise ValueError(f"Ruta administrativa no protegida: {path}")
    return info


def nginx_with_gate(original):
    block = rb"(?m)^([ \t]*)location[ \t]+/rifas/[ \t]*\{[ \t]*\n"
    anchors = list(re.finditer(block, original))
    if len(anchors) != 1 or os.fsencode(MARKER) in original:
        raise ValueError("La ubicación /rifas/ requiere revisión antes de instalar la barrera")
    match = anchors[0]
    first = original[match.end():].splitlines()[0:4]
    if not any(re.search(rb"^[ \t]*proxy_pass[ \t]+http://127\.0\.0\.1:8767(?:[/;]|$)", line) for line in first):
        raise ValueError("La ubicación /rifas/ no coincide con el backend esperado")
    rule = match[1] + b"    if (-f " + os.fsencode(MARKER) + b") { return 503; }\n"
    return original[:match.end()] + rule + original[match.end():]


def historical_files():
    files = [ROOT / "central/plantillas/entidad_maestra_antes_888_20261114_124946.sqlite3"]
    files.extend((ROOT / "platform_app").glob("*.py.bak_paso*"))
    files.extend((ROOT / "platform_app/__pycache__").glob("*.pyc"))
    blocked = []
    for path in files:
        if not path.is_file() or path.is_symlink() or path.resolve() != path:
            continue
        if call("/usr/sbin/runuser", "-u", "dealfonsocom", "--", "/usr/bin/test", "-r", str(path),
                check=False).returncode:
            blocked.append(path)
    return sorted(blocked)


def install_file(path, data, mode):
    with path.open("xb") as stream:
        stream.write(data)
        os.fchmod(stream.fileno(), mode)


def unit_definition():
    drop_paths = " ".join(map(str, (*FOREIGN, ROOT / ".rifas-deploy")))
    return (
        "[Service]\nUser=root\nGroup=root\nProtectSystem=strict\nPrivateTmp=yes\n"
        "NoNewPrivileges=yes\nEnvironment=PYTHONDONTWRITEBYTECODE=1\n"
        f"ReadWritePaths={ROOT / 'central'} {ROOT / 'entidades'}\nReadOnlyPaths={drop_paths}\n"
        "InaccessiblePaths=-/run/systemd/private -/run/dbus/system_bus_socket\n"
        "UnsetEnvironment=LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT GLIBC_TUNABLES\n"
        "ExecStart=\n"
        "ExecStart=/usr/bin/unshare --mount --pid --fork --mount-proc --kill-child=SIGTERM "
        "/usr/bin/setpriv --reuid=dealfonsocom --regid=psacln --init-groups "
        "--bounding-set=-all --inh-caps=-all --ambient-caps=-all --no-new-privs "
        f"/usr/bin/python3 -I -B {SELECTOR}\n"
    ).encode()


def main():
    if os.geteuid() != 0:
        raise ValueError("La intervención de infraestructura requiere al administrador")
    os.umask(0o077)
    sources = Path(__file__).resolve().parent
    for path in (sources, sources / "production_serve.py", sources / "production_launcher.sh",
                 sources.parent / "structure.py", NGINX, Path(SERVICE)):
        managed(path)
    for path in (CONTROL, UNIT_DIR, SUDOERS, SELECTOR, LIBRARY, CURRENT, Path(LAUNCHER), Path(WRITERS)):
        if path.exists() or path.is_symlink():
            raise ValueError(f"Ya existe. Se requiere revisión: {path}")
    for path in (ROOT / "central", ROOT / "entidades", ROOT / ".rifas-deploy", *FOREIGN):
        if not path.is_dir() or path.resolve() != path:
            raise ValueError(f"Ruta requerida inválida: {path}")
    runtime = COORDINATOR / "runtime/google-oauth-2.4.2-c9799a5"
    if runtime.resolve() != runtime or not (runtime / "bin/python").is_file():
        raise ValueError("No está disponible el entorno Python revisado")
    gunicorn = str(ROOT / "venv/bin/gunicorn")
    baseline = f"argv[]={gunicorn} {' '.join(ARGUMENTS)} ;"
    if (baseline not in show("ExecStart") or show("User") != "dealfonsocom" or show("Group") != "psacln"
            or show("Type") != "simple" or show("KillMode") != "control-group"
            or show("WorkingDirectory") != str(ROOT) or show("NeedDaemonReload") != "no"
            or any(show(p) for p in ("DropInPaths", "ExecStartPre", "ExecStartPost", "ExecStop", "ExecStopPost",
                                    "EnvironmentFiles", "PassEnvironment"))):
        raise ValueError("El arranque efectivo de PRODUCCIÓN difiere del observado")
    if any(not re.fullmatch(r"(?:RIFAS_[A-Z0-9_]+|GOOGLE_[A-Z0-9_]+|PYTHONUNBUFFERED|PYTHONDONTWRITEBYTECODE|HTTPS_ONLY)=.*", entry)
           for entry in shlex.split(show("Environment"))):
        raise ValueError("La unidad de PRODUCCIÓN contiene variables que requieren revisión")
    for url, expected in ((PRIVATE, "200"), (PUBLIC, "200"), (STAGING, "401")):
        wait_health(url, expected)
    original = NGINX.read_bytes()
    updated = nginx_with_gate(original)
    archive = Path(tempfile.mkdtemp(prefix=".production-infra-", dir=COORDINATOR.parent))
    (archive / "vhost_nginx.conf.original").write_bytes(original)
    moved = []
    files = []
    dirs = []
    nginx_changed = False
    service_touched = False
    current_created = False
    marker_created = False
    try:
        call("/usr/bin/install", "-d", "-o", "dealfonsocom", "-g", "psacln", "-m", "0711", str(CONTROL))
        dirs.append(CONTROL)
        for directory in (UNIT_DIR, LIBRARY):
            directory.mkdir(mode=0o755)
            directory.chmod(0o755)
            dirs.append(directory)
        observer = (
            '#!/bin/sh\nset -eu\n[ "$#" -eq 0 ] || exit 64\n'
            f'exec /usr/bin/python3 -I -B {LIBRARY / "structure.py"} {ROOT / "central"} {ROOT / "entidades"}\n'
        ).encode()
        policy = (
            f'dealfonsocom ALL=(root) NOPASSWD: {LAUNCHER}, {WRITERS} ""\n'
        ).encode()
        policy_test = archive / "sudoers.proposed"
        install_file(policy_test, policy, 0o440)
        call("/usr/sbin/visudo", "-cf", str(policy_test))
        for path, data, mode in (
            (SELECTOR, (sources / "production_serve.py").read_bytes(), 0o644),
            (Path(LAUNCHER), (sources / "production_launcher.sh").read_bytes(), 0o755),
            (Path(WRITERS), observer, 0o755),
            (LIBRARY / "structure.py", (sources.parent / "structure.py").read_bytes(), 0o644),
            (SUDOERS, policy, 0o440),
        ):
            install_file(path, data, mode)
            files.append(path)
        call("/usr/sbin/visudo", "-c")
        call("/usr/sbin/runuser", "-u", "dealfonsocom", "--", "/usr/bin/ln", "-sT", runtime.name, str(CURRENT))
        current_created = True
        call("/usr/sbin/runuser", "-u", "dealfonsocom", "--", "/usr/bin/sudo", "-n", LAUNCHER, "--help")

        nginx_changed = True
        NGINX.write_bytes(updated)
        call("/usr/sbin/nginx", "-t")
        call("/usr/bin/systemctl", "reload", "nginx")
        call("/usr/sbin/runuser", "-u", "dealfonsocom", "--", "/usr/bin/install", "-m", "0644", "/dev/null", str(MARKER))
        marker_created = True
        wait_health(PUBLIC, "503")
        wait_health(STAGING, "401")

        service_touched = True
        call("/usr/bin/systemctl", "stop", UNIT)
        for source in historical_files():
            target = archive / "historico" / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            moved.append((source, target))
        install_file(DROPIN, unit_definition(), 0o644)
        files.append(DROPIN)
        call("/usr/bin/systemd-analyze", "verify", UNIT)
        call("/usr/bin/systemctl", "daemon-reload")
        call("/usr/bin/systemctl", "start", UNIT)
        wait_health(PRIVATE, "200")
        call("/usr/bin/python3", "-B", "-m", "deployment.arsys.inspect_production_isolation", "active")
        writers = call("/usr/sbin/runuser", "-u", "dealfonsocom", "--", "/usr/bin/sudo", "-n", WRITERS, capture=True)
        if json.loads(writers.stdout).get("complete") is not True:
            raise ValueError("El observador de PRODUCCIÓN no tiene visibilidad completa")
        MARKER.unlink()
        marker_created = False
        wait_health(PUBLIC, "200")
        wait_health(STAGING, "401")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}. Revirtiendo la infraestructura de PRODUCCIÓN.", file=sys.stderr)
        if service_touched:
            call("/usr/bin/systemctl", "stop", UNIT)
        for source, target in reversed(moved):
            if source.exists() or source.is_symlink():
                raise ValueError(f"No se puede reponer sin sobrescribir: {source}")
            target.rename(source)
        for path in reversed(files):
            path.unlink()
        if current_created:
            CURRENT.unlink()
        if service_touched:
            call("/usr/bin/systemctl", "daemon-reload")
            call("/usr/bin/systemctl", "start", UNIT)
            wait_health(PRIVATE, "200")
        if nginx_changed:
            NGINX.write_bytes(original)
            call("/usr/sbin/nginx", "-t")
            call("/usr/bin/systemctl", "reload", "nginx")
        if marker_created:
            MARKER.unlink()
        for directory in reversed(dirs):
            directory.rmdir()
        print(f"Configuración anterior restaurada. Copia de Nginx: {archive}")
        raise SystemExit(1) from None
    print(f"OK: infraestructura de PRODUCCIÓN operativa; archivos históricos conservados: {len(moved)} en {archive}")


if __name__ == "__main__":
    main()
