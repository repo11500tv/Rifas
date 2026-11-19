from pathlib import Path
import argparse
import ast
import hashlib
import importlib.metadata
import json
import sqlite3
import sys

REQUIRED_COLUMNS = {'image_filename', 'extended_info'}
REQUIRED_PACKAGES = ('Flask', 'Pillow', 'reportlab', 'gunicorn')


def check_database(path, require_raffle_version=False):
    if not path.is_file():
        raise RuntimeError(f'Base de datos inexistente: {path}')

    with sqlite3.connect(
        path.resolve().as_uri() + '?mode=ro',
        uri=True
    ) as con:
        integrity = con.execute(
            'PRAGMA integrity_check'
        ).fetchone()[0]

        if integrity != 'ok':
            raise RuntimeError(f'Integridad incorrecta: {path}')

        columns = {
            row[1] for row in con.execute(
                'PRAGMA table_info(raffles)'
            )
        }

        if not REQUIRED_COLUMNS <= columns:
            raise RuntimeError(
                f'Faltan columnas de sorteos 2.4.0: {path}'
            )

        version = con.execute(
            "SELECT version FROM module_versions "
            "WHERE module='sorteos'"
        ).fetchone()

        if require_raffle_version:
            if not version or version[0] != '2.4.0':
                raise RuntimeError(
                    f'Versión incorrecta de sorteos: {path}'
                )

    return version[0] if version else 'NO DISPONIBLE'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest).resolve()

    print('===== PREFLIGHT SORTEOS 2.4.0 =====')
    print('ENTORNO:', root)

    manifest = json.loads(
        manifest_path.read_text(encoding='utf-8')
    )

    if manifest.get('package') != 'sorteos':
        raise RuntimeError('Paquete incorrecto')

    if manifest.get('module_version') != '2.4.0':
        raise RuntimeError('Versión de módulo incorrecta')

    if manifest.get('platform_version') != '2.3.1':
        raise RuntimeError('Versión de plataforma incorrecta')

    if manifest.get('status') != 'preparation':
        raise RuntimeError('Estado inesperado del manifiesto')

    files = manifest.get('files')

    if not isinstance(files, list) or not files:
        raise RuntimeError('Lista de archivos vacía')

    print('\n--- ARCHIVOS ---')

    seen = set()

    for item in files:
        relative = item['path']

        if relative in seen:
            raise RuntimeError('Archivo duplicado: ' + relative)

        seen.add(relative)

        path = (root / relative).resolve()

        if not path.is_relative_to(root):
            raise RuntimeError('Ruta fuera del entorno')

        if not path.is_file():
            raise RuntimeError('Archivo inexistente: ' + relative)

        digest = hashlib.sha256(path.read_bytes()).hexdigest()

        if digest != item['sha256']:
            raise RuntimeError('SHA-256 diferente: ' + relative)

        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'))

        print('OK:', relative)

    print('\n--- PLANTILLA MAESTRA ---')

    template = (
        root / 'central/plantillas/entidad_maestra.sqlite3'
    )

    version = check_database(template, True)

    print('INTEGRIDAD: OK')
    print('VERSION SORTEOS:', version)

    print('\n--- ENTIDADES ---')

    entities = root / 'entidades'

    if not entities.is_dir():
        raise RuntimeError('Directorio de entidades inexistente')

    count = 0

    for directory in sorted(entities.iterdir()):
        if not directory.is_dir():
            continue

        database = directory / 'data/rifas.sqlite3'

        if not database.is_file():
            continue

        version = check_database(database, True)

        print(
            'OK:', directory.name,
            '| SORTEOS:', version
        )

        count += 1

    if count == 0:
        raise RuntimeError('No se encontraron entidades')

    print('\n--- DEPENDENCIAS ---')

    for package in REQUIRED_PACKAGES:
        version = importlib.metadata.version(package)
        print('OK:', package, version)

    print('\nENTIDADES VERIFICADAS:', count)
    print('BASES MODIFICADAS: NINGUNA')
    print('RESULTADO: PREFLIGHT SUPERADO')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('RESULTADO: PREFLIGHT FALLIDO')
        print('MOTIVO:', exc)
        sys.exit(1)
