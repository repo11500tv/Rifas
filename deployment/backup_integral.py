"""Inventario y restauración del conjunto local bajo barrera de escritura."""

import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from deployment.backup_sqlite import backup_database, sha256, verify_sqlite


def sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    sync(path.parent)


def component(path):
    relative = Path(path)
    if (relative.is_absolute() or relative.as_posix() != path or not relative.parts
            or ".." in relative.parts or relative.parts[0] == ".rifas-deploy"):
        raise ValueError(f"Componente de recuperación inseguro: {path}")
    return relative


def confined(base, relative):
    path = base / relative
    if path.resolve() != path:
        raise ValueError(f"No se admiten enlaces en componentes de recuperación: {path}")
    return path


def roots(data, previous, extra):
    scopes = {"data": (data, [component(name) for name in ["central", "entidades", *extra]])}
    if previous is not None:
        scopes["code"] = (previous, [Path("platform_app"), Path("wsgi.py")])
    seen = set()
    for base, components in scopes.values():
        for path in components:
            absolute = confined(base, path)
            if any(absolute.is_relative_to(other) or other.is_relative_to(absolute) for other in seen):
                raise ValueError(f"Componentes de recuperación solapados: {absolute}")
            seen.add(absolute)
    return scopes


def inventory(data, previous, extra, databases, *, restoring=False):
    scopes = roots(data, previous, extra)
    database_paths = {data / path for path in databases}
    sidecars = {Path(str(path) + suffix) for path in database_paths for suffix in ("-wal", "-shm", "-journal")}
    records = []
    for group, (base, components) in scopes.items():
        for scope in components:
            top = confined(base, scope)
            if not top.exists():
                if restoring:
                    continue
                raise ValueError(f"Componente obligatorio ausente: {top}")
            paths = [top, *sorted(top.rglob("*"))] if top.is_dir() else [top]
            for path in paths:
                relative = path.relative_to(base)
                confined(base, relative)
                info = path.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                    raise ValueError(f"No se admiten enlaces físicos en componentes de recuperación: {path}")
                if path in sidecars:
                    continue
                if stat.S_ISDIR(info.st_mode):
                    kind = "directory"
                elif stat.S_ISREG(info.st_mode):
                    kind = "sqlite" if path in database_paths or path.suffix in (".sqlite", ".sqlite3", ".db") else "file"
                else:
                    raise ValueError(f"Componente no regular: {path}")
                if kind == "file" and path.name.endswith(("-wal", "-shm", "-journal")):
                    if path.with_name(path.name.rsplit("-", 1)[0]).suffix in (".sqlite", ".sqlite3", ".db"):
                        continue
                records.append({"group": group, "path": relative.as_posix(), "kind": kind,
                                "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid,
                                "gid": info.st_gid, "size": info.st_size if kind != "directory" else 0})
    return records


def capture(data, previous, extra, databases, folder, event):
    folder.mkdir(mode=0o700)
    bases = {"data": data, "code": previous}
    records = inventory(data, previous, extra, databases)
    for record in records:
        group, kind, name = (record[key] for key in ("group", "kind", "path"))
        if kind == "directory":
            continue
        source = bases[group] / name
        destination = folder / group / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if kind == "sqlite":
            backup_database(source, destination)
        else:
            shutil.copyfile(source, destination)
        record["sha256"] = sha256(destination)
        record["size"] = destination.stat().st_size
        sync(destination)
        event("backed_up", component=f"{group}/{name}", kind=kind)
    manifest = folder / "inventory.json"
    atomic_json(manifest, {"format": 1, "records": records})
    for directory, _, _ in os.walk(folder, topdown=False):
        sync(Path(directory))
    sync(folder.parent)
    return sha256(manifest)


def verify(folder, fingerprint):
    manifest = folder / "inventory.json"
    if sha256(manifest) != fingerprint:
        raise ValueError("Huella del inventario de restauración incorrecta")
    content = json.loads(manifest.read_text())
    if content["format"] != 1:
        raise ValueError("Formato de inventario de restauración incorrecto")
    for record in content["records"]:
        if record["kind"] == "directory":
            continue
        source = confined(folder, Path(record["group"]) / component(record["path"]))
        if source.stat().st_size != record["size"] or sha256(source) != record["sha256"]:
            raise ValueError(f"Componente de respaldo alterado: {record['path']}")
        if record["kind"] == "sqlite":
            verify_sqlite(source)
    return content["records"]


def metadata(path, record):
    info = path.stat()
    if (info.st_uid, info.st_gid) != (record["uid"], record["gid"]):
        os.chown(path, record["uid"], record["gid"])
    os.chmod(path, record["mode"])


def restore(data, previous, extra, databases, folder, fingerprint, event):
    records = verify(folder, fingerprint)
    expected = {(record["group"], record["path"]): record["kind"] for record in records}
    scopes = roots(data, previous, extra)
    current = inventory(data, previous, extra, databases, restoring=True)
    for record in sorted(current, key=lambda item: len(Path(item["path"]).parts), reverse=True):
        key = record["group"], record["path"]
        if expected.get(key) == record["kind"]:
            continue
        path = scopes[key[0]][0] / key[1]
        if record["kind"] == "directory":
            path.rmdir()
        else:
            path.unlink()
        sync(path.parent)
    for record in sorted(records, key=lambda item: len(Path(item["path"]).parts)):
        group, kind, name = (record[key] for key in ("group", "kind", "path"))
        path = confined(scopes[group][0], component(name))
        if kind == "directory":
            path.mkdir(parents=True, exist_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "sqlite":
            for suffix in ("-wal", "-shm", "-journal"):
                Path(str(path) + suffix).unlink(missing_ok=True)
        # El fichero temporal comparte volumen con su destino. Un reintento
        # vuelve a copiar desde el mismo inventario verificado.
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".rifas-restore-", delete=False) as temporary:
            replacement = Path(temporary.name)
        try:
            shutil.copyfile(folder / group / name, replacement)
            metadata(replacement, record)
            sync(replacement)
            os.replace(replacement, path)
        finally:
            replacement.unlink(missing_ok=True)
        sync(path.parent)
        event("restored", component=f"{group}/{name}", kind=kind)
    for record in reversed(records):
        if record["kind"] == "directory":
            path = scopes[record["group"]][0] / record["path"]
            metadata(path, record)
            sync(path.parent)
    recovered = inventory(data, previous, extra, databases)
    if {(r["group"], r["path"]): r["kind"] for r in recovered} != expected:
        raise ValueError("El inventario restaurado no coincide")
    for record in records:
        path = scopes[record["group"]][0] / record["path"]
        info = path.stat()
        if (stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid) != (record["mode"], record["uid"], record["gid"]):
            raise ValueError(f"Permisos restaurados incorrectos: {path}")
        if record["kind"] != "directory" and sha256(path) != record["sha256"]:
            raise ValueError(f"Huella restaurada incorrecta: {path}")
