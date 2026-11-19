/usr/bin/python3 -I -B -c 'import errno
import glob
import json
import os
from pathlib import Path
import re
import struct
import subprocess

PROD = Path("/var/www/vhosts/dealfonso.com/rifas")
STAGE = PROD / "staging/prueba_231"
BASE = Path("/var/www/vhosts/system/dealfonso.com/conf")
RULES = {
    "allow", "deny", "satisfy", "auth_basic", "auth_request", "auth_jwt",
    "return", "error_page", "rewrite", "try_files", "limit_except",
    "proxy_pass", "proxy_cache", "proxy_intercept_errors", "include",
}
TOKEN = re.compile(r"""\#[^\n]*|"(?:\\.|[^"\\])*"|'"'"'(?:\\.|[^'"'"'\\])*'"'"'|[{};]|(?:\$\{[^}]+\}|[^\s{};#])+""")


def emit(section, **fields):
    print(json.dumps({"section": section, **fields}, sort_keys=True))


def acl_tool(path):
    try:
        result = subprocess.run(["/usr/bin/getfacl", "-cpn", "--", str(path)],
                                capture_output=True, timeout=5,
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except FileNotFoundError:
        return "executable_missing"
    except PermissionError:
        return "executable_denied"
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError:
        return "execution_error"
    if result.returncode == 0:
        return "read"
    text = result.stderr.lower()
    for marker, alias in ((b"permission denied", "path_denied"),
                          (b"operation not permitted", "path_denied"),
                          (b"no such file or directory", "path_missing"),
                          (b"not supported", "operation_unsupported")):
        if marker in text:
            return alias
    return "exit_error"


def acl_xattr(path, name):
    try:
        data = os.getxattr(path, "system.posix_acl_" + name)
    except OSError as error:
        states = {errno.ENODATA: "attribute_absent", errno.ENOTSUP: "operation_unsupported",
                  errno.EACCES: "path_denied", errno.EPERM: "path_denied", errno.ENOENT: "path_missing"}
        return {"state": states.get(error.errno, "read_error")}
    if len(data) < 4 or (len(data) - 4) % 8 or struct.unpack_from("<I", data)[0] != 2:
        return {"state": "unrecognized"}
    entries = list(struct.iter_unpack("<HHI", data[4:]))
    mask = next((mode for tag, mode, _ in entries if tag == 16), 7)
    return {"state": "read", "named": sum(tag in {2, 8} for tag, _, _ in entries),
            "named_effective_write": sum(tag in {2, 8} and bool(mode & mask & 2)
                                         for tag, mode, _ in entries)}


def acl():
    emit("acl_utility", result=acl_tool(STAGE))
    paths = {"vhost_parent": PROD.parent, "production_parent": PROD, "staging_parent": STAGE.parent,
             "staging": STAGE, "staging_data": STAGE / "central", "staging_entities": STAGE / "entidades",
             "production_data": PROD / "central", "production_entities": PROD / "entidades",
             "legacy": PROD.parent / "sorteos", "control_parent": Path("/srv/rifas-deploy/staging")}
    for role, path in paths.items():
        emit("acl_metadata", role=role, access=acl_xattr(path, "access"), default=acl_xattr(path, "default"))


def read_config(path, allowed=None):
    canonical = path.resolve(strict=True)
    if not any(canonical.is_relative_to(root) for root in (allowed or (BASE,))) or not path.is_file():
        raise ValueError("outside")
    with path.open(errors="replace") as source:
        text = source.read(512 * 1024 + 1)
    if len(text) > 512 * 1024:
        raise ValueError("limit")
    root = {"items": [], "parent": None, "kind": "file"}
    block = root
    words = []
    line = 1
    last = 0
    for match in TOKEN.finditer(text):
        line += text.count("\n", last, match.start())
        last = match.end()
        token = match[0]
        if token.startswith("#"):
            continue
        if token == "}":
            if words or block["parent"] is None:
                raise ValueError("syntax")
            block = block["parent"]
        elif token in ("{", ";"):
            if not words:
                raise ValueError("syntax")
            item = {"kind": words[0], "args": words[1:], "line": start, "parent": block, "items": []}
            block["items"].append(item)
            if token == "{":
                block = item
            words = []
        else:
            if not words:
                start = line
            words.append(token)
    if words or block is not root:
        raise ValueError("syntax")
    return root


def walk(block):
    for item in block["items"]:
        yield item
        yield from walk(item)


def rule(item, scope):
    args = " ".join(item["args"])
    emit("route_rule", scope=scope, line=item["line"], directive=item["kind"],
         returns_503=item["kind"] == "return" and bool(item["args"]) and item["args"][0] == "503",
         dynamic=bool(re.search(r"\$|~", args)))


def route():
    source = BASE / "vhost_nginx.conf"
    try:
        tree = read_config(source)
        matches = [item for item in walk(tree) if item["kind"] == "proxy_pass"
                   and re.search(r":8768(?:[/'"'"'\x22]|$)", " ".join(item["args"]))]
        anchors = [item for item in matches if item["line"] == 42]
        if len(anchors) != 1:
            emit("route", state="anchor_drift_or_unreadable", literal_matches=len(matches))
            return
        anchor = anchors[0]
        chain = []
        node = anchor["parent"]
        while node is not None:
            chain.append(node)
            node = node["parent"]
        pending = {"inheritance_from_effective_http_vhost", "competing_locations_and_public_aliases"}
        emit("route", state="anchor_parsed", file=source.name, line=42, literal_matches=len(matches),
             effective_verified=False)
        visited = {source.resolve()}
        for scope in chain:
            level = scope["kind"] if scope["kind"] in {"server", "location", "if", "file"} else "other"
            if level != "file":
                emit("route_scope", kind=level, line=scope["line"])
            for item in scope["items"]:
                if any(item is member for member in chain):
                    continue
                if item["kind"] == "if":
                    pending.add("conditional_rules_require_runtime_confirmation")
                    for nested in walk(item):
                        if nested["kind"] in RULES:
                            rule(nested, "conditional")
                if item["kind"] not in RULES:
                    continue
                rule(item, level)
                if item["kind"] == "limit_except":
                    for nested in walk(item):
                        if nested["kind"] in RULES:
                            rule(nested, "method")
                if item["kind"] != "include":
                    continue
                if not item["args"]:
                    pending.add("include_unresolved")
                    continue
                pattern = item["args"][0].strip("\"'"'"'")
                if not Path(pattern).is_absolute() or not Path(pattern).is_relative_to(BASE):
                    pending.add("external_or_relative_include")
                    continue
                for match in glob.iglob(pattern):
                    included = Path(match)
                    if len(visited) >= 32:
                        pending.add("include_limit")
                        break
                    if included.resolve() in visited:
                        continue
                    visited.add(included.resolve())
                    try:
                        for nested in read_config(included)["items"]:
                            if nested["kind"] in RULES:
                                rule(nested, "include")
                            if nested["kind"] == "include" or nested["items"]:
                                pending.add("nested_include_or_block_not_resolved")
                    except (OSError, ValueError, RuntimeError):
                        pending.add("include_unreadable")
        emit("route_limits", pending=sorted(pending))
    except (OSError, ValueError, RuntimeError, RecursionError):
        emit("route", state="configuration_unreadable_or_not_safely_parsed")


# Lecturas de cierre. Se reutilizan el parser Nginx y la lectura POSIX ACL.
import stat

LEGACY = PROD.parent / "sorteos"
CONTROL = Path("/srv/rifas-deploy/staging/control")
NGINX = Path("/etc/nginx")
PROC = Path("/proc")
SYSTEMD = "/usr/bin/systemctl"
SCOPE_ROOTS = (("staging", STAGE), ("production", PROD), ("legacy", LEGACY))
PENDING = set()
EDGE_FIELDS = ("Requires", "Wants", "BindsTo", "PartOf", "ConsistsOf", "Conflicts",
               "PropagatesStopTo", "StopPropagatedFrom", "OnFailure", "OnSuccess",
               "Triggers", "TriggeredBy", "Requisite")
SERVICE_NAMES = {"staging": "rifas-pruebas.service", "production": "rifas-platform.service"}
STAGING_PATH = re.compile(r"(?i)(?:/rifas/staging\b|\bprueba_231\b|\brifas-pruebas\b|(?<!\d)8768(?!\d))")
PRODUCTION_PATH = re.compile(r"(?i)(?:\brifas-platform\b|(?<!\d)8767(?!\d)|/rifas/(?:central|entidades)\b)")
LEGACY_PATH = re.compile(r"(?i)(?:/sorteos(?:/|\b)|(?<!\d)8766(?!\d))")
REVISED_RULES = RULES | {"root", "alias", "internal", "listen", "server_name", "satisfy", "map"}


def scope_of(value):
    path = Path(value)
    for scope, root in SCOPE_ROOTS:
        if path.is_relative_to(root):
            return scope
    return "outside"


def hints(value):
    return [scope for scope, pattern in (("staging", STAGING_PATH), ("production", PRODUCTION_PATH),
                                         ("legacy", LEGACY_PATH)) if pattern.search(value)]


def short_read(path, limit=512 * 1024):
    with path.open(errors="replace") as handle:
        value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError("read_limit")
    return value


def read_command(*argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, errors="replace", check=True,
                                timeout=4, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        if len(result.stdout) <= 512 * 1024:
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


class IncludeReview:
    def __init__(self):
        self.files = {}
        self.locations = []
        self.expanded = set()

    def select_file(self, path):
        canonical = path.resolve(strict=True)
        if not canonical.is_relative_to(NGINX) and not canonical.is_relative_to(BASE):
            raise ValueError("external_include")
        if canonical not in self.files:
            if len(self.files) >= 64:
                raise ValueError("file_limit")
            self.files[canonical] = len(self.files) + 1
        return canonical

    def expand_file(self, path, ancestors=(), depth=0):
        if depth > 8:
            raise ValueError("depth_limit")
        canonical = self.select_file(path)
        if canonical in ancestors:
            raise ValueError("cycle")
        identifier = self.files[canonical]
        if canonical in self.expanded:
            PENDING.add("configuration_included_more_than_once")
        self.expanded.add(canonical)
        node = read_config(canonical, (NGINX, BASE))
        self.expand_block(node, identifier, (*ancestors, canonical), depth)
        return node

    def expand_block(self, node, identifier, ancestors, depth):
        children = []
        for item in node["items"]:
            item["file"] = identifier
            if item["kind"] != "include":
                self.expand_block(item, identifier, ancestors, depth)
                children.append(item)
                continue
            if len(item["args"]) != 1 or "$" in item["args"][0]:
                PENDING.add("dynamic_include")
                continue
            pattern = item["args"][0].strip("\"'"'"'")
            if not Path(pattern).is_absolute():
                # Nginx puede resolver rutas relativas con un prefijo distinto.
                PENDING.add("relative_include_requires_effective_prefix")
                continue
            # No expandir patrones de otros vhosts o fuera del alcance.
            search = Path(pattern)
            if not search.is_relative_to(NGINX) and not search.is_relative_to(BASE):
                PENDING.add("external_include")
                continue
            matches = sorted(glob.glob(pattern))
            if not matches and not glob.has_magic(pattern):
                PENDING.add("literal_include_missing")
            for count, match in enumerate(matches, start=1):
                if count > 64 or len(self.locations) >= 128:
                    PENDING.add("include_limit")
                    break
                try:
                    included = self.select_file(Path(match))
                    self.locations.append((self.files[included], identifier, item["line"]))
                    children.extend(self.expand_file(included, ancestors, depth + 1)["items"])
                except (OSError, ValueError, RuntimeError):
                    PENDING.add("include_skipped_or_unreadable")
        node["items"] = children
        for item in children:
            item["parent"] = node


def apache_hints():
    for name in ("httpd.conf", "last_httpd.conf", "vhost.conf", "vhost_ssl.conf"):
        try:
            path = (BASE / name).resolve(strict=True)
            if not path.is_relative_to(BASE) or not path.is_file():
                PENDING.add("apache_vhost_reference_outside_scope")
                continue
            for line, raw in enumerate(short_read(path).splitlines(), start=1):
                text = raw.strip()
                if text.startswith("#"):
                    continue
                if re.search(r"(?i)^(?:ProxyPass(?:Match)?|RewriteRule|Alias(?:Match)?|SetHandler)\b", text):
                    if "staging" in hints(text):
                        emit("apache_alternative_hint", file=name, line=line)
                    elif "$" in text or "%" in text:
                        PENDING.add("apache_dynamic_routes_unresolved")
        except FileNotFoundError:
            continue
        except (OSError, RuntimeError, ValueError):
            PENDING.add("apache_vhost_partial_visibility")


def nginx_entrypoint():
    default = NGINX / "nginx.conf"
    output = read_command(SYSTEMD, "--no-pager", "show", "--property=MainPID,Id", "nginx.service")
    properties = dict(line.split("=", 1) for line in (output or "").splitlines() if "=" in line)
    pid = properties.get("MainPID", "")
    if properties.get("Id") != "nginx.service" or not pid.isdecimal() or pid == "0":
        PENDING.add("active_nginx_command_not_visible")
        return default
    try:
        with (PROC / pid / "cmdline").open("rb") as handle:
            argv = handle.read(8193)
        if len(argv) > 8192 or b"nginx" not in argv:
            raise ValueError("unrecognized")
        line = argv.replace(b"\0", b" ").decode(errors="replace")
        explicit = re.search(r"(?<!\S)-c\s+([^\s;]+)", line)
        custom_prefix = bool(re.search(r"(?<!\S)-p(?:\s+|/)", line))
        emit("nginx_entrypoint_hint", active_command_visible=True,
             explicit_config=bool(explicit), custom_prefix=custom_prefix)
        if custom_prefix:
            PENDING.add("custom_nginx_prefix_requires_review")
        if explicit:
            path = Path(explicit[1]).resolve(strict=True)
            if not path.is_relative_to(NGINX) and not path.is_relative_to(BASE):
                PENDING.add("active_nginx_config_outside_review_scope")
            else:
                return path
        elif re.search(r"(?<!\S)-c\S", line):
            PENDING.add("active_nginx_config_argument_not_parsed")
    except (OSError, ValueError, RuntimeError):
        PENDING.add("active_nginx_command_not_visible")
    return default


def proxy_final(entrypoint=None):
    review = IncludeReview()
    try:
        tree = review.expand_file(entrypoint or NGINX / "nginx.conf")
    except (OSError, ValueError, RuntimeError):
        PENDING.add("nginx_entrypoint_unavailable")
        tree = {"items": []}
    if (BASE / "vhost_nginx.conf").resolve() not in review.files:
        PENDING.add("staging_vhost_fragment_not_reached_from_entrypoint")
        try:
            tree["items"].extend(review.expand_file(BASE / "vhost_nginx.conf")["items"])
        except (OSError, ValueError, RuntimeError):
            PENDING.add("staging_vhost_fragment_unavailable")
    for order, (file, parent, line) in enumerate(review.locations, start=1):
        emit("include_order", order=order, file=file, parent=parent, line=line)
    for path, number in review.files.items():
        known = {"nginx.conf", "vhost_nginx.conf", "httpd.conf"}
        emit("configuration_file", id=number, area="plesk_vhost" if path.is_relative_to(BASE) else "nginx",
             recognized_name=path.name if path.name in known else None)
    nodes = list(walk(tree))
    upstreams = {item["args"][0] for item in nodes if item["kind"] == "upstream" and item["args"]
                 and any(child["kind"] == "server" and re.search(r":8768\b", " ".join(child["args"]))
                         for child in item["items"])}
    candidate_count = 0
    for item in nodes:
        text = " ".join(item["args"])
        if item["kind"] != "proxy_pass" or not (
            re.search(r":8768(?:[/'"'"'\x22]|$)", text)
            or any(re.match(r"https?://" + re.escape(name) + r"(?:/|$)", text.strip("\"'"'"'"))
                   for name in upstreams)
        ):
            continue
        candidate_count += 1
        parent = item["parent"]
        while parent is not None and parent["kind"] != "location":
            parent = parent["parent"]
        location = parent
        while parent is not None and parent["kind"] != "server":
            parent = parent["parent"]
        server = parent
        emit("staging_route_candidate", file=item.get("file"), line=item["line"],
             location_line=location["line"] if location else None, server_line=server["line"] if server else None,
             via_named_upstream=not bool(re.search(r":8768\b", text)))
        parent = item["parent"]
        while parent is not None:
            for child in parent["items"]:
                kind = child["kind"]
                if kind in REVISED_RULES:
                    emit("effective_route_hint", file=child.get("file"), line=child["line"], directive=kind,
                         scope=parent["kind"] if parent["kind"] in {"file", "http", "server", "location", "if"} else "other",
                         backend_scopes=hints(" ".join(child["args"])),
                         returns_503=kind == "return" and child["args"][:1] == ["503"])
                elif kind in {"if", "limit_except"}:
                    for nested in walk(child):
                        if nested["kind"] in REVISED_RULES:
                            emit("conditional_route_hint", file=nested.get("file"), line=nested["line"],
                                 directive=nested["kind"], condition_kind=kind,
                                 returns_503=nested["kind"] == "return" and nested["args"][:1] == ["503"],
                                 expected_marker=str(CONTROL / "maintenance") in " ".join(child["args"]))
            parent = parent["parent"]
        if server:
            siblings = [node for node in server["items"] if node["kind"] == "location" and node is not location]
            emit("competing_routes", server_line=server["line"], total=len(siblings),
                 potential_dynamic=sum(bool(re.search(r"\$|~|@", " ".join(node["args"]))) for node in siblings),
                 aliases_declared=sum(node["kind"] == "server_name" for node in server["items"]))
            for sibling in siblings:
                emit("competing_route_hint", file=sibling.get("file"), line=sibling["line"],
                     dynamic=bool(re.search(r"\$|~|@", " ".join(sibling["args"]))),
                     access_directives=sorted({rule["kind"] for rule in sibling["items"]
                                               if rule["kind"] in {"allow", "deny", "auth_basic", "auth_request",
                                                                   "return", "internal", "proxy_pass", "alias",
                                                                   "root", "rewrite", "try_files"}}))
    for child in nodes:
        kind = child["kind"]
        if kind in {"alias", "root", "rewrite", "return", "try_files", "map", "proxy_pass"}:
            text = " ".join(child["args"])
            if (kind == "proxy_pass" and "$" in text) or "staging" in hints(text):
                emit("alternative_review_hint", file=child.get("file"), line=child["line"], directive=kind,
                     dynamic=bool(re.search(r"\$|~", text)), scope=child["parent"]["kind"]
                     if child["parent"]["kind"] in {"server", "location", "if", "http", "file"} else "other")
    apache_hints()
    emit("publication", candidates=candidate_count, effective_verified=False,
         known_control_marker_present=(CONTROL / "maintenance").is_file())
    PENDING.update(("loaded_runtime_configuration_and_public_route_precedence_unproven",
                    "apache_dynamic_proxy_and_external_bypass_require_review",
                    "maintenance_behavior_and_authenticated_portal_require_authorized_test"))


def show_unit(name, fields):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*\.(?:service|timer|socket)", name):
        return None
    output = read_command(SYSTEMD, "--no-pager", "show", "--property=" + ",".join(fields), name)
    if output is None:
        return None
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def dependencies_final():
    fields = ("Id", "LoadState", "User", "Group", "ControlGroup", *EDGE_FIELDS)
    data = {}
    for scope, name in SERVICE_NAMES.items():
        values = show_unit(name, fields)
        if values is not None and values.get("Id") == name and values.get("LoadState") == "loaded":
            data[scope] = values
        else:
            PENDING.add("unit_access_incomplete")
    initial = data.get("staging", {})
    visited = {SERVICE_NAMES["staging"]}
    queue = [(name, edge, 1) for edge in EDGE_FIELDS for name in initial.get(edge, "").split()]
    while queue:
        name, edge, depth = queue.pop(0)
        if name in visited:
            continue
        if len(visited) >= 24:
            PENDING.add("dependency_graph_limit")
            break
        visited.add(name)
        match = hints(name)
        if match:
            emit("dependency_hit", depth=depth, edge=edge, scopes=match)
        if not name.endswith((".service", ".timer", ".socket")):
            PENDING.add("dependency_graph_contains_other_unit_types")
            continue
        values = show_unit(name, ("Id", "LoadState", *EDGE_FIELDS))
        if values is None or values.get("LoadState") != "loaded":
            PENDING.add("dependencies_not_fully_visible")
        elif depth < 3:
            queue.extend((target, field, depth + 1) for field in EDGE_FIELDS
                         for target in values.get(field, "").split())
        elif any(value for field, value in values.items() if field in EDGE_FIELDS):
            PENDING.add("dependency_depth_limit")
    emit("dependency_visibility", visited=len(visited), complete=False)
    return data


def writers_final():
    readers_denied = 0
    inspected = 0
    descriptor_budget = 12000
    incomplete = False
    for proc in PROC.iterdir():
        if not proc.name.isdecimal():
            continue
        if inspected >= 4096 or descriptor_budget <= 0:
            incomplete = True
            break
        inspected += 1
        found = set()
        try:
            for index, fd in enumerate((proc / "fd").iterdir()):
                descriptor_budget -= 1
                if index >= 512 or descriptor_budget <= 0:
                    incomplete = True
                    break
                try:
                    path = os.readlink(fd).removesuffix(" (deleted)")
                    scope = scope_of(path)
                    if scope == "outside":
                        continue
                    flags = re.search(r"(?m)^flags:\s*([0-7]+)$", (proc / "fdinfo" / fd.name).read_text())
                    if flags and (int(flags[1], 8) & os.O_ACCMODE) in (os.O_WRONLY, os.O_RDWR):
                        found.add(scope)
                except FileNotFoundError:
                    continue
            with (proc / "maps").open(errors="replace") as maps:
                for count, line in enumerate(maps):
                    if count >= 2048:
                        incomplete = True
                        break
                    parts = line.split(maxsplit=5)
                    if len(parts) == 6 and len(parts[1]) == 4 and parts[1][1] == "w" and parts[1][3] == "s":
                        scope = scope_of(parts[5].strip().removesuffix(" (deleted)"))
                        if scope != "outside":
                            found.add(scope)
        except PermissionError:
            readers_denied += 1
        except FileNotFoundError:
            continue
        except OSError:
            incomplete = True
        if found:
            emit("writer_hint", pid=int(proc.name), scopes=sorted(found))
    emit("writer_visibility", inspected=inspected, denied=readers_denied, capped=incomplete)
    PENDING.add("writer_snapshot_cannot_exclude_idle_jobs_external_tools_or_mount_aliases")


def scheduled_final(services):
    user_cron = {}
    for scope, values in services.items():
        owner = values.get("User", "")
        if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", owner):
            user_cron.setdefault(owner, []).append(scope)
    common = [(Path("/etc/crontab"), ["system"])]
    try:
        paths = list(Path("/etc/cron.d").iterdir())
        common.extend((path, ["system"]) for path in paths[:48] if path.is_file())
        if len(paths) > 48:
            PENDING.add("system_cron_limit")
    except OSError:
        PENDING.add("system_cron_not_visible")
    candidates = common + [(Path("/var/spool/cron/crontabs") / user, scopes) for user, scopes in user_cron.items()]
    for path, owners in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                if owners != ["system"]:
                    PENDING.add("user_cron_absent_or_not_visible")
                continue
            for number, line in enumerate(short_read(path, 64 * 1024).splitlines(), start=1):
                if not line.lstrip().startswith("#") and (scopes := hints(line)):
                    emit("cron_hint", owner_scope=owners, line=number, scopes=scopes)
        except (OSError, ValueError):
            PENDING.add("cron_not_fully_visible")
    PENDING.add("plesk_scheduler_requires_authorized_readonly_console_review")


def permission_delegation_final(services):
    emit("service_identity_relations", identities_visible=len(services) == 2,
         same_user=bool(len(services) == 2 and services["staging"].get("User") == services["production"].get("User")),
         same_group=bool(len(services) == 2 and services["staging"].get("Group") == services["production"].get("Group")))
    paths = {"staging_parent": STAGE.parent, "staging": STAGE, "staging_data": STAGE / "central",
             "staging_entities": STAGE / "entidades", "production": PROD, "legacy": LEGACY,
             "control_parent": CONTROL.parent}
    for role, path in paths.items():
        try:
            record = path.stat()
            emit("permission_hint", role=role, mode=oct(stat.S_IMODE(record.st_mode)),
                 probe_is_owner=record.st_uid == os.geteuid(),
                 probe_has_group=record.st_gid in {os.getegid(), *os.getgroups()},
                 writable_by_probe=os.access(path, os.W_OK, effective_ids=True),
                 traversal_by_probe=os.access(path, os.X_OK, effective_ids=True),
                 symlink_or_alias=path.resolve() != path)
        except (OSError, RuntimeError):
            emit("permission_hint", role=role, visible=False)
    try:
        for line in short_read(PROC / "self/mountinfo").splitlines():
            fields, _, rest = line.partition(" - ")
            parts = fields.split()
            if len(parts) < 6:
                continue
            location = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), parts[4]))
            scopes = [scope for scope, root in SCOPE_ROOTS
                      if root.is_relative_to(location) or location.is_relative_to(root)]
            if scopes:
                filesystem = rest.split()
                emit("mount_hint", scopes=scopes, readonly="ro" in parts[5].split(","),
                     nonroot_filesystem_subtree=parts[3] != "/",
                     network=bool(filesystem and filesystem[0] in {"nfs", "nfs4", "cifs", "smb3"}))
    except (OSError, ValueError):
        PENDING.add("mount_metadata_incomplete")
    for directory, kind in ((Path("/etc/sudoers.d"), "sudo"), (Path("/etc/polkit-1/rules.d"), "polkit")):
        try:
            for index, path in enumerate(sorted(directory.iterdir())):
                if index >= 32:
                    PENDING.add("delegation_rules_limit")
                    break
                if path.is_symlink() or not path.is_file():
                    continue
                raw = short_read(path, 64 * 1024)
                if re.search(r"rifas-pruebas|manage-units|systemctl", raw, re.I):
                    emit("delegation_hint", mechanism=kind, scopes=hints(raw),
                         generic_systemd_reference=bool(re.search(r"manage-units|systemctl", raw, re.I)))
        except (OSError, ValueError):
            PENDING.add("delegation_files_not_fully_visible")
    PENDING.add("effective_future_account_permissions_and_service_delegation_require_authorized_test")


def final_inspection():
    emit("inspection", read_only=True, unresolved_only=True, certification=False)
    proxy_final(nginx_entrypoint())
    services = dependencies_final()
    writers_final()
    scheduled_final(services)
    permission_delegation_final(services)
    emit("limits", pending=sorted(PENDING))


if __name__ == "__main__":
    final_inspection()
'
