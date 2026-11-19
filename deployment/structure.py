"""Evidencia estructural y comprobaciones operativas Linux/systemd."""

import argparse
import hashlib
import json
import os
import pwd
from pathlib import Path
import re
import stat
import subprocess

PROPERTIES = (
    "Id", "User", "Group", "WorkingDirectory", "ProtectSystem",
    "NoNewPrivileges", "KillMode", "ReadWritePaths", "InaccessiblePaths",
    "BindPaths", "BindReadOnlyPaths", "PrivateMounts", "FragmentPath", "DropInPaths",
    "ExecStart", "Environment", "EnvironmentFiles", "RootDirectory", "RootImage",
)
SYSTEMCTL = "/usr/bin/systemctl"
SS = "/usr/bin/ss"


def command(*args):
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=12).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"No se pudo completar la consulta de {Path(args[0]).name}") from error


def unit(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.service", name):
        raise ValueError("Unidad estructural inválida")
    result = command(SYSTEMCTL, "--no-pager", "show",
                     "--property=" + ",".join((*PROPERTIES, "ActiveState", "MainPID", "ControlGroup")), name)
    values = dict(line.split("=", 1) for line in result.splitlines() if "=" in line)
    if values.get("Id") != name:
        raise ValueError("La unidad observada no coincide con el perfil")
    return values


def excludes(path, protected):
    return any(path.is_relative_to(other) for other in protected)


def metadata(path):
    info = path.stat()
    return [info.st_dev, info.st_ino, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid]


def checked_path(name):
    path = Path(name)
    if not path.is_absolute() or path.resolve() != path or path.is_relative_to("/root"):
        raise ValueError("Ruta estructural no canónica")
    return path


def access_attributes(path):
    attributes = {}
    for name in ("system.posix_acl_access", "system.posix_acl_default"):
        if name in os.listxattr(path):
            attributes[name] = hashlib.sha256(os.getxattr(path, name)).hexdigest()
    return attributes


def process_group(process):
    return next((line[3:] for line in (process / "cgroup").read_text().splitlines()
                 if line.startswith("0::")), "")


def listener_identity(master, observed, pids):
    try:
        expected = pwd.getpwnam(observed["User"]).pw_uid
        status = (Path("/proc") / str(master) / "status").read_text()
        uid = re.search(r"(?m)^Uid:\s+(\d+)\s+(\d+)", status)
        return bool(uid and int(uid[2]) == expected and observed["ControlGroup"] and all(
            process_group(Path("/proc") / str(pid)) == observed["ControlGroup"] for pid in pids
        ))
    except (KeyError, OSError):
        return False


def mounts(paths):
    relevant = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields, _, filesystem = line.partition(" - ")
        parts = fields.split()
        if len(parts) < 6 or not filesystem:
            continue
        target = Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), parts[4]))
        if any(path.is_relative_to(target) or target.is_relative_to(path) for path in paths):
            relevant.append([*parts[2:], filesystem])
    return sorted(relevant)


class Structure:
    def __init__(self, settings, root, state, protected, components, profile, control_root=None):
        self.settings = settings
        self.control_root = control_root
        self.profile = profile
        self.root = root
        self.state = state
        self.protected = tuple(protected)
        self.writable = {root / name for name in ("central", "entidades", *components)}
        self.port = settings["port"]
        if not isinstance(self.port, int) or not 0 < self.port < 65536:
            raise ValueError("Puerto estructural inválido")
        self.observer = settings["writer_observer"]
        if (not isinstance(self.observer, list) or not self.observer
                or not all(isinstance(arg, str) for arg in self.observer)
                or not Path(self.observer[0]).is_absolute()):
            raise ValueError("El observador de escritores requiere un argv absoluto")

    def evidence(self, *, review=False):
        active = unit(self.settings["unit"])
        peer = unit(self.settings["peer_unit"])
        checks = {
            "identidades_separadas": bool(active.get("User")) and active["User"] not in ("root", "0")
            and bool(peer.get("User")) and active["User"] != peer["User"],
            "cuenta_operativa_no_privilegiada": os.geteuid() != 0,
            "confinamiento_systemd": active.get("ProtectSystem") == "strict"
            and active.get("NoNewPrivileges") == "yes" and active.get("KillMode") == "control-group",
            "sin_remontajes_privados_no_revisados": not any(
                active.get(key) for key in ("BindPaths", "BindReadOnlyPaths", "RootDirectory", "RootImage")
            ),
        }
        checks["directorio_de_unidad_correcto"] = active.get("WorkingDirectory") == self.settings["working_directory"]
        writes = {checked_path(item.lstrip("-")) for item in active.get("ReadWritePaths", "").split()}
        hidden = {checked_path(item.lstrip("-")) for item in active.get("InaccessiblePaths", "").split()}
        checks["escrituras_limitadas"] = bool(writes) and all(
            path in self.writable | {self.state, self.control_root} for path in writes
        )
        checks["ambitos_ajenos_ocultos"] = bool(self.protected) and all(
            excludes(path, hidden) for path in self.protected
        )
        checks["operador_sin_escritura_ajena_visible"] = all(
            not os.access(path, os.W_OK, effective_ids=True)
            and not os.access(path.parent, os.W_OK, effective_ids=True)
            for path in self.protected
        )
        paths = [self.root, self.state, *self.writable, *self.protected]
        if self.control_root is not None:
            paths.append(self.control_root)
        review_files = [*self.settings["review_files"]]
        review_files.extend(self.profile[key] for key in ("allowed_signers", "approval_signers", "intervention_signers") if key in self.profile)
        for item in review_files:
            path = checked_path(item)
            paths.append(path)
            if path.is_dir():
                for count, child in enumerate(path.rglob("*"), start=1):
                    if count > 512:
                        raise ValueError("Limitar el directorio estructural a sus includes efectivos")
                    child = checked_path(child)
                    if not (child.is_file() or child.is_dir()):
                        raise ValueError("Entrada estructural no regular")
                    paths.append(child)
        for observed in (active, peer):
            for item in [observed.get("FragmentPath"), *observed.get("DropInPaths", "").split()]:
                if item:
                    paths.append(checked_path(item))
        records = {}
        for path in sorted(set(paths)):
            if path.resolve() != path:
                raise ValueError(f"Ruta estructural no canónica: {path}")
            if not path.exists():
                records[str(path)] = None
                if path in self.writable or path in (self.root, self.state, self.control_root):
                    checks["raices_operativas_presentes"] = False
                if str(path) in review_files:
                    checks["archivos_de_revision_presentes"] = False
                continue
            content = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            records[str(path)] = [metadata(path), access_attributes(path), content]
        payload = {
            "profile": self.profile, "uid": os.geteuid(), "gid": os.getegid(), "groups": sorted(os.getgroups()),
            "units": [{name: value for name, value in item.items() if name in PROPERTIES}
                      for item in (active, peer)],
            "paths": records, "mounts": mounts(paths), "checks": checks,
        }
        # Los valores efectivos de systemd (incluido Environment) quedan dentro
        # del resumen. No se imprimen ni se guardan en el registro.
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if not review:
            if not all(checks.values()):
                failed = ", ".join(name for name, ok in checks.items() if not ok)
                raise ValueError(f"Aislamiento estructural insuficiente: {failed}")
            if fingerprint != self.settings.get("expected_fingerprint"):
                raise ValueError("Cambió la evidencia estructural o falta aprobarla")
        return {"digest": fingerprint, "checks": checks}

    def listeners(self):
        result = command(SS, "-H", "-lntp", f"sport = :{self.port}")
        listeners = []
        for line in result.splitlines():
            items = line.split()
            if len(items) < 5:
                raise ValueError("No se pudo interpretar el listener")
            host, sep, number = items[3].rpartition(":")
            if not sep or number != str(self.port):
                raise ValueError("La consulta de listeners devolvió un puerto inesperado")
            listeners.append((host.strip("[]"), {int(pid) for pid in re.findall(r"\bpid=(\d+)", line)}))
        return listeners

    def service(self, *, stopped=False):
        observed = unit(self.settings["unit"])
        listeners = self.listeners()
        if stopped:
            if observed.get("ActiveState") != "inactive" or observed.get("MainPID") != "0" or listeners:
                raise ValueError("La unidad o su puerto siguen activos tras el drenaje")
            return
        master = observed.get("MainPID", "")
        if (observed.get("ActiveState") != "active" or not master.isdecimal()
                or not listeners or any(host not in {"127.0.0.1", "::1"} or int(master) not in pids
                                       for host, pids in listeners)):
            raise ValueError("Listener privado no atribuible a la unidad esperada")
        if not listener_identity(int(master), observed, set().union(*(pids for _, pids in listeners))):
            raise ValueError("Identidad o cgroup del listener distintos de la unidad")

    def writers(self, *, drained=False):
        try:
            report = json.loads(command(*self.observer))
            if report["complete"] is not True or report["paths"] != sorted(map(str, self.writable)):
                raise ValueError("Visibilidad incompleta de los escritores")
            rows = report["writers"]
            groups = set() if drained else {
                unit(self.settings["unit"]).get("ControlGroup"), *self.settings.get("writer_groups", [])
            }
            if any(not row["group"] or row["group"] not in groups for row in rows):
                raise ValueError("Se detectaron escritores no autorizados en el ámbito")
            return len(rows)
        except (KeyError, TypeError) as error:
            raise ValueError("Respuesta inválida del observador de escritores") from error


def observe(paths):
    writers = []
    complete = True
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            group = process_group(process)
            if not group:
                complete = False
            if any(len(parts) == 6 and parts[1][1] == "w" and parts[1][-1] == "s"
                   and excludes(Path(parts[5].removesuffix(" (deleted)")), paths)
                   for parts in (line.split(maxsplit=5) for line in (process / "maps").read_text().splitlines())):
                writers.append({"group": group})
                continue
            for fd in (process / "fd").iterdir():
                try:
                    target = Path(os.readlink(fd).removesuffix(" (deleted)"))
                    if not excludes(target, paths):
                        continue
                    flags = re.search(r"(?m)^flags:\s*([0-7]+)$", (process / "fdinfo" / fd.name).read_text())
                    if flags and (int(flags[1], 8) & os.O_ACCMODE) in (os.O_WRONLY, os.O_RDWR):
                        writers.append({"group": group})
                        break
                except FileNotFoundError:
                    continue
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (PermissionError, OSError):
            complete = False
    return {"paths": sorted(map(str, paths)), "writers": writers, "complete": complete}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    print(json.dumps(observe([checked_path(path) for path in args.paths])))


if __name__ == "__main__":
    main()
