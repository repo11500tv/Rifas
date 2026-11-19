/usr/bin/python3 -I -B -c 'import json
import os
from pathlib import Path
import re
import stat
import subprocess

STAGE = Path("/var/www/vhosts/dealfonso.com/rifas/staging/prueba_231")
PROD = STAGE.parents[1]
LEGACY = PROD.parent / "sorteos"
VHOST = Path("/var/www/vhosts/system/dealfonso.com/conf")
UNIT = "rifas-pruebas.service"
LIMIT = 512 * 1024
unresolved = set()


def emit(section, **fields):
    print(json.dumps({"section": section, **fields}, sort_keys=True))


def read_command(*argv):
    try:
        result = subprocess.run(argv, check=True, capture_output=True, text=True, errors="replace",
                                timeout=8, env={"PATH": "/usr/sbin:/usr/bin:/bin", "LC_ALL": "C"})
        return result.stdout if len(result.stdout) <= LIMIT else None
    except (OSError, subprocess.SubprocessError):
        return None


def proxy():
    # No se invocan pruebas de configuración que puedan abrir logs.
    names = ("nginx.conf", "last_nginx.conf", "vhost_nginx.conf",
             "httpd.conf", "last_httpd.conf", "vhost.conf", "vhost_ssl.conf")
    reviewed = 0
    for name in names:
        try:
            path = (VHOST / name).resolve(strict=True)
            if not path.is_relative_to(VHOST) or not path.is_file():
                unresolved.add("proxy_reference_outside_vhost")
                continue
            with path.open(errors="replace") as source:
                content = source.read(LIMIT + 1)
            if len(content) > LIMIT:
                unresolved.add("proxy_file_limit")
                continue
        except FileNotFoundError:
            continue
        except (OSError, RuntimeError):
            unresolved.add("proxy_visibility_incomplete")
            continue
        reviewed += 1
        # Conserva solo ubicación relativa de pistas y categorías fijas.
        # Nunca publica argumentos de ProxyPass, variables ni rutas arbitrarias.
        for number, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            categories = []
            if re.search(r"(?i)^(?:proxy_pass|ProxyPass(?:Match|Reverse)?|RewriteRule|SetHandler)\b", line):
                categories.append("forwarding")
            if re.search(r"(?i)^(?:include(?:optional)?|Alias(?:Match)?|Redirect(?:Match)?|location|<Location(?:Match)?)\b", line):
                categories.append("routing")
            if re.search(r"(?i)^(?:server_name|ServerName|ServerAlias)\b", line):
                categories.append("vhost")
            if re.search(r"\breturn\s+503\b|\bR=503\b|(?:\bmaintenance\b|\bErrorDocument\s+503\b)", line, re.I):
                categories.append("maintenance")
            if re.search(r"(?i)^(?:proxy_set_header|RequestHeader|proxy_cache|proxy_cookie_\w+)\b", line):
                categories.append("headers_cache_cookie")
            if categories:
                emit("proxy_hint", file=name, line=number, categories=categories,
                     staging_literal="/staging/prueba_231" in line,
                     backend_8768=bool(re.search(r":8768\b", line)),
                     backend_other_known=bool(re.search(r":(?:8766|8767)\b", line)),
                     variables_or_regex=bool(re.search(r"\$|~|\b(?:Match|RewriteRule)\b", line)))
    emit("proxy_coverage", reviewed_files=reviewed, plesk_generated_dir=VHOST.is_dir())
    unresolved.add("effective_order_wildcard_includes_external_routes_and_bypasses_need_review")


def direct_backend():
    output = read_command("/usr/bin/ss", "-H", "-lnt", "sport = :8768")
    if output is None:
        unresolved.add("direct_backend_visibility_incomplete")
        return
    addresses = [
        parts[3].rpartition(":")[0].strip("[]")
        for line in output.splitlines() if len(parts := line.split()) >= 5
    ]
    emit("direct_staging_backend", listeners=len(addresses),
         non_loopback=sum(address not in {"127.0.0.1", "::1"} for address in addresses))
    if not addresses:
        unresolved.add("staging_listener_not_visible_in_probe_namespace")


def permissions():
    paths = {"parent_vhost": PROD.parent, "parent_production": PROD, "parent_staging": STAGE.parent,
             "staging": STAGE, "staging_central": STAGE / "central",
             "staging_entities": STAGE / "entidades", "staging_code": STAGE / "platform_app",
             "staging_control": Path("/srv/rifas-deploy/staging/control"),
             "production_central": PROD / "central", "production_entities": PROD / "entidades",
             "legacy": LEGACY, "plesk_vhost_config": VHOST}
    for role, path in paths.items():
        try:
            info = path.stat()
            named = read_command("/usr/bin/getfacl", "-cpn", "--", str(path))
            if named is None:
                unresolved.add("acl_not_visible")
            lines = (named or "").splitlines()
            emit("permissions", role=role, mode=oct(stat.S_IMODE(info.st_mode)),
                 owner_matches_probe=info.st_uid == os.geteuid(),
                 owning_group_matches_probe=info.st_gid in {os.getegid(), *os.getgroups()},
                 symlink_in_path=path.resolve() != path, mount=path.is_mount(),
                 acl_visible=named is not None,
                 named_acl_entries=sum(bool(re.match(r"^(?:default:)?(?:user|group):\d+:", line)) for line in lines),
                 named_write_entries=sum(bool(re.match(r"^(?:default:)?(?:user|group):\d+:[r-]w", line)) for line in lines),
                 default_acl=any(line.startswith("default:") for line in lines),
                 setgid=bool(info.st_mode & stat.S_ISGID))
        except (OSError, RuntimeError):
            emit("permissions", role=role, available=False)
            unresolved.add("path_permissions_incomplete")
    unresolved.add("acl_effective_for_future_identity_and_descendants_requires_review")


def dependencies():
    dependency_fields = ("Requires", "Wants", "BindsTo", "PartOf", "Before", "After",
                         "Triggers", "TriggeredBy", "RequiresMountsFor", "Conflicts",
                         "PropagatesStopTo", "StopPropagatedFrom", "ConsistsOf", "OnFailure")
    policy_fields = ("ReadWritePaths", "InaccessiblePaths", "BindPaths", "BindReadOnlyPaths",
                     "ProtectSystem", "NoNewPrivileges", "KillMode", "RootDirectory", "RootImage",
                     "ExecStartPre", "ExecStopPost", "EnvironmentFiles")
    raw = read_command("/usr/bin/systemctl", "--no-pager", "show",
                       "--property=" + ",".join(dependency_fields + policy_fields), UNIT)
    if raw is None:
        unresolved.add("service_dependency_visibility_incomplete")
        return
    values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    for field in dependency_fields:
        entries = values.get(field, "").split()
        emit("dependency", property=field, count=len(entries),
             production_reference="rifas-platform.service" in entries,
             legacy_hint=any("sorteos" in value.lower() for value in entries))
    emit("service_policy", declared=[key for key in policy_fields if values.get(key)],
         protect_system_strict=values.get("ProtectSystem") == "strict",
         kills_control_group=values.get("KillMode") == "control-group",
         permits_elevation=values.get("NoNewPrivileges") != "yes")
    timers = read_command("/usr/bin/systemctl", "--no-pager", "--no-legend", "list-timers", "--all")
    emit("scheduled", timer_list_visible=timers is not None,
         matching_hints=sum(bool(re.search(r"\b(?:rifas|sorteos)", line, re.I))
                            for line in (timers or "").splitlines()),
         cron_sources_present=Path("/etc/cron.d").is_dir())
    unresolved.add("worker_lifecycle_user_cron_and_plesk_scheduled_tasks_need_review")


if __name__ == "__main__":
    emit("inspection", phase="2E", read_only=True, sqlite_opened=False)
    proxy()
    direct_backend()
    permissions()
    dependencies()
    emit("limits", pending=sorted(unresolved))
'
