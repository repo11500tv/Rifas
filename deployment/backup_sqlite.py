from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3
import tempfile


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def verify_sqlite(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise RuntimeError('SQLite inexistente: ' + str(path))
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        result = db.execute('PRAGMA integrity_check').fetchone()[0]
    if result != 'ok':
        raise RuntimeError('Integridad incorrecta: ' + str(path))
    return True


def backup_database(source, destination):
    source = Path(source).resolve()
    destination = Path(destination)

    if not source.is_file():
        raise RuntimeError('Origen inexistente: ' + str(source))
    if destination.exists():
        raise RuntimeError('Destino ya existente: ' + str(destination))
    if not destination.parent.is_dir():
        raise RuntimeError('Directorio de destino inexistente')

    verify_sqlite(source)

    fd, name = tempfile.mkstemp(
        prefix='.rifas_backup_',
        suffix='.sqlite3',
        dir=destination.parent
    )
    os.close(fd)
    temporary = Path(name)

    try:
        with sqlite3.connect(
            source.as_uri() + '?mode=ro', uri=True
        ) as original:
            with sqlite3.connect(temporary) as backup:
                original.backup(backup)

        verify_sqlite(temporary)
        digest = sha256(temporary)
        size = temporary.stat().st_size

        os.link(temporary, destination)
        temporary.unlink()

        if sha256(destination) != digest:
            destination.unlink(missing_ok=True)
            raise RuntimeError('SHA-256 incorrecto')

        return {
            'source': str(source),
            'backup': str(destination.resolve()),
            'size': size,
            'sha256': digest,
            'verified_at': datetime.now(timezone.utc).isoformat()
        }
    finally:
        temporary.unlink(missing_ok=True)


def write_inventory(records, destination):
    destination = Path(destination)
    if destination.exists():
        raise RuntimeError('Inventario ya existente')
    if not destination.parent.is_dir():
        raise RuntimeError('Directorio de inventario inexistente')

    content = {
        'format': 'rifas-backup-v1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'databases': records
    }

    fd, name = tempfile.mkstemp(
        prefix='.rifas_inventory_',
        suffix='.json',
        dir=destination.parent
    )

    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
            f.write('\\n')
            f.flush()
            os.fsync(f.fileno())

        os.link(name, destination)
        os.unlink(name)
    finally:
        Path(name).unlink(missing_ok=True)

    return content
