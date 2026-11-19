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


def read_config(path):
    if not path.resolve(strict=True).is_relative_to(BASE) or not path.is_file():
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


if __name__ == "__main__":
    emit("inspection", read_only=True, targeted=True)
    acl()
    route()
'
