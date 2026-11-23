"""External configuration inventory and verified backup.

Paths come exclusively from a validated installation manifest. Restoration of
privileged files is deliberately not performed here: it requires a reviewed,
environment-scoped administrator operation.
"""
from pathlib import Path
import hashlib
import json
import shutil

from deployment.installation import load_installation


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_external(environment, installation_manifest):
    config = load_installation(installation_manifest)
    if environment not in config["environments"]:
        raise ValueError("Entorno no válido")
    records = []
    for filename in config["environments"][environment]["external_files"]:
        path = Path(filename)
        if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
            raise RuntimeError("Configuración externa no disponible o insegura: " + filename)
        records.append({
            "source": filename,
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    return records


def backup_external(environment, destination, installation_manifest):
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("Destino ya existente")
    records = inventory_external(environment, installation_manifest)
    destination.mkdir(parents=True, mode=0o700)
    try:
        for index, record in enumerate(records):
            source = Path(record["source"])
            copied = destination / (str(index) + "_" + source.name)
            shutil.copy2(source, copied, follow_symlinks=False)
            if copied.is_symlink() or sha256(copied) != record["sha256"]:
                raise RuntimeError("Error de verificación: " + str(source))
            record["backup_name"] = copied.name
        manifest = {
            "format": "rifas-external-backup-v1",
            "environment": environment,
            "files": records,
        }
        with (destination / "inventory.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
        return manifest
    except BaseException:
        shutil.rmtree(destination)
        raise


def verify_external(destination):
    destination = Path(destination)
    inventory = destination / "inventory.json"
    if inventory.is_symlink():
        raise RuntimeError("Inventario simbólico")
    manifest = json.loads(inventory.read_text(encoding="utf-8"))
    if manifest.get("format") != "rifas-external-backup-v1":
        raise RuntimeError("Formato de inventario incorrecto")
    for record in manifest["files"]:
        copied = destination / record["backup_name"]
        if (copied.is_symlink() or not copied.is_file()
                or copied.parent != destination
                or sha256(copied) != record["sha256"]):
            raise RuntimeError("Integridad incorrecta: " + str(copied))
    return True
