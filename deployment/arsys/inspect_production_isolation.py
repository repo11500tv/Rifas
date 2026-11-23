"""Read-only reports for the isolated production coordinator."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re

from deployment.arsys.inspect_staging_isolation import listener_processes, managed_file_digest, mount_mode
from deployment.arsys.production_serve import COORDINATOR, ROOT
from deployment.arsys.production_structure import ArsysProductionStructure, PEER, UNIT
from deployment.arsys.production_service_bridge import LAUNCHER, SERVICE, WRITERS
from deployment.structure import Structure, command, unit


def gunicorn_process(proc):
    name = (proc / "comm").read_text().strip()
    if name == "gunicorn":
        return True
    if not re.fullmatch(r"python(?:3(?:\.12)?)?", name):
        return False
    args = (proc / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
    runtime = COORDINATOR / "runtime/current/bin/python"
    return (len(args) >= 5 and Path(os.fsdecode(args[0])).resolve() == runtime.resolve(strict=True)
            and args[1:4] == [b"-B", b"-m", b"gunicorn"] and args[-1] == b"wsgi:app")


def unit_policy(observed):
    policies = []
    for service in (observed, unit(PEER)):
        files = [service["FragmentPath"], *service["DropInPaths"].split()]
        static = {key: value for key, value in service.items()
                  if key not in {"ActiveState", "MainPID", "ControlGroup", "ExecStart"}}
        policies.append({"settings": static, "files": {file: managed_file_digest(file) for file in files}})
    helpers = (LAUNCHER, SERVICE, WRITERS, "/usr/local/sbin/rifas-produccion-serve",
               "/usr/local/lib/rifas-produccion/structure.py")
    payload = {"units": policies, "helpers": {file: managed_file_digest(file) for file in helpers}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def inspect(action):
    uid = pwd.getpwnam("dealfonsocom").pw_uid
    if os.geteuid() not in {0, uid}:
        raise ValueError("La consulta requiere la cuenta del dominio o el administrador del servidor")
    observed = unit(UNIT)
    if (observed.get("ProtectSystem") != "strict" or observed.get("NoNewPrivileges") != "yes"
            or observed.get("KillMode") != "control-group" or observed.get("WorkingDirectory") != str(ROOT)):
        raise ValueError("Aislamiento de systemd de PRODUCCIÓN insuficiente")
    report = {"environment": "production", "unit": UNIT}
    if action == "policy":
        if command("/usr/bin/systemctl", "show", UNIT, "-p", "NeedDaemonReload", "--value").strip() != "no":
            raise ValueError("La unidad de PRODUCCIÓN tiene cambios sin cargar")
        return dict(report, policy=unit_policy(observed))

    listeners = Structure({"port": 8767, "writer_observer": ["/usr/bin/false"]}, ROOT,
                          ROOT / ".rifas-deploy", (), [], {}).listeners()
    if action == "stopped":
        if observed.get("ActiveState") != "inactive" or observed.get("MainPID") != "0" or listeners:
            raise ValueError("El servicio o el puerto de PRODUCCIÓN sigue activo")
        return dict(report, stopped=True)

    launcher = observed.get("MainPID", "")
    if observed.get("ActiveState") != "active" or not re.fullmatch(r"[1-9][0-9]*", launcher):
        raise ValueError("No se pudo confirmar el lanzador activo de PRODUCCIÓN")
    group = observed["ControlGroup"]
    processes = listener_processes(listeners, group, uid, gunicorn_process)
    if int(launcher) in processes:
        raise ValueError("Gunicorn y el lanzador de PRODUCCIÓN no están separados")
    master = next(pid for pid, inner in processes.items() if inner == 1)
    writable = ArsysProductionStructure.service_writable
    readonly = ArsysProductionStructure.service_read_only
    mounts = {str(path): mount_mode(master, path) for path in (*readonly, *writable)}
    if mounts != {**{str(path): "ro" for path in readonly}, **{str(path): "rw" for path in writable}}:
        raise ValueError("Montajes de Gunicorn de PRODUCCIÓN inesperados")
    return dict(report, gunicorn_uid=uid, group=group, mounts=mounts, listener_processes=len(processes))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("active", "stopped", "policy"))
    print(json.dumps(inspect(parser.parse_args().action), sort_keys=True))
