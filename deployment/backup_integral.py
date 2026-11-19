from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import sqlite3

from backup_sqlite import backup_database, verify_sqlite, sha256

EXCLUDED = {
    '__pycache__',
    'venv',
    '.git',
    'logs',
    'tmp',
}


def collect_files(root):
    root = Path(root).resolve()
    selected = []

    for relative in ('central', 'platform_app', 'entidades', 'wsgi.py'):
        base = root / relative

        if not base.exists():
            raise RuntimeError('Ruta obligatoria inexistente: ' + str(base))

        if base.is_symlink():
            raise RuntimeError('Enlace simbólico no admitido: ' + str(base))

        if base.is_file():
            selected.append(base)
            continue

        for directory, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = sorted(
                name for name in dirs
                if name not in EXCLUDED
                and not (Path(directory) / name).is_symlink()
            )

            for name in sorted(names):
                path = Path(directory) / name

                if path.is_symlink():
                    raise RuntimeError(
                        'Enlace simbólico no admitido: ' + str(path)
                    )

                if path.is_file():
                    selected.append(path)

    return selected


def create_backup(root, destination):
    root = Path(root).resolve()
    destination = Path(destination).resolve()

    if destination.exists():
        raise RuntimeError('Destino de respaldo ya existente')

    if not destination.parent.is_dir():
        raise RuntimeError('Directorio de respaldo inexistente')

    files = collect_files(root)

    if destination.is_relative_to(root):
        raise RuntimeError('El respaldo no puede estar dentro del origen')

    destination.mkdir(mode=0o700)

    records = []

    try:
        for original in files:
            relative = original.relative_to(root)
            copied = destination / relative
            copied.parent.mkdir(parents=True, exist_ok=True)

            if original.suffix.lower() in ('.sqlite', '.sqlite3', '.db'):
                record = backup_database(original, copied)
                kind = 'sqlite'
            else:
                shutil.copy2(original, copied)
                kind = 'file'

            digest = sha256(copied)

            records.append({
                'path': str(relative),
                'type': kind,
                'size': copied.stat().st_size,
                'sha256': digest,
            })

        inventory = {
            'format': 'rifas-integral-backup-v1',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'source': str(root),
            'files': records,
        }

        inventory_path = destination / 'inventory.json'

        with inventory_path.open('x', encoding='utf-8') as handle:
            json.dump(inventory, handle, indent=2, ensure_ascii=False)
            handle.write('\n')

        verify_backup(destination)

        return inventory

    except BaseException:
        shutil.rmtree(destination)
        raise


def verify_backup(destination):
    destination = Path(destination).resolve()
    inventory_path = destination / 'inventory.json'

    inventory = json.loads(
        inventory_path.read_text(encoding='utf-8')
    )

    if inventory.get('format') != 'rifas-integral-backup-v1':
        raise RuntimeError('Formato de inventario incorrecto')

    for record in inventory['files']:
        relative = Path(record['path'])

        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Ruta insegura en inventario')

        path = destination / relative

        if not path.is_file():
            raise RuntimeError('Archivo de respaldo ausente')

        if sha256(path) != record['sha256']:
            raise RuntimeError(
                'SHA-256 incorrecto: ' + str(relative)
            )

        if record['type'] == 'sqlite':
            verify_sqlite(path)

    return True
