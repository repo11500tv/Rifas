#!/usr/bin/env python3
"""Pruebas aisladas de límites OTP y entrega; sin Flask, SMTP ni datos reales."""
import argparse
import ast
import importlib.util
import pathlib
import sqlite3
import sys
import types
from unittest.mock import patch

NAMES = ['participant_ip_limits','participant_account_limits','participant_delivery_status','participant_safe_retry','participant_combined_guard','participant_code_invalidation','participant_smtp_outcome']
IMPORTS = {
 'participant_ip_limits': {'ipaddress','time'},
 'participant_account_limits': {'time'},
 'participant_delivery_status': set(),
 'participant_safe_retry': {'platform_app.participant_delivery_status'},
 'participant_combined_guard': {'platform_app.participant_ip_limits','platform_app.participant_account_limits'},
 'participant_code_invalidation': {'time'},
 'participant_smtp_outcome': {'smtplib'},
}
SCHEMA = '''
CREATE TABLE participants (id INTEGER PRIMARY KEY, email TEXT, active INTEGER, email_verified INTEGER);
CREATE TABLE participant_codes (id INTEGER PRIMARY KEY, participant_id INTEGER, channel TEXT, purpose TEXT, code_hash TEXT, expires_at INTEGER, used_at INTEGER, attempts INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE participant_code_deliveries (id INTEGER PRIMARY KEY, code_id INTEGER UNIQUE, status TEXT CHECK(status IN ('pending','accepted','failed','uncertain')), updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE participant_otp_requests (id INTEGER PRIMARY KEY, ip_address TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE participant_account_otp_requests (id INTEGER PRIMARY KEY, participant_id INTEGER NOT NULL, created_at INTEGER NOT NULL);
'''

def safe_load(folder):
    pkg = types.ModuleType('platform_app')
    pkg.__path__ = [str(folder)]
    sys.modules['platform_app'] = pkg
    mods = {}
    for name in NAMES:
        path = folder / (name + '.py')
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Import):
                assert all(a.name in IMPORTS[name] for a in node.names), f'Importación inesperada en {name}'
            elif isinstance(node, ast.ImportFrom):
                assert node.module in IMPORTS[name] and node.level == 0, f'Dependencia inesperada en {name}'
            elif isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                assert not node.decorator_list, f'Decorador inesperado en {name}'
            elif isinstance(node, ast.Assign):
                # Solo constantes y cadenas SQL; no llamadas de inicialización.
                assert isinstance(node.value, (ast.Constant,ast.BinOp)) and not any(isinstance(x,ast.Call) for x in ast.walk(node.value)), f'Inicialización inesperada en {name}'
            elif isinstance(node, ast.Expr) and isinstance(node.value,ast.Constant):
                pass
            else:
                raise AssertionError(f'Código de nivel superior inesperado en {name}: {type(node).__name__}')
        spec = importlib.util.spec_from_file_location('platform_app.'+name,path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    return mods

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default='/var/www/vhosts/dealfonso.com/rifas/platform_app')
    args=parser.parse_args()
    folder=pathlib.Path(args.source)
    mods=safe_load(folder)
    ip=mods['participant_ip_limits']; acct=mods['participant_account_limits']; guard=mods['participant_combined_guard']; delivery=mods['participant_delivery_status']; retry=mods['participant_safe_retry']; invalid=mods['participant_code_invalidation']; smtp=mods['participant_smtp_outcome']
    db=sqlite3.connect(':memory:'); db.executescript(SCHEMA)
    db.execute("INSERT INTO participants VALUES (1,'ficticio@example.invalid',1,1)")
    db.execute("INSERT INTO participants VALUES (2,'otro@example.invalid',1,1)")
    db.commit()
    checks=[]
    def check(label, condition):
        checks.append(bool(condition)); print(('OK' if condition else 'ERROR')+' | '+label)
    def rejects(fn,exception=ValueError):
        try: fn(); return False
        except exception: return True
    try:
        check('Normalización IPv6',ip.normalize_ip('2001:0db8::1')=='2001:db8::1')
        check('IP inválida rechazada',rejects(lambda: ip.normalize_ip('no-es-ip'),ValueError))
        check('ID booleano rechazado',rejects(lambda: acct.validate_participant_id(True)))
        check('ID negativo rechazado',rejects(lambda: acct.validate_participant_id(-1)))
        check('ID válido admitido',acct.validate_participant_id(1)==1)
        check('IP inicialmente permitida',ip.check_ip_limit(db,'192.0.2.10',10000))
        for _ in range(5): ip.record_ip_request(db,'192.0.2.10',10000)
        check('Límite IP 5/15 minutos',not ip.check_ip_limit(db,'192.0.2.10',10000))
        check('IP distinta independiente',ip.check_ip_limit(db,'192.0.2.11',10000))
        check('Ventana IP 15 minutos expira',ip.check_ip_limit(db,'192.0.2.10',10901))
        for _ in range(5): ip.record_ip_request(db,'192.0.2.10',10901)
        check('Límite IP 10/hora',not ip.check_ip_limit(db,'192.0.2.10',10901))
        check('Ventana IP hora expira',ip.check_ip_limit(db,'192.0.2.10',13602))
        check('Cuenta inicialmente permitida',acct.check_account_limit(db,1,10000))
        for _ in range(5): acct.record_account_request(db,1,10000)
        check('Límite cuenta 5/15 minutos',not acct.check_account_limit(db,1,10000))
        check('Otra cuenta independiente',acct.check_account_limit(db,2,10000))
        check('Ventana cuenta 15 minutos expira',acct.check_account_limit(db,1,10901))
        for _ in range(5): acct.record_account_request(db,1,10901)
        check('Límite cuenta 10/hora',not acct.check_account_limit(db,1,10901))
        check('Ventana cuenta hora expira',acct.check_account_limit(db,1,13602))
        for _ in range(10): acct.record_account_request(db,1,13602)
        check('Límite cuenta 20/24 horas',not acct.check_account_limit(db,1,13602))
        check('Ventana cuenta 24 horas expira',acct.check_account_limit(db,1,100000))
        db.execute('DELETE FROM participant_otp_requests');db.execute('DELETE FROM participant_account_otp_requests');db.commit()
        check('Control combinado admite solicitud',guard.register_combined_attempt(db,1,'198.51.100.20') is True)
        check('Control combinado registra IP',db.execute('SELECT COUNT(*) FROM participant_otp_requests').fetchone()[0]==1)
        check('Control combinado registra cuenta',db.execute('SELECT COUNT(*) FROM participant_account_otp_requests').fetchone()[0]==1)
        check('Control combinado rechaza IP inválida',rejects(lambda:guard.register_combined_attempt(db,1,'IP-MALA')))
        for _ in range(4): guard.register_combined_attempt(db,1,'198.51.100.20')
        before=db.execute('SELECT COUNT(*) FROM participant_account_otp_requests').fetchone()[0]
        check('Control combinado aplica límite',rejects(lambda:guard.register_combined_attempt(db,1,'198.51.100.20'),guard.CombinedLimitExceeded))
        check('Rechazo no registra intento parcial',db.execute('SELECT COUNT(*) FROM participant_account_otp_requests').fetchone()[0]==before and not db.in_transaction)
        db.execute("INSERT INTO participant_codes (id,participant_id,channel,purpose,code_hash,expires_at) VALUES (1,1,'email','login','ficticio',9999999999)")
        db.commit()
        delivery.create_delivery_record(db,1);db.commit()
        check('Entrega comienza pendiente',delivery.get_delivery_status(db,1)=='pending')
        check('No reintento con entrega pendiente',not retry.can_retry_after_failed_delivery(db,1,'email','login'))
        check('Entrega aceptada',delivery.update_delivery_status(db,1,'accepted'))
        check('Estado aceptado no se sobrescribe',not delivery.update_delivery_status(db,1,'failed'))
        check('Estado de entrega inválido rechazado',rejects(lambda:delivery.update_delivery_status(db,1,'inventado')))
        check('SMTP sin error aceptado',smtp.classify_smtp_result()=='accepted')
        check('SMTP error genérico incierto',smtp.classify_smtp_result(RuntimeError('simulado'))=='uncertain')
        check('Invalidación selectiva',invalid.invalidate_code(db,1,1,'email','login'))
        check('Invalidación no se repite',not invalid.invalidate_code(db,1,1,'email','login'))
        db.execute("INSERT INTO participant_codes (id,participant_id,channel,purpose,code_hash,expires_at,used_at) VALUES (2,1,'email','login','ficticio',9999999999,1)")
        delivery.create_delivery_record(db,2);delivery.update_delivery_status(db,2,'failed');db.commit()
        check('Reintento permitido tras fallo confirmado',retry.can_retry_after_failed_delivery(db,1,'email','login'))
        db.execute("INSERT INTO participant_codes (id,participant_id,channel,purpose,code_hash,expires_at,used_at) VALUES (3,1,'email','login','ficticio',9999999999,1)")
        delivery.create_delivery_record(db,3);delivery.update_delivery_status(db,3,'uncertain');db.commit()
        check('Reintento bloqueado ante resultado incierto',not retry.can_retry_after_failed_delivery(db,1,'email','login'))
    finally:
        db.close()
    errors=checks.count(False)
    print(f'RESUMEN AUTENTICACION AUXILIAR: {len(checks)-errors}/{len(checks)} correctas; {errors} errores')
    return int(bool(errors))
if __name__=='__main__':
    try: sys.exit(main())
    except Exception as e:
        print('ERROR | Excepción en pruebas aisladas:',repr(e));sys.exit(1)
