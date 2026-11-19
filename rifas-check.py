#!/usr/bin/env python3
"""Rifas Benéficas: diagnóstico no destructivo de producción y staging."""
import argparse
import datetime as dt
import hashlib
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path('/var/www/vhosts/dealfonso.com/rifas')
CONFIG = {
    'produccion': {'service': 'rifas-platform', 'port': 8767, 'root': ROOT, 'dbroot': ROOT},
    'staging': {'service': 'rifas-pruebas', 'port': 8768, 'root': ROOT / 'staging/prueba_231', 'dbroot': ROOT / 'staging/prueba_231'},
}

def check_http(port):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        conn.request('GET', '/')
        response = conn.getresponse()
        code, location = response.status, response.getheader('Location')
        response.read(4096)
        return code, location
    finally:
        conn.close()

def sqlite_integrity(path):
    uri = path.resolve().as_uri() + '?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=3)
    try:
        con.execute('PRAGMA query_only=ON')
        result = [r[0] for r in con.execute('PRAGMA integrity_check').fetchall()]
        tables = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
        fk = con.execute('PRAGMA foreign_key_check').fetchall()
        return result == ['ok'], tables, len(fk)
    finally:
        con.close()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('entorno', choices=CONFIG)
    args = ap.parse_args()
    cfg = CONFIG[args.entorno]
    checks = []
    def record(name, status, detail):
        checks.append({'prueba': name, 'estado': status, 'detalle': str(detail)})
        print(f'{status:>12}  {name}: {detail}')

    print(f'RIFAS CHECK 0.1 | {args.entorno} | {dt.datetime.now().astimezone().isoformat()}')
    try:
        result = subprocess.run(['systemctl', 'is-active', cfg['service']], capture_output=True, text=True, timeout=5)
        record('Servicio ' + cfg['service'], 'OK' if result.stdout.strip() == 'active' else 'ERROR', result.stdout.strip() or result.stderr.strip())
    except Exception as e:
        record('Servicio', 'ERROR', type(e).__name__)
    try:
        code, loc = check_http(cfg['port'])
        record('HTTP local', 'OK' if (code, loc) == (302, '/login') else 'ERROR', f'HTTP {code}; Location={loc}')
    except Exception as e:
        record('HTTP local', 'ERROR', type(e).__name__ + ': ' + str(e))
    wsgi = cfg['root'] / 'wsgi.py'
    record('wsgi.py', 'OK' if wsgi.is_file() else 'ERROR', str(wsgi))
    if wsgi.is_file():
        record('SHA256 wsgi.py', 'INFO', hashlib.sha256(wsgi.read_bytes()).hexdigest())
    dbroot = cfg['dbroot']
    dbs = [dbroot / 'central/plataforma.sqlite'] + sorted((dbroot / 'entidades').glob('*/data/rifas.sqlite3'))
    schemas = {}
    for path in dbs:
        label = str(path.relative_to(dbroot))
        if not path.is_file():
            record('SQLite ' + label, 'ERROR', 'No existe')
            continue
        try:
            ok, tables, fks = sqlite_integrity(path)
            record('SQLite ' + label, 'OK' if ok and fks == 0 else 'ERROR', f'integridad={ok}; violaciones FK={fks}; tablas={len(tables)}')
            schemas[label] = tables
        except Exception as e:
            record('SQLite ' + label, 'ERROR', type(e).__name__ + ': ' + str(e))
    entity_schemas = {k: set(v) for k,v in schemas.items() if k.startswith('entidades/')}
    if len(entity_schemas) >= 2:
        baseline = next(iter(entity_schemas.values()))
        differences = {k: sorted(v ^ baseline) for k,v in entity_schemas.items() if v != baseline}
        record('Comparación de tablas entre entidades', 'AVISO' if differences else 'OK', differences if differences else 'Sin diferencias')
    elif len(entity_schemas) < 2:
        record('Comparación de tablas entre entidades', 'NO_COMPROBADO', 'Se necesitan al menos dos entidades')
    report = {'fecha': dt.datetime.now().astimezone().isoformat(), 'entorno': args.entorno, 'version_verificador': '0.1', 'checks': checks, 'tablas': schemas}
    # Por defecto solo lectura: no se crean archivos en el servidor.
    totals = {s: sum(c['estado'] == s for c in checks) for s in ('OK','ERROR','AVISO','NO_COMPROBADO','INFO')}
    print('\nRESUMEN:', json.dumps(totals, ensure_ascii=False))
    print('AVISO: comprobaciones funcionales de registro, reservas, créditos, SMTP y PDF aún NO IMPLEMENTADAS.')
    return 1 if totals['ERROR'] else 0

if __name__ == '__main__':
    sys.exit(main())
