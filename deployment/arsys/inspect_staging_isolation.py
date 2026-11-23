"""Read-only inspection of the running Gunicorn process on Arsys staging."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re

from deployment.arsys.staging_google_checks import STAGE
from deployment.structure import Structure, command, process_group, unit


UNIT = "rifas-pruebas.service"
DOMAIN = Path("/var/www/vhosts/dealfonso.com")
PROTECTED = (
    DOMAIN / "rifas",
    DOMAIN / "rifas/central",
    DOMAIN / "rifas/entidades",
    DOMAIN / "rifas-deployment/production",
    DOMAIN / "rifas-deployment/staging/checkout",
    STAGE / ".rifas-deploy",
    Path("/var/lib/rifas-pruebas-control"),
)


def gunicorn_process(proc):
    name = (proc / "comm").read_text().strip()
    if name == "gunicorn":
        return True
    if not re.fullmatch(r"python(?:3(?:\.12)?)?", name):
        return False
    args = (proc / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
    runtime = DOMAIN / "rifas-deployment/staging/runtime/current/bin/python"
    return (
        len(args) >= 5
        and Path(os.fsdecode(args[0])).resolve() == runtime.resolve(strict=True)
        and args[1:4] == [b"-B", b"-m", b"gunicorn"]
        and args[-1] == b"wsgi:app"
    )


def listener_processes(listeners, expected_group, expected_uid, process_matches=gunicorn_process):
    if not listeners or any(host not in {"127.0.0.1", "::1"} or not pids for host, pids in listeners):
        raise ValueError("El puerto de PRUEBAS no es privado o sus procesos no son visibles")
    rows = {}
    for pid in sorted({pid for _, pids in listeners for pid in pids}):
        proc = Path("/proc") / str(pid)
        fields = dict(line.split(":", 1) for line in (proc / "status").read_text().splitlines() if ":" in line)
        uids = fields["Uid"].split()
        namespace = fields["NSpid"].split()
        if (process_group(proc) != expected_group or not expected_group
                or not process_matches(proc)
                or any(int(uid) != expected_uid for uid in uids)
                or len(namespace) < 2 or int(namespace[0]) != pid
                or fields["NoNewPrivs"].strip() != "1" or int(fields["CapEff"], 16)):
            raise ValueError("El proceso que escucha no coincide con el Gunicorn aislado de PRUEBAS")
        rows[pid] = int(namespace[-1])
    if sum(value == 1 for value in rows.values()) != 1:
        raise ValueError("No se pudo identificar el Gunicorn principal de PRUEBAS")
    return rows


def mount_mode(pid, path):
    if not path.is_dir() or path.resolve() != path:
        raise ValueError(f"Ruta ausente o no canónica: {path}")
    flags = command("/usr/bin/findmnt", "--task", str(pid), "--target", str(path),
                    "--noheadings", "--output", "VFS-OPTIONS").strip().split(",")
    if ("ro" in flags) == ("rw" in flags):
        raise ValueError(f"Modo de montaje indeterminado: {path}")
    return "ro" if "ro" in flags else "rw"


def inspect(action="active"):
    expected_uid = pwd.getpwnam("dealfonsocom").pw_uid
    if os.geteuid() not in {0, expected_uid}:
        raise ValueError("Ejecutar la consulta como dealfonsocom o el administrador del servidor")
    observed = unit(UNIT)
    if (observed.get("ProtectSystem") != "strict"
            or observed.get("NoNewPrivileges") != "yes" or observed.get("KillMode") != "control-group"
            or observed.get("WorkingDirectory") != str(STAGE)):
        raise ValueError("La unidad no coincide con el aislamiento esperado")
    if action == "policy":
        if command("/usr/bin/systemctl", "show", UNIT, "-p", "NeedDaemonReload", "--value").strip() != "no":
            raise ValueError("La política de PRUEBAS tiene cambios de systemd sin cargar")
        peer = unit("rifas-platform.service")
        policies = []
        for service in (observed, peer):
            files = [service["FragmentPath"], *service["DropInPaths"].split()]
            hashes = {file: managed_file_digest(file) for file in files}
            static = {key: value for key, value in service.items()
                      if key not in {"ActiveState", "MainPID", "ControlGroup", "ExecStart"}}
            policies.append({"settings": static, "files": hashes})
        helpers = {path: managed_file_digest(path) for path in (
            "/usr/local/sbin/rifas-pruebas-deploy", "/usr/local/sbin/rifas-pruebas-serve",
            "/usr/local/sbin/rifas-staging-service", "/usr/local/sbin/rifas-pruebas-observe-writers",
            "/usr/local/lib/rifas-pruebas/structure.py",
        )}
        payload = json.dumps({"unit_policies": policies, "helpers": helpers}, sort_keys=True).encode()
        return {"environment": "staging", "unit": UNIT, "policy": hashlib.sha256(payload).hexdigest()}
    listener = Structure({"port": 8768, "writer_observer": ["/usr/bin/false"]}, STAGE,
                         STAGE / ".rifas-deploy", PROTECTED, [], {}).listeners()
    if action == "stopped":
        if observed.get("ActiveState") != "inactive" or observed.get("MainPID") != "0" or listener:
            raise ValueError("La unidad o el puerto de PRUEBAS siguen activos tras el drenaje")
        return {"environment": "staging", "unit": UNIT, "stopped": True}
    if observed.get("ActiveState") != "active":
        raise ValueError("La unidad de PRUEBAS no está activa")
    launcher = observed.get("MainPID", "")
    if not re.fullmatch(r"[1-9][0-9]*", launcher):
        raise ValueError("No se pudo identificar el lanzador de PRUEBAS")
    processes = listener_processes(listener, observed["ControlGroup"], expected_uid)
    master = next(pid for pid, inner_pid in processes.items() if inner_pid == 1)
    if master == int(launcher) or any(pid == int(launcher) for pid in processes):
        raise ValueError("El lanzador y el proceso web deben ser distintos")
    modes = {str(path): mount_mode(master, path) for path in (*PROTECTED, STAGE)}
    if modes[str(STAGE)] != "rw" or any(modes[str(path)] != "ro" for path in PROTECTED):
        raise ValueError("PRUEBAS no tiene los permisos de montaje esperados")
    return {"environment": "staging", "unit": UNIT, "gunicorn_uid": expected_uid,
            "listener_processes": len(processes), "mounts": modes, "group": observed["ControlGroup"]}


def managed_file_digest(name):
    path = Path(name)
    metadata = path.stat()
    if (not path.is_absolute() or not path.is_file() or path.resolve() != path
            or metadata.st_uid != 0 or metadata.st_mode & 0o022):
        raise ValueError(f"Archivo de infraestructura inválido: {name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="active", choices=("active", "stopped", "policy"))
    print(json.dumps(inspect(parser.parse_args().action), sort_keys=True))
