from pathlib import Path
import hashlib
import json
import shutil

EXTERNAL_FILES = {
    'staging': (
        '/etc/systemd/system/rifas-pruebas.service',
        '/var/www/vhosts/system/dealfonso.com/conf/vhost_nginx.conf',
    ),
    'production': (
        '/etc/systemd/system/rifas-platform.service',
        '/var/www/vhosts/system/dealfonso.com/conf/vhost_nginx.conf',
    ),
}


def sha256(path):
    digest = hashlib.sha256()

    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1048576), b''):
            digest.update(chunk)

    return digest.hexdigest()


def inventory_external(environment):
    if environment not in EXTERNAL_FILES:
        raise ValueError('Entorno no válido')

    records = []

    for filename in EXTERNAL_FILES[environment]:
        path = Path(filename)

        if not path.is_file() or path.is_symlink():
            raise RuntimeError(
                'Configuración externa no disponible: ' + filename
            )

        records.append({
            'source': filename,
            'size': path.stat().st_size,
            'sha256': sha256(path),
        })

    return records


def backup_external(environment, destination):
    destination = Path(destination)

    if destination.exists():
        raise RuntimeError('Destino ya existente')

    records = inventory_external(environment)
    destination.mkdir(parents=True, mode=0o700)

    try:
        for index, record in enumerate(records):
            source = Path(record['source'])
            copied = destination / (
                str(index) + '_' + source.name
            )

            shutil.copy2(source, copied)

            if sha256(copied) != record['sha256']:
                raise RuntimeError(
                    'Error de verificación: ' + str(source)
                )

            record['backup_name'] = copied.name

        manifest = {
            'format': 'rifas-external-backup-v1',
            'environment': environment,
            'files': records,
        }

        with (destination / 'inventory.json').open(
            'x', encoding='utf-8'
        ) as handle:
            json.dump(manifest, handle, indent=2)

        return manifest

    except BaseException:
        shutil.rmtree(destination)
        raise


def verify_external(destination):
    destination = Path(destination)

    manifest = json.loads(
        (destination / 'inventory.json').read_text(
            encoding='utf-8'
        )
    )

    if manifest.get('format') != 'rifas-external-backup-v1':
        raise RuntimeError('Formato de inventario incorrecto')

    for record in manifest['files']:
        copied = destination / record['backup_name']

        if not copied.is_file():
            raise RuntimeError('Archivo externo ausente')

        if sha256(copied) != record['sha256']:
            raise RuntimeError(
                'Integridad incorrecta: ' + str(copied)
            )

    return True
