#!/usr/bin/env python3
"""Rifas Benéficas: verificador no destructivo v0.9 (Python 3.12)."""
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

VERSION = '1.0'
ROOT = Path('/var/www/vhosts/dealfonso.com/rifas')
CONFIG = {
    'produccion': {'service': 'rifas-platform', 'port': 8767, 'root': ROOT},
    'staging': {'service': 'rifas-pruebas', 'port': 8768, 'root': ROOT / 'staging/prueba_231'},
}
PENDING = ['Envío SMTP', 'Generación de PDF']


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



def purchase_schema_check(path):
    """Read-only structural checks; does not exercise Flask purchase routes."""
    required = {
        'credit_movements': {'participant_id', 'amount_cents', 'movement_type', 'reference'},
        'raffle_purchases': {'raffle_id', 'participant_id', 'quantity', 'unit_price_cents',
                             'total_cents', 'credit_movement_id'},
        'raffle_numbers': {'raffle_id', 'purchase_id', 'participant_id', 'number'},
    }
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=8)
    try:
        con.execute('PRAGMA query_only=ON')
        errors = []
        definitions = {}
        for table, fields in required.items():
            row = con.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',
                              ('table', table)).fetchone()
            if not row or not row[0]:
                errors.append(f'Falta tabla {table}')
                continue
            definitions[table] = row[0]
            quoted = '"' + table.replace('"', '""') + '"'
            cols = {r[1] for r in con.execute('PRAGMA table_info(' + quoted + ')')}
            missing = fields - cols
            if missing:
                errors.append(f'{table}: faltan columnas {sorted(missing)}')
        if errors:
            return False, '; '.join(errors)
        # Recreate the real table definitions in a disposable in-memory DB.
        # The tests exercise SQLite constraints, not Flask business logic.
        mem = sqlite3.connect(':memory:')
        try:
            mem.execute('PRAGMA foreign_keys=OFF')
            for table in ('credit_movements', 'raffle_purchases', 'raffle_numbers'):
                mem.execute(definitions[table])
            def reject(sql, params):
                try:
                    mem.execute(sql, params)
                except sqlite3.IntegrityError:
                    return True
                return False
            mem.execute("INSERT INTO credit_movements(participant_id,amount_cents,movement_type,reference) VALUES (1,1000,'topup','T1')")
            if not reject("INSERT INTO credit_movements(participant_id,amount_cents,movement_type,reference) VALUES (1,100,'topup','T1')", ()):
                errors.append('Se permite duplicar referencia de crédito')
            if not reject("INSERT INTO credit_movements(participant_id,amount_cents,movement_type,reference) VALUES (1,0,'topup','ZERO')", ()):
                errors.append('Se permite movimiento de importe cero')
            mem.execute("INSERT INTO credit_movements(participant_id,amount_cents,movement_type,reference) VALUES (1,-300,'consume','BUY1')")
            mem.execute("INSERT INTO raffle_purchases(raffle_id,participant_id,quantity,unit_price_cents,total_cents,credit_movement_id) VALUES (1,1,3,100,300,2)")
            if not reject("INSERT INTO raffle_purchases(raffle_id,participant_id,quantity,unit_price_cents,total_cents,credit_movement_id) VALUES (1,1,2,100,300,1)", ()):
                errors.append('Se permite total distinto de cantidad por precio')
            if not reject("INSERT INTO raffle_purchases(raffle_id,participant_id,quantity,unit_price_cents,total_cents,credit_movement_id) VALUES (1,1,1,100,100,2)", ()):
                errors.append('Se permite reutilizar movimiento de compra')
            mem.execute("INSERT INTO raffle_numbers(raffle_id,purchase_id,participant_id,number) VALUES (1,1,1,7)")
            if not reject("INSERT INTO raffle_numbers(raffle_id,purchase_id,participant_id,number) VALUES (1,1,1,7)", ()):
                errors.append('Se permite duplicar número del sorteo')
            mem.commit()
            # Verify rollback of a multi-table operation after a UNIQUE violation.
            before = [mem.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
                      for t in ('credit_movements', 'raffle_purchases', 'raffle_numbers')]
            mem.execute('BEGIN IMMEDIATE')
            try:
                mem.execute("INSERT INTO credit_movements(participant_id,amount_cents,movement_type,reference) VALUES (1,-100,'consume','ROLLBACK1')")
                mem.execute("INSERT INTO raffle_purchases(raffle_id,participant_id,quantity,unit_price_cents,total_cents,credit_movement_id) VALUES (1,1,1,100,100,3)")
                mem.execute("INSERT INTO raffle_numbers(raffle_id,purchase_id,participant_id,number) VALUES (1,2,1,7)")
                errors.append('La venta duplicada no provocó error de integridad')
            except sqlite3.IntegrityError:
                pass
            finally:
                mem.rollback()
            after = [mem.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0]
                     for t in ('credit_movements', 'raffle_purchases', 'raffle_numbers')]
            if before != after:
                errors.append('Rollback incompleto en simulación aislada')
        finally:
            mem.close()
        return not errors, ('; '.join(errors) if errors else
                            '6 restricciones/transacciones comprobadas con esquema real en SQLite aislado; rutas Flask no ejecutadas')
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
    # Batería OTP aislada en otro proceso, SQLite en memoria, sin SMTP ni acceso a datos reales.
    # Antes de ejecutarla, exigir que el módulo OTP solo importe librerías estándar conocidas
    # y que no contenga instrucciones de nivel superior con efectos secundarios.
    otp_module = source_root / 'platform_app/participant_otp.py'
    otp_tests = ROOT / 'rifas-otp-tests-0.1.py'
    if not otp_module.is_file() or not otp_tests.is_file():
        record('Motor OTP (21 casos)', 'NO_COMPROBADO',
               'Falta el módulo OTP o el archivo rifas-otp-tests-0.1.py')
    else:
        try:
            tree = ast.parse(otp_module.read_bytes(), filename=str(otp_module))
            allowed_imports = {'hashlib', 'hmac', 'secrets', 'time'}
            for node in tree.body:
                if isinstance(node, ast.Import):
                    if any(a.name not in allowed_imports for a in node.names):
                        raise ValueError('Importación nueva en OTP: requiere revisión de seguridad')
                elif isinstance(node, ast.ImportFrom):
                    raise ValueError('Importación desde otro módulo: requiere revisión de seguridad')
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.decorator_list:
                        raise ValueError('Decorador en OTP: requiere revisión de seguridad')
                elif isinstance(node, ast.Assign):
                    if not isinstance(node.value, ast.Constant):
                        raise ValueError('Inicialización ejecutable en OTP: requiere revisión de seguridad')
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                    pass  # Docstring del módulo
                else:
                    raise ValueError('Código nuevo de nivel superior en OTP: requiere revisión de seguridad')
            result = subprocess.run(
                [sys.executable, '-B', str(otp_tests), '--module', str(otp_module)],
                capture_output=True, text=True, timeout=20, check=False,
                cwd='/tmp', env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
            )
            success = result.returncode == 0 and 'RESUMEN OTP: 21/21 correctas; 0 errores' in result.stdout
            detail = next((line for line in result.stdout.splitlines() if line.startswith('RESUMEN OTP:')), '')
            if not detail:
                detail = (result.stderr or result.stdout or 'Sin resultado')[-350:]
            record('Motor OTP (21 casos)', 'OK' if success else 'ERROR', detail)
        except Exception as e:
            record('Motor OTP (21 casos)', 'ERROR', repr(e))
    # Pruebas auxiliares aisladas de autenticación: proceso separado y SQLite en memoria.
    auth_tests = ROOT / 'rifas-auth-tests-0.2.py'
    auth_source = source_root / 'platform_app'
    if not auth_tests.is_file() or not auth_source.is_dir():
        record('Seguridad auxiliar de autenticación', 'NO_COMPROBADO',
               'Falta rifas-auth-tests-0.2.py o el directorio platform_app')
    else:
        try:
            result = subprocess.run(
                [sys.executable, '-B', str(auth_tests), '--source', str(auth_source)],
                capture_output=True, text=True, timeout=20, check=False,
                cwd='/tmp', env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
            )
            detail = next((line for line in result.stdout.splitlines()
                           if line.startswith('RESUMEN AUTENTICACION AUXILIAR:')), '')
            success = result.returncode == 0 and detail and '; 0 errores' in detail
            if not detail:
                detail = (result.stderr or result.stdout or 'Sin resultado')[-450:]
            record('Seguridad auxiliar de autenticación', 'OK' if success else 'ERROR', detail)
        except Exception as e:
            record('Seguridad auxiliar de autenticación', 'ERROR', repr(e))
    # Integración de registro/acceso: aislamiento SQLite en memoria y correo simulado.
    integration_tests = ROOT / 'rifas-integration-tests-0.1.py'
    if not integration_tests.is_file() or not auth_source.is_dir():
        record('Integración de registro y acceso OTP', 'NO_COMPROBADO',
               'Falta rifas-integration-tests-0.1.py o platform_app')
    else:
        try:
            result = subprocess.run(
                [sys.executable, '-B', str(integration_tests), '--source', str(auth_source)],
                capture_output=True, text=True, timeout=25, check=False,
                cwd='/tmp', env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'},
            )
            detail = next((line for line in result.stdout.splitlines()
                           if line.startswith('RESUMEN INTEGRACION OTP:')), '')
            success = result.returncode == 0 and bool(detail) and '; 0 errores' in detail
            if not success:
                detail = (result.stdout + '\n' + result.stderr)[-1500:]
            record('Integración de registro y acceso OTP', 'OK' if success else 'ERROR', detail)
        except Exception as e:
            record('Integración de registro y acceso OTP', 'ERROR', repr(e))
    # Pruebas funcionales Flask aisladas: Python del venv y SQLite temporal.
    # El auxiliar debe mantener su cortafuegos de imports y acceso a datos reales.
    purchase_tests = ROOT / 'rifas-purchase-credit-tests-0.1.py'
    purchase_python = ROOT / 'venv/bin/python'
    if not purchase_tests.is_file() or not purchase_python.is_file() or not auth_source.is_dir():
        record('Compras directas y créditos (21 casos)', 'NO_COMPROBADO',
               'Falta el módulo de pruebas, Python del entorno virtual o platform_app')
    else:
        try:
            result = subprocess.run(
                [str(purchase_python), '-B', str(purchase_tests), '--source', str(auth_source)],
                capture_output=True, text=True, timeout=35, check=False,
                cwd='/tmp', env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1',
                                 'PYTHONNOUSERSITE': '1'},
            )
            detail = next((line for line in result.stdout.splitlines()
                           if line.startswith('RESUMEN COMPRAS Y CREDITOS:')), '')
            success = (result.returncode == 0 and
                       detail == 'RESUMEN COMPRAS Y CREDITOS: 21 casos; 0 errores')
            if not success:
                detail = (result.stdout + '\n' + result.stderr)[-1500:] or 'Sin resultado'
            record('Compras directas y créditos (21 casos)', 'OK' if success else 'ERROR', detail)
        except Exception as e:
            record('Compras directas y créditos (21 casos)', 'ERROR', repr(e))
    # Verificación aislada de los decoradores reales de permisos con SQLite temporal.
    permissions_tests = ROOT / 'rifas-permissions-tests-0.1.py'
    if not permissions_tests.is_file() or not purchase_python.is_file() or not auth_source.is_dir():
        record('Permisos y aislamiento funcional entre entidades (21 casos)', 'NO_COMPROBADO',
               'Falta el módulo de permisos, Python del entorno virtual o platform_app')
    else:
        try:
            result = subprocess.run(
                [str(purchase_python), '-B', str(permissions_tests), '--source', str(auth_source)],
                capture_output=True, text=True, timeout=35, check=False,
                cwd='/tmp', env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1',
                                 'PYTHONNOUSERSITE': '1'},
            )
            detail = next((line for line in result.stdout.splitlines()
                           if line.startswith('RESUMEN PERMISOS:')), '')
            success = (result.returncode == 0 and
                       detail == 'RESUMEN PERMISOS: 21 casos; 0 errores')
            if not success:
                detail = (result.stdout + '\n' + result.stderr)[-1500:] or 'Sin resultado'
            record('Permisos y aislamiento funcional entre entidades (21 casos)',
                   'OK' if success else 'ERROR', detail)
        except Exception as e:
            record('Permisos y aislamiento funcional entre entidades (21 casos)', 'ERROR', repr(e))
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
    for path in dbs[1:]:
        if not path.is_file():
            continue
        name = str(path.relative_to(cfg['root']))
        try:
            passed, detail = purchase_schema_check(path)
            record('Restricciones de compra y crédito ' + name,
                   'OK' if passed else 'ERROR', detail)
        except Exception as e:
            record('Restricciones de compra y crédito ' + name, 'ERROR', repr(e))
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
