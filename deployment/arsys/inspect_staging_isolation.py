"""Read-only inspection of the running Gunicorn process on Arsys staging."""

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


def listener_processes(listeners, expected_group, expected_uid):
    if not listeners or any(host not in {"127.0.0.1", "::1"} or not pids for host, pids in listeners):
        raise ValueError("El puerto de PRUEBAS no es privado o sus procesos no son visibles")
    rows = {}
    for pid in sorted({pid for _, pids in listeners for pid in pids}):
        proc = Path("/proc") / str(pid)
        fields = dict(line.split(":", 1) for line in (proc / "status").read_text().splitlines() if ":" in line)
        uids = fields["Uid"].split()
        namespace = fields["NSpid"].split()
        if (process_group(proc) != expected_group or not expected_group
                or (proc / "comm").read_text().strip() != "gunicorn"
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


def inspect():
    expected_uid = pwd.getpwnam("dealfonsocom").pw_uid
    if os.geteuid() not in {0, expected_uid}:
        raise ValueError("Ejecutar la consulta como dealfonsocom o el administrador del servidor")
    observed = unit(UNIT)
    if (observed.get("ActiveState") != "active" or observed.get("ProtectSystem") != "strict"
            or observed.get("NoNewPrivileges") != "yes" or observed.get("KillMode") != "control-group"
            or observed.get("WorkingDirectory") != str(STAGE)):
        raise ValueError("La unidad activa no coincide con el aislamiento esperado")
    launcher = observed.get("MainPID", "")
    if not re.fullmatch(r"[1-9][0-9]*", launcher):
        raise ValueError("No se pudo identificar el lanzador de PRUEBAS")
    listener = Structure({"port": 8768, "writer_observer": ["/usr/bin/false"]}, STAGE,
                         STAGE / ".rifas-deploy", PROTECTED, [], {}).listeners()
    processes = listener_processes(listener, observed["ControlGroup"], expected_uid)
    master = next(pid for pid, inner_pid in processes.items() if inner_pid == 1)
    if master == int(launcher) or any(pid == int(launcher) for pid in processes):
        raise ValueError("El lanzador y el proceso web deben ser distintos")
    modes = {str(path): mount_mode(master, path) for path in (*PROTECTED, STAGE)}
    if modes[str(STAGE)] != "rw" or any(modes[str(path)] != "ro" for path in PROTECTED):
        raise ValueError("PRUEBAS no tiene los permisos de montaje esperados")
    return {"environment": "staging", "unit": UNIT, "gunicorn_uid": expected_uid,
            "listener_processes": len(processes), "mounts": modes}


if __name__ == "__main__":
    print(json.dumps(inspect(), sort_keys=True))
