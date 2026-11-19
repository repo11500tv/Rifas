/usr/bin/python3 -I -B -c 'import json
import os
from pathlib import Path
import re
import stat
import subprocess

HOST = Path("/var/www/vhosts/dealfonso.com")
PROD = HOST / "rifas"
STAGE = PROD / "staging/prueba_231"
LEGACY = HOST / "sorteos"
ROOTS = {"staging": STAGE, "production": PROD, "legacy": LEGACY}
PORTS = {8766, 8767, 8768}
UNITS = {"staging": "rifas-pruebas.service", "production": "rifas-platform.service"}
COMPONENTS = ("central", "entidades", "platform_app", "wsgi.py", "ops-reviewed", ".rifas-deploy")
VHOST = Path("/var/www/vhosts/system/dealfonso.com/conf")
LIMIT = 512 * 1024
MAX_PROCESSES = 4096
MAX_FDS = 512
MAX_TOTAL_FDS = 16000
MAX_ENTITIES = 512
warnings = set()


def report(section, **fields):
    print(json.dumps({"section": section, **fields}, ensure_ascii=True, sort_keys=True))


def command(*argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                                timeout=8, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        if result.returncode != 0 or len(result.stdout) > LIMIT:
            return None
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def label(path):
    for key, root in ROOTS.items():   # staging se comprueba antes de su raíz padre.
        if path.is_relative_to(root):
            return key
    return "outside"


def file_info(path, expected):
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
        real = resolved.stat()
        return {"present": True, "kind": "directory" if stat.S_ISDIR(real.st_mode) else "file"
                if stat.S_ISREG(real.st_mode) else "other", "bytes": real.st_size,
                "uid": real.st_uid, "gid": real.st_gid, "mode": oct(stat.S_IMODE(real.st_mode)),
                "device": real.st_dev, "inode": real.st_ino, "links": real.st_nlink,
                "mount": path.is_mount(), "symlink": stat.S_ISLNK(info.st_mode),
                "resolved_scope": label(resolved), "within_expected": label(resolved) == expected}
    except FileNotFoundError:
        return {"present": False}
    except (OSError, RuntimeError):
        return {"present": None}


def systemd():
    records = {}
    keys = ("ActiveState", "SubState", "MainPID", "User", "Group", "WorkingDirectory",
            "ControlGroup", "KillMode", "TimeoutStopUSec", "ProtectSystem", "NoNewPrivileges",
            "RootDirectory", "RootImage", "ReadWritePaths", "InaccessiblePaths", "BindPaths",
            "FragmentPath", "DropInPaths", "ExecStart")
    for env, unit in UNITS.items():
        result = command("/usr/bin/systemctl", "--no-pager", "show",
                         *[f"--property={key}" for key in keys], unit)
        if result is None:
            warnings.add("systemd_unavailable")
            report("service", env=env, unit=unit, observed=False)
            continue
        properties = dict(line.split("=", 1) for line in result.splitlines() if "=" in line)
        records[env] = properties
        states = {"active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance"}
        state = properties.get("ActiveState")
        bind = sorted({int(port) for port in re.findall(r":([0-9]{2,5})\b", properties.get("ExecStart", ""))
                       if int(port) in PORTS})
        report("service", env=env, unit=unit, observed=True,
               active=state if state in states else "unknown",
               pid=int(properties.get("MainPID", "0")) if properties.get("MainPID", "").isdigit() else None,
               working_directory=label(Path(properties["WorkingDirectory"]).resolve())
               if properties.get("WorkingDirectory") else "unset",
               bind_port_hints=bind, wsgi_app_hint=bool(re.search(r"\bwsgi:app\b", properties.get("ExecStart", ""))),
               kill_control_group=properties.get("KillMode") == "control-group",
               protect_system_strict=properties.get("ProtectSystem") == "strict",
               no_new_privileges=properties.get("NoNewPrivileges") == "yes",
               confinement_fields_present=[key for key in ("RootDirectory", "RootImage", "ReadWritePaths",
                                                           "InaccessiblePaths", "BindPaths") if properties.get(key)],
               dropins_present=bool(properties.get("DropInPaths")))
    if len(records) == 2:
        left, right = records["staging"], records["production"]
        report("shared_identity", same_user=left.get("User") == right.get("User"),
               same_group=left.get("Group") == right.get("Group"),
               staging_user_declared=bool(left.get("User")), production_user_declared=bool(right.get("User")))
    return records


def socket_map(services):
    result = command("/usr/bin/ss", "-lntp", "-H")
    owners = {}
    if result is None:
        warnings.add("tcp_listeners_unavailable")
        return owners
    known_pids = {int(item["MainPID"]) for item in services.values()
                  if item.get("MainPID", "").isdigit() and item["MainPID"] != "0"}
    for line in result.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        host, sep, port = parts[3].rpartition(":")
        if not sep or not port.isdigit():
            continue
        pids = [int(pid) for pid in re.findall(r"\bpid=(\d+)", line)]
        relevant = bool(known_pids.intersection(pids))
        for pid in pids:
            try:
                relevant |= label(Path(os.readlink(f"/proc/{pid}/cwd"))) in ROOTS
            except OSError:
                pass
        if int(port) not in PORTS and not relevant:
            continue
        owners.setdefault(int(port), set()).update(pids)
        report("listener", port=int(port), loopback=host.strip("[]") in {"127.0.0.1", "::1"}, pids=pids)
        if not pids:
            warnings.add("listener_pid_visibility_incomplete")
    if command("/usr/bin/ss", "-lxnp", "-H") is None:
        warnings.add("unix_listeners_unavailable")
    else:
        warnings.add("unix_socket_routes_require_effective_config_review")
    return owners


def processes(services, owners, database_paths):
    inspected = 0
    denied = 0
    capped = 0
    total_fds = 0
    listener_pids = set().union(*owners.values()) if owners else set()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        if inspected == MAX_PROCESSES:
            warnings.add("process_scan_limit")
            break
        inspected += 1
        pid = int(proc.name)
        try:
            cgroup = (proc / "cgroup").read_text(errors="replace")
        except OSError:
            cgroup = ""
        try:
            cwd = label(Path(os.readlink(proc / "cwd")))
        except OSError:
            cwd = "unknown"
        units = [env for env, data in services.items() if data.get("ControlGroup")
                 and any(line.split(":", 2)[-1] == data["ControlGroup"]
                         or line.split(":", 2)[-1].startswith(data["ControlGroup"] + "/")
                         for line in cgroup.splitlines())]
        writers = {}
        databases = set()
        try:
            for index, fd in enumerate((proc / "fd").iterdir()):
                if total_fds >= MAX_TOTAL_FDS:
                    warnings.add("total_fd_scan_limit")
                    break
                total_fds += 1
                if index == MAX_FDS:
                    capped += 1
                    break
                try:
                    target = os.readlink(fd).removesuffix(" (deleted)")
                    scope = label(Path(target))
                    if target in database_paths:
                        databases.add(database_paths[target])
                    if scope == "outside":
                        continue
                    flags = re.search(r"(?m)^flags:\s*([0-7]+)$", (proc / "fdinfo" / fd.name).read_text())
                    if flags and int(flags[1], 8) & os.O_ACCMODE in (os.O_WRONLY, os.O_RDWR):
                        writers[scope] = writers.get(scope, 0) + 1
                except (OSError, ValueError):
                    continue
        except PermissionError:
            denied += 1
        except OSError:
            pass
        if pid in listener_pids or cwd in ROOTS or units or writers or databases:
            report("process", pid=pid, cwd_scope=cwd, unit_scopes=units, writable_fds=writers,
                   ports=sorted(port for port, pids in owners.items() if pid in pids), databases=sorted(databases))
    report("visibility", processes_inspected=inspected, fd_directories_denied=denied, fd_lists_capped=capped, descriptors_inspected=total_fds)
    warnings.add("writers_snapshot_cannot_exclude_future_writers_or_alternate_mounts")


def files():
    database_paths = {}
    for env, root in ROOTS.items():
        report("root", env=env, **file_info(root, env))
        if env == "legacy":
            continue
        for name in COMPONENTS:
            report("component", env=env, component=name, **file_info(root / name, env))
        relative_databases = [("central", root / "central/plataforma.sqlite"),
                              ("template", root / "central/plantillas/entidad_maestra.sqlite3")]
        try:
            entities = (root / "entidades")
            if entities.resolve() != entities:
                raise OSError("alias")
            for index, entity in enumerate(entities.iterdir()):
                if index == MAX_ENTITIES:
                    warnings.add("entity_scan_limit")
                    break
                if entity.is_dir():
                    relative_databases.append((f"entity-{index + 1}", entity / "data/rifas.sqlite3"))
        except OSError:
            warnings.add(f"{env}_entity_listing_unavailable")
        for role, database in relative_databases:
            auxiliaries = {suffix: file_info(Path(str(database) + suffix), env)["present"]
                           for suffix in ("-wal", "-shm", "-journal")}
            info = file_info(database, env)
            report("database_file", env=env, role=role, sidecars=auxiliaries, **info)
            if info.get("present") and info.get("within_expected"):
                database_paths[str(database)] = f"{env}/{role}"
    return database_paths


def proxy_config():
    # Se examinan referencias acotadas de Plesk. La asociación es textual,
    # no un volcado efectivo ni un análisis de precedencia de Nginx.
    for name in ("nginx.conf", "last_nginx.conf", "vhost_nginx.conf"):
        path = VHOST / name
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(VHOST) or not resolved.is_file() or resolved.stat().st_size > LIMIT:
                warnings.add("nginx_file_outside_scope_or_limit")
                continue
            with resolved.open(errors="replace") as configuration:
                text = configuration.read(LIMIT + 1)
            if len(text) > LIMIT:
                warnings.add("nginx_file_outside_scope_or_limit")
                continue
        except FileNotFoundError:
            continue
        except OSError:
            warnings.add("nginx_config_access_incomplete")
            continue
        text = re.sub(r"(?m)^\s*#.*$", "", text)
        report("proxy_file", file=name, include_count=len(re.findall(r"\binclude\s+", text)),
               maintenance_hint=bool(re.search(r"\breturn\s+503\s*;", text)),
               marker_hint=bool(re.search(r"\bif\s*\(\s*-f\b", text)),
               cache_directives=bool(re.search(r"\bproxy_cache\b", text)),
               forwarded_headers=sorted(set(re.findall(
                   r"(?i)\bproxy_set_header\s+(X-Forwarded-(?:For|Host|Proto|Prefix)|Host)\b", text))),
               cookie_directives=bool(re.search(r"\bproxy_cookie_(?:path|domain|flags)\b", text)))
        routes = re.compile(r"(?m)^\s*location\s+(?:(?:=|\^~)\s+)?(/(?:rifas(?:/staging/prueba_231)?|sorteos)/?)\s*\{")
        for match in routes.finditer(text):
            # Solo cuerpo plano hasta el siguiente bloque; si es complejo se
            # muestra como incompleto en vez de asignar otra ruta por error.
            body = re.split(r"[{}]", text[match.end():], maxsplit=1)[0]
            ports = sorted({int(p) for p in re.findall(
                r"\bproxy_pass\s+https?://(?:127\.0\.0\.1|localhost|\[::1\]):(\d+)\b", body)
                if int(p) in PORTS})
            report("proxy_route_hint", file=name, route=match[1], loopback_ports=ports)
    warnings.add("effective_nginx_includes_aliases_and_bypasses_unverified")


def backup_and_jobs():
    listed = command("/usr/bin/systemctl", "--no-pager", "--no-legend", "list-timers", "--all")
    report("writers_and_backup", timers_visible=listed is not None,
           timers_matching_project=sum(bool(re.search(r"(?i)\b(rifas|sorteos)", line))
                                       for line in (listed or "").splitlines()),
           backup_timer_hints=sum(bool(re.search(r"(?i)backup|pmm", line))
                                  for line in (listed or "").splitlines()),
           cron_directories_present=all(Path(p).is_dir() for p in ("/etc/cron.d", "/etc/cron.daily")),
           plesk_backup_directory_present=Path("/var/lib/psa/dumps").is_dir(),
           coordinator_local_coverage=["central", "entidades", "previous_code", "ops-reviewed_if_configured"],
           external_destination_verified=False, recovery_proven=False)
    warnings.add("cron_plesk_and_external_writers_not_ruled_out")
    warnings.add("external_backup_scope_acl_and_restore_unverified")


if __name__ == "__main__":
    report("inspection", mode="read-only", sqlite_opened=False, services_modified=False)
    services = systemd()
    owners = socket_map(services)
    databases = files()
    processes(services, owners, databases)
    proxy_config()
    backup_and_jobs()
    report("limits", pending=sorted(warnings | {"sqlite_schema_catalog_and_runtime_configuration_unverified"}))
'
