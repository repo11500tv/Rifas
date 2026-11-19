from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys

STAGING = Path(
    '/var/www/vhosts/dealfonso.com/rifas/staging/prueba_231'
)
PRODUCTION = Path(
    '/var/www/vhosts/dealfonso.com/rifas'
)

REQUIRED_FILES = {
    'platform_app/raffle_routes.py',
    'platform_app/entity_routes.py',
    'platform_app/participant_raffle_purchases.py',
    'platform_app/raffle_image_storage.py',
    'platform_app/raffle_image_cleanup.py',
    'platform_app/raffle_migration.py',
    'platform_app/raffle_schema.py',
}

def inspect_database(path):
    if not path.is_file():
        raise RuntimeError('Base de datos inexistente: ' + str(path))

    with sqlite3.connect(
        path.resolve().as_uri() + '?mode=ro',
        uri=True
    ) as con:
        integrity = con.execute(
            'PRAGMA integrity_check'
        ).fetchone()[0]

        if integrity != 'ok':
            raise RuntimeError('SQLite no íntegra: ' + str(path))

        columns = {
            row[1] for row in con.execute(
                'PRAGMA table_info(raffles)'
            )
        }

        result = con.execute(
            "SELECT version FROM module_versions "
            "WHERE module='sorteos'"
        ).fetchone()

    version = result[0] if result else None

    if version not in ('2.2.0', '2.4.0'):
        raise RuntimeError(
            'Versión de sorteos no prevista: ' + str(version)
        )

    updated = {'image_filename', 'extended_info'} <= columns

    if version == '2.4.0' and not updated:
        raise RuntimeError(
            'Versión 2.4.0 sin columnas obligatorias'
        )

    return {'version': version, 'columns_ready': updated}


def verify_manifest(source, manifest):
    if manifest.get('package') != 'sorteos':
        raise RuntimeError('Paquete incorrecto')

    if manifest.get('module_version') != '2.4.0':
        raise RuntimeError('Versión objetivo incorrecta')

    if manifest.get('status') != 'preparation':
        raise RuntimeError('Estado de manifiesto inesperado')

    files = manifest.get('files')

    if not isinstance(files, list):
        raise RuntimeError('Archivos de manifiesto incorrectos')

    paths = {item['path'] for item in files}

    if paths != REQUIRED_FILES or len(files) != len(REQUIRED_FILES):
        raise RuntimeError('Archivos autorizados no coinciden')

    for item in files:
        relative = item['path']
        path = (source / relative).resolve()

        if not path.is_relative_to(source):
            raise RuntimeError('Ruta fuera de staging')

        if not path.is_file():
            raise RuntimeError('Archivo ausente: ' + relative)

        digest = hashlib.sha256(path.read_bytes()).hexdigest()

        if digest != item['sha256']:
            raise RuntimeError('SHA-256 incorrecto: ' + relative)

        if path.suffix == '.py':
            compile(path.read_bytes(), str(path), 'exec')

    return len(files)



def backup_restore_test():
    import tempfile
    import importlib.util

    module_path = STAGING / 'deployment/backup_sqlite.py'

    spec = importlib.util.spec_from_file_location(
        'rifas_backup_sqlite', module_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    print('===== PRUEBA AUTOMATICA DE RESPALDO Y RESTAURACION =====')

    with tempfile.TemporaryDirectory(prefix='rifas_backup_test_') as tmp:
        folder = Path(tmp)
        original_db = folder / 'original.sqlite3'
        backup_db = folder / 'respaldo.sqlite3'
        restored_db = folder / 'restaurada.sqlite3'

        with sqlite3.connect(original_db) as con:
            con.execute(
                'CREATE TABLE prueba (id INTEGER PRIMARY KEY, valor TEXT)'
            )
            con.execute(
                "INSERT INTO prueba(valor) VALUES ('dato_original')"
            )

        record = module.backup_database(original_db, backup_db)

        if not module.verify_sqlite(backup_db):
            raise RuntimeError('Copia no íntegra')

        if module.sha256(backup_db) != record['sha256']:
            raise RuntimeError('Huella de respaldo incorrecta')

        with sqlite3.connect(original_db) as con:
            con.execute(
                "UPDATE prueba SET valor='dato_modificado'"
            )

        with sqlite3.connect(
            backup_db.resolve().as_uri() + '?mode=ro',
            uri=True
        ) as source:
            with sqlite3.connect(restored_db) as destination:
                source.backup(destination)

        module.verify_sqlite(restored_db)

        with sqlite3.connect(restored_db) as con:
            value = con.execute(
                'SELECT valor FROM prueba WHERE id=1'
            ).fetchone()[0]

        if value != 'dato_original':
            raise RuntimeError('Restauración incorrecta')

        print('COPIA SQLITE: OK')
        print('INTEGRIDAD: OK')
        print('SHA-256: OK')
        print('RESTAURACION: OK')
        print('DATO ORIGINAL RECUPERADO:', value)
        print('BASES REALES: SIN MODIFICAR')
        print('RESULTADO: PRUEBA DE RESPALDO SUPERADA')


def integral_backup_test():
    import tempfile
    import shutil

    sys.path.insert(0, str(STAGING / 'deployment'))
    from backup_integral import create_backup, verify_backup

    print('===== PRUEBA INTEGRAL AUTOMATIZADA =====')

    with tempfile.TemporaryDirectory(prefix='rifas_integral_') as temp:
        base = Path(temp)
        source = base / 'instalacion'
        backup = base / 'respaldo'
        restored = base / 'restaurada'

        for relative in (
            'central/plantillas',
            'platform_app',
            'entidades/demostracion/data',
            'entidades/demostracion/config',
            'entidades/demostracion/uploads/sorteos',
        ):
            (source / relative).mkdir(parents=True, exist_ok=True)

        databases = (
            'central/plataforma.sqlite',
            'central/plantillas/entidad_maestra.sqlite3',
            'entidades/demostracion/data/rifas.sqlite3',
        )

        for relative in databases:
            with sqlite3.connect(source / relative) as con:
                con.execute(
                    'CREATE TABLE prueba(id INTEGER PRIMARY KEY, valor TEXT)'
                )
                con.execute(
                    "INSERT INTO prueba(valor) VALUES ('original')"
                )

        (source / 'platform_app/__init__.py').write_text(
            'def create_app(): pass\n', encoding='utf-8'
        )
        (source / 'wsgi.py').write_text(
            'from platform_app import create_app\n', encoding='utf-8'
        )
        (source / 'entidades/demostracion/config/entity.json').write_text(
            '{"entidad":"demostracion"}', encoding='utf-8'
        )

        photo = (
            source /
            'entidades/demostracion/uploads/sorteos/premio.jpg'
        )
        photo.write_bytes(b'FOTO_ORIGINAL')

        inventory = create_backup(source, backup)
        assert verify_backup(backup)

        print('ARCHIVOS RESPALDADOS:', len(inventory['files']))
        print('INTEGRIDAD: OK')

        copied_photo = (
            backup /
            'entidades/demostracion/uploads/sorteos/premio.jpg'
        )
        copied_photo.write_bytes(b'FOTO_ALTERADA')

        try:
            verify_backup(backup)
        except RuntimeError:
            print('ALTERACION DETECTADA: OK')
        else:
            raise RuntimeError('No se detectó la alteración')

        copied_photo.write_bytes(b'FOTO_ORIGINAL')
        assert verify_backup(backup)

        shutil.copytree(backup, restored)
        assert verify_backup(restored)

        for relative in databases:
            with sqlite3.connect(restored / relative) as con:
                value = con.execute(
                    'SELECT valor FROM prueba'
                ).fetchone()[0]
                assert value == 'original'

        print('RESTAURACION SQLITE: OK')
        print('RESTAURACION ARCHIVOS: OK')

    print('DIRECTORIOS TEMPORALES: ELIMINADOS')
    print('BASES REALES: SIN MODIFICAR')
    print('RESULTADO: PRUEBA INTEGRAL SUPERADA')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--environment',
        choices=('staging', 'production'),
        required=True
    )
    parser.add_argument('--backup-test', action='store_true')
    parser.add_argument('--integral-test', action='store_true')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        required=False
    )
    args = parser.parse_args()
    if args.integral_test:
        integral_backup_test()
        return
    if args.backup_test:
        backup_restore_test()
        return
    if not args.dry_run:
        raise RuntimeError('Solo se permite --dry-run')

    source = STAGING.resolve()
    target = (
        STAGING if args.environment == 'staging'
        else PRODUCTION
    ).resolve()

    print('===== DESPLIEGUE UNIFICADO: SIMULACION =====')
    print('ORIGEN:', source)
    print('DESTINO:', target)
    print('MODO: SOLO LECTURA')

    manifest_path = (
        source / 'deployment/sorteos_2.4.0.json'
    )
    manifest = json.loads(
        manifest_path.read_text(encoding='utf-8')
    )

    print('\n--- PAQUETE ---')
    count = verify_manifest(source, manifest)
    print('ARCHIVOS VERIFICADOS:', count)

    print('\n--- BASE CENTRAL ---')
    central = target / 'central/plataforma.sqlite'

    if not central.is_file():
        raise RuntimeError('Base central inexistente')

    with sqlite3.connect(
        central.resolve().as_uri() + '?mode=ro',
        uri=True
    ) as con:
        integrity = con.execute(
            'PRAGMA integrity_check'
        ).fetchone()[0]

    if integrity != 'ok':
        raise RuntimeError('Base central no íntegra')

    print('INTEGRIDAD: OK')

    print('\n--- PLANTILLA MAESTRA ---')
    template = (
        target / 'central/plantillas/entidad_maestra.sqlite3'
    )
    template_info = inspect_database(template)
    print('VERSION:', template_info['version'])
    print('COLUMNAS 2.4.0:', template_info['columns_ready'])

    print('\n--- ENTIDADES ---')
    entities = target / 'entidades'

    if not entities.is_dir():
        raise RuntimeError('Directorio de entidades inexistente')

    count_entities = 0

    for folder in sorted(entities.iterdir()):
        if not folder.is_dir():
            continue

        database = folder / 'data/rifas.sqlite3'

        if not database.is_file():
            continue

        info = inspect_database(database)

        print(
            folder.name,
            '| version:', info['version'],
            '| migracion:',
            'NO NECESARIA' if (
                info['version'] == '2.4.0'
                and info['columns_ready']
            ) else 'NECESARIA'
        )

        count_entities += 1

    if count_entities == 0:
        raise RuntimeError('No hay entidades verificables')



    print('\n--- INVENTARIO DE RESPALDO ---')

    mandatory = [
        target / 'central/plataforma.sqlite',
        target / 'central/plantillas/entidad_maestra.sqlite3',
        target / 'platform_app',
        target / 'wsgi.py',
    ]

    optional = []

    for folder in sorted(entities.iterdir()):
        if not folder.is_dir():
            continue

        database = folder / 'data/rifas.sqlite3'
        if not database.is_file():
            continue

        mandatory.append(database)
        optional.extend([
            folder / 'config',
            folder / 'uploads',
        ])

    missing = [p for p in mandatory if not p.exists()]
    if missing:
        raise RuntimeError(
            'Elementos obligatorios ausentes: ' +
            ', '.join(str(p) for p in missing)
        )

    for path in mandatory:
        kind = 'DIRECTORIO' if path.is_dir() else 'ARCHIVO'
        print('OBLIGATORIO', kind + ':', path.relative_to(target))

    for path in optional:
        if path.exists():
            kind = 'DIRECTORIO' if path.is_dir() else 'ARCHIVO'
            print('OPCIONAL', kind + ':', path.relative_to(target))
        else:
            print('OPCIONAL AUSENTE:', path.relative_to(target))

    print('ELEMENTOS OBLIGATORIOS:', len(mandatory))
    print('ELEMENTOS OPCIONALES:', len(optional))
    print('RESPALDO REAL: PENDIENTE DE IMPLEMENTACION')

    print('\n--- PLAN ---')
    print('ENTIDADES:', count_entities)
    print('COPIAS SQLITE: OBLIGATORIAS EN DESPLIEGUE REAL')
    print('COPIAS DE CODIGO Y FOTOS: OBLIGATORIAS')
    print('MIGRACIONES: SEGUN VERSION')
    print('VALIDACION POSTERIOR: OBLIGATORIA')
    print('REVERSIÓN: OBLIGATORIA')
    print('DESPLIEGUE REAL: TODAVIA NO HABILITADO')

    print('\nARCHIVOS MODIFICADOS: NINGUNO')
    print('BASES MODIFICADAS: NINGUNA')
    print('SERVICIOS REINICIADOS: NINGUNO')
    print('RESULTADO: SIMULACION SUPERADA')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('RESULTADO: SIMULACION FALLIDA')
        print('MOTIVO:', exc)
        sys.exit(1)
