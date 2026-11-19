#!/usr/bin/env python3
"""Rifas Benéficas: verificador no destructivo v0.4 (Python 3.12)."""
import argparse
import ast
import datetime as dt
import hashlib
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

VERSION = '0.4'
ROOT = Path('/var/www/vhosts/dealfonso.com/rifas')
CONFIG = {
    'produccion': {'service': 'rifas-platform', 'port': 8767, 'root': ROOT},
    'staging': {'service': 'rifas-pruebas', 'port': 8768, 'root': ROOT / 'staging/prueba_231'},
}
PENDING = ['Registro y autenticación de participantes', 'Reservas y caducidad',
           'Créditos y donativos', 'Envío SMTP', 'Generación de PDF',
           'Permisos y aislamiento funcional entre entidades']


def command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=8, check=False)


def http_check(port):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=6)
    try:
        conn.request('GET', '/')
        r = conn.getresponse()
        result = (r.status, r.getheader('Location'))
        r.read(4096)
        return result
    finally:
        conn.close()


def database_check(path):
    # mode=ro impide crear una base accidentalmente; query_only bloquea escrituras SQL.
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=8)
    try:
        con.execute('PRAGMA query_only=ON')
        integrity = [r[0] for r in con.execute('PRAGMA integrity_check')]
        fks = sum(1 for _ in con.execute('PRAGMA foreign_key_check'))
        tables = {}
        for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            # quote SQL identifier safely; names originate from sqlite_master
            ident = '"' + name.replace('"', '""') + '"'
            cols = [[r[1], r[2], r[3], r[4], r[5]] for r in con.execute('PRAGMA table_info(' + ident + ')')]
            indexes = [[r[1], r[2], r[3]] for r in con.execute('PRAGMA index_list(' + ident + ')')]
            tables[name] = {'columnas': cols, 'indices': sorted(indexes)}
        return integrity == ['ok'], fks, tables
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description='Diagnóstico seguro de Rifas Benéficas')
    ap.add_argument('entorno', choices=CONFIG)
    ap.add_argument('--report-dir', type=Path, default=Path.home() / 'rifas-check-informes')
    ap.add_argument('--baseline', type=Path, help='Comparar contra un informe JSON anterior')
    ap.add_argument('--no-report', action='store_true', help='No guardar informe')
    args = ap.parse_args()
    cfg = CONFIG[args.entorno]
    now = dt.datetime.now().astimezone()
    checks = []
    schema = {}

    def record(name, status, detail):
        checks.append({'prueba': name, 'estado': status, 'detalle': str(detail)})
        print(f'{status:>14}  {name}: {detail}')

    print(f'RIFAS CHECK {VERSION} | {args.entorno} | {now.isoformat()}')
    try:
        r = command(['systemctl', 'show', cfg['service'], '-p', 'ActiveState', '-p', 'WorkingDirectory', '-p', 'ExecStart'])
        values = dict(line.split('=', 1) for line in r.stdout.splitlines() if '=' in line)
        active = values.get('ActiveState') == 'active'
        cwd = values.get('WorkingDirectory') == str(cfg['root'])
        port = f'127.0.0.1:{cfg["port"]}' in values.get('ExecStart', '')
        record('Servicio y entorno', 'OK' if active and cwd and port else 'ERROR',
               f'activo={active}; directorio_correcto={cwd}; puerto_configurado={port}')
    except Exception as e:
        record('Servicio y entorno', 'ERROR', repr(e))
    try:
        status, location = http_check(cfg['port'])
        record('HTTP local', 'OK' if (status, location) == (302, '/login') else 'ERROR',
               f'HTTP {status}; Location={location}')
    except Exception as e:
        record('HTTP local', 'ERROR', repr(e))
    wsgi = cfg['root'] / 'wsgi.py'
    record('Punto de entrada wsgi.py', 'OK' if wsgi.is_file() else 'ERROR', str(wsgi))
    if wsgi.is_file():
        try:
            record('SHA256 wsgi.py', 'INFO', hashlib.sha256(wsgi.read_bytes()).hexdigest())
        except OSError as e:
            record('SHA256 wsgi.py', 'AVISO', repr(e))
    # Validación sintáctica sin importar módulos, ejecutar código ni crear __pycache__.
    # Solo código operativo: no recorrer copias, desarrollos históricos ni venv.
    source_root = cfg['root']
    source_files = sorted((source_root / 'platform_app').rglob('*.py')) if (source_root / 'platform_app').is_dir() else []
    source_files += [source_root / 'wsgi.py'] if (source_root / 'wsgi.py').is_file() else []
    if not source_files:
        record('Sintaxis Python', 'ERROR', 'No se localizaron archivos del código operativo')
    else:
        failures = []
        for source in source_files:
            try:
                ast.parse(source.read_bytes(), filename=str(source))
            except (SyntaxError, UnicodeError, OSError, ValueError) as e:
                failures.append(f'{source.relative_to(source_root)}: {e}')
        record('Sintaxis Python', 'ERROR' if failures else 'OK',
               '; '.join(failures[:10]) if failures else f'{len(source_files)} archivos analizados sin ejecutar código')
    # Prueba funcional aislada: compilar únicamente la función AST seleccionada.
    # No importa el paquete ni ejecuta instrucciones a nivel de módulo.
    validator = source_root / 'platform_app/participant_session_validation.py'
    if not validator.is_file():
        record('Validación ID participante (12 casos)', 'NO_COMPROBADO',
               'Módulo ausente en este entorno; no se ha ejecutado la prueba')
    else:
        try:
            tree = ast.parse(validator.read_bytes(), filename=str(validator))
            functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                         and n.name == 'valid_participant_id']
            if len(functions) != 1:
                raise ValueError('Se esperaba exactamente una función valid_participant_id')
            function = functions[0]
            # Solo se admite una función sencilla sin decoradores, anotaciones ni cierres.
            if function.decorator_list or function.args.defaults or function.args.kw_defaults:
                raise ValueError('Firma modificada: revisar manualmente antes de probar')
            isolated = ast.Module(body=[function], type_ignores=[])
            ast.fix_missing_locations(isolated)
            namespace = {'__builtins__': {'type': type, 'int': int}}
            exec(compile(isolated, str(validator), 'exec'), namespace)
            validate = namespace['valid_participant_id']
            cases = [(1, 1), (100, 100), (9223372036854775807, 9223372036854775807),
                     (0, None), (-1, None), (9223372036854775808, None),
                     ('123', None), (1.0, None), (True, None), (None, None),
                     (False, None), ([], None)]
            failures = [(repr(value), repr(expected), repr(validate(value)))
                        for value, expected in cases if validate(value) != expected]
            record('Validación ID participante (12 casos)', 'ERROR' if failures else 'OK',
                   f'{len(cases)-len(failures)}/{len(cases)} casos correctos' +
                   (f'; fallos={failures[:5]}' if failures else ''))
        except Exception as e:
            record('Validación ID participante (12 casos)', 'ERROR', repr(e))
    dbs = [cfg['root'] / 'central/plataforma.sqlite'] + sorted((cfg['root'] / 'entidades').glob('*/data/rifas.sqlite3'))
    if not (cfg['root'] / 'entidades').is_dir():
        record('Directorio de entidades', 'ERROR', 'No existe')
    if len(dbs) == 1:
        record('Bases de entidades', 'AVISO', 'No se encontraron bases de entidades')
    for path in dbs:
        name = str(path.relative_to(cfg['root']))
        if not path.is_file():
            record('SQLite ' + name, 'ERROR', 'No existe')
            continue
        try:
            ok, fks, tables = database_check(path)
            schema[name] = tables
            record('SQLite ' + name, 'OK' if ok and fks == 0 else 'ERROR',
                   f'integridad={ok}; violaciones_FK={fks}; tablas={len(tables)}')
        except Exception as e:
            record('SQLite ' + name, 'ERROR', repr(e))
    entities = {k: v for k, v in schema.items() if k.startswith('entidades/')}
    if len(entities) >= 2:
        names = sorted(entities)
        reference = entities[names[0]]
        diff = {}
        for name in names[1:]:
            a, b = set(reference), set(entities[name])
            missing = sorted(a - b)
            extra = sorted(b - a)
            changed = sorted(t for t in a & b if reference[t] != entities[name][t])
            if missing or extra or changed:
                diff[name] = {'solo_referencia': missing, 'solo_entidad': extra, 'estructura_distinta': changed}
        record('Comparación de esquemas entre entidades', 'AVISO' if diff else 'OK',
               json.dumps(diff, ensure_ascii=False) if diff else 'Sin diferencias')
    else:
        record('Comparación de esquemas entre entidades', 'NO_COMPROBADO', 'Se necesitan al menos dos entidades')
    for name in PENDING:
        record(name, 'NO_COMPROBADO', 'Prueba funcional todavía no implementada')

    # Huella de estructura (no de registros) para detectar cambios sin exponer datos.
    canonical = json.dumps(schema, sort_keys=True, ensure_ascii=False, default=str)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    record('Huella SHA256 de esquemas', 'INFO', fingerprint)
    if args.baseline:
        try:
            old = json.loads(args.baseline.read_text(encoding='utf-8'))
            if old.get('entorno') != args.entorno:
                record('Comparación con referencia', 'ERROR', 'La referencia pertenece a otro entorno')
            elif old.get('huella_esquemas') != fingerprint:
                record('Comparación con referencia', 'AVISO', 'La estructura difiere de la referencia')
            else:
                record('Comparación con referencia', 'OK', 'Estructura sin cambios')
        except Exception as e:
            record('Comparación con referencia', 'ERROR', repr(e))
    totals = {s: sum(c['estado'] == s for c in checks) for s in ('OK', 'ERROR', 'AVISO', 'NO_COMPROBADO', 'INFO')}
    report = {'fecha': now.isoformat(), 'entorno': args.entorno, 'version_verificador': VERSION,
              'checks': checks, 'resumen': totals, 'huella_esquemas': fingerprint, 'esquemas': schema}
    if not args.no_report:
        try:
            args.report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            dest = args.report_dir / f'{args.entorno}_{now.strftime("%Y%m%d_%H%M%S_%f")}.json'
            with dest.open('x', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            os.chmod(dest, 0o600)
            print('INFORME:', dest)
        except Exception as e:
            record('Guardar informe', 'ERROR', repr(e))
            totals['ERROR'] += 1
    print('RESUMEN:', json.dumps(totals, ensure_ascii=False))
    return 1 if totals['ERROR'] else 0

if __name__ == '__main__':
    sys.exit(main())
