#!/usr/bin/env python3
"""Pruebas aisladas del servicio OTP; sin SMTP, Flask ni SQLite de producción."""
import argparse
import ast
import importlib.util
from pathlib import Path
import sqlite3
import smtplib
import sys
import types
from unittest.mock import patch

BASE = Path(__file__).resolve().parent
SCHEMA = '''
CREATE TABLE participants (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL, active INTEGER NOT NULL, email_verified INTEGER NOT NULL);
CREATE TABLE participant_codes (id INTEGER PRIMARY KEY, participant_id INTEGER NOT NULL, channel TEXT NOT NULL, purpose TEXT NOT NULL, code_hash TEXT NOT NULL, expires_at INTEGER NOT NULL, used_at INTEGER, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE participant_code_deliveries (id INTEGER PRIMARY KEY, code_id INTEGER NOT NULL UNIQUE, status TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE participant_otp_requests (id INTEGER PRIMARY KEY, ip_address TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE participant_account_otp_requests (id INTEGER PRIMARY KEY, participant_id INTEGER NOT NULL, created_at INTEGER NOT NULL);
'''
ALLOW = {
 'participant_otp': {'hashlib','hmac','secrets','time'},
 'participant_otp_limits': {'time'},
 'participant_ip_limits': {'ipaddress','time'},
 'participant_account_limits': {'time'},
 'participant_delivery_status': set(),
 'participant_safe_retry': {'platform_app.participant_delivery_status'},
 'participant_combined_guard': {'platform_app.participant_ip_limits','platform_app.participant_account_limits'},
 'participant_code_invalidation': {'time'},
 'participant_smtp_outcome': {'smtplib'},
 'participant_registration_service': {'platform_app.participant_otp','platform_app.participant_code_invalidation','platform_app.participant_delivery_status','platform_app.participant_smtp_outcome','platform_app.participant_combined_guard','platform_app.participant_otp_limits','platform_app.participant_safe_retry','platform_app.participant_registration_email'},
 'participant_login_service_v2': {'platform_app.participant_otp','platform_app.participant_code_invalidation','platform_app.participant_delivery_status','platform_app.participant_smtp_outcome','platform_app.participant_combined_guard','platform_app.participant_otp_limits','platform_app.participant_safe_retry','platform_app.participant_email_otp'},
}
ORDER = ['participant_otp','participant_ip_limits','participant_account_limits','participant_delivery_status','participant_safe_retry','participant_combined_guard','participant_code_invalidation','participant_smtp_outcome','participant_otp_limits','participant_registration_service','participant_login_service_v2']

def safe_load(folder):
    pkg = types.ModuleType('platform_app'); pkg.__path__ = []
    sys.modules['platform_app'] = pkg
    # Cortafuegos: los módulos de correo son exclusivamente simuladores, jamás se importan.
    for name, fn in [('participant_registration_email','send_registration_code'),('participant_email_otp','send_login_code')]:
        stub = types.ModuleType('platform_app.'+name)
        def forbidden(*args, **kwargs):
            raise AssertionError('Envío no simulado: operación prohibida')
        setattr(stub, fn, forbidden)
        sys.modules[stub.__name__] = stub
    modules = {}
    for name in ORDER:
        path = folder / (name+'.py')
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Import):
                assert all(alias.name in ALLOW[name] for alias in node.names), f'Importación inesperada en {name}'
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module in ALLOW[name], f'Dependencia inesperada en {name}'
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assert not node.decorator_list, f'Decorador inesperado en {name}'
            elif isinstance(node, ast.Assign):
                assert isinstance(node.value,(ast.Constant,ast.BinOp)) and not any(isinstance(x,ast.Call) for x in ast.walk(node.value)), f'Inicialización inesperada en {name}'
            elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant):
                pass
            else:
                raise AssertionError(f'Código de nivel superior inesperado en {name}: {type(node).__name__}')
        spec = importlib.util.spec_from_file_location('platform_app.'+name,path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        modules[name] = mod
    return modules

def database(verified):
    db = sqlite3.connect(':memory:')
    db.executescript(SCHEMA)
    db.execute('INSERT INTO participants VALUES (1,?,?,?,1,?)',('Ficticio','ficticio@example.invalid','600000001',int(verified)))
    db.commit()
    return db

def state(db):
    return db.execute('SELECT c.id,c.used_at,d.status,c.channel,c.purpose FROM participant_codes c JOIN participant_code_deliveries d ON d.code_id=c.id ORDER BY c.id').fetchall()

def run(folder):
    mods = safe_load(folder)
    checks = []
    def check(name, cond):
        ok = bool(cond); checks.append(ok)
        print(('OK' if ok else 'ERROR')+' | '+name)
    def expect(exc, fn):
        try: fn(); return False
        except exc: return True
    otp=mods['participant_otp']
    for purpose, service_name, fn_name, exception_name in [
        ('register','participant_registration_service','request_registration_email_code','RegistrationResendTooSoon'),
        ('login','participant_login_service_v2','request_login_email_code','LoginResendTooSoon')]:
        svc=mods[service_name]; request=getattr(svc,fn_name); resend=getattr(svc,exception_name)
        def invoke(db, ip='192.0.2.10'): return request(db,b'test-secret',1,ip)
        def patched(sender): return patch.object(svc,'send_registration_code' if purpose=='register' else 'send_login_code',side_effect=sender)
        with database(purpose=='login') as db:
            with patched(lambda *a: True):
                check(purpose+' primer envío',invoke(db) is True)
                rows=state(db)
                check(purpose+' código aceptado',len(rows)==1 and rows[0][1] is None and rows[0][2]=='accepted' and rows[0][4]==purpose)
                check(purpose+' sin transacción pendiente',not db.in_transaction)
                check(purpose+' reenvío bloqueado',expect(resend,lambda:invoke(db)))
                check(purpose+' intento de reenvío contabilizado',db.execute('SELECT COUNT(*) FROM participant_account_otp_requests').fetchone()[0]==2)
                check(purpose+' sin código adicional',len(state(db))==1)
        with database(purpose=='login') as db:
            def rejected(*args): raise smtplib.SMTPRecipientsRefused({'ficticio@example.invalid':(550,b'rejected')})
            with patched(rejected):
                check(purpose+' rechazo SMTP propagado',expect(smtplib.SMTPRecipientsRefused,lambda:invoke(db)))
            rows=state(db)
            check(purpose+' rechazo clasificado failed',len(rows)==1 and rows[0][2]=='failed')
            check(purpose+' código rechazado invalidado',len(rows)==1 and rows[0][1] is not None)
            check(purpose+' rechazo sin transacción pendiente',not db.in_transaction)
            with patched(lambda *a: True):
                check(purpose+' reintento tras rechazo confirmado',invoke(db) is True)
                rows=state(db)
                check(purpose+' nuevo código tras rechazo',len(rows)==2 and rows[1][2]=='accepted' and rows[1][1] is None)
        with database(purpose=='login') as db:
            def uncertain(*args): raise OSError('simulación de pérdida de conexión')
            with patched(uncertain):
                check(purpose+' fallo incierto propagado',expect(OSError,lambda:invoke(db)))
            rows=state(db)
            check(purpose+' fallo clasificado uncertain',len(rows)==1 and rows[0][2]=='uncertain')
            check(purpose+' código incierto invalidado',len(rows)==1 and rows[0][1] is not None)
            with patched(lambda *a: True):
                check(purpose+' reintento incierto bloqueado',expect(resend,lambda:invoke(db)))
            check(purpose+' fallo incierto sin transacción pendiente',not db.in_transaction)
        with database(purpose!='login') as db:  # registro ya verificado; login aún no verificado
            with patched(lambda *a: True):
                check(purpose+' estado participante inválido',expect(ValueError,lambda:invoke(db)))
            check(purpose+' sin código para cuenta no habilitada',len(state(db))==0)
            check(purpose+' intento de cuenta no habilitada contabilizado',db.execute('SELECT COUNT(*) FROM participant_account_otp_requests').fetchone()[0]==1)
        with database(purpose=='login') as db:
            db.execute('UPDATE participants SET active=0 WHERE id=1');db.commit()
            with patched(lambda *a: True):
                check(purpose+' cuenta inactiva rechazada',expect(ValueError,lambda:invoke(db)))
            check(purpose+' cuenta inactiva sin código',len(state(db))==0)
        with database(purpose=='login') as db:
            with patched(lambda *a: True):
                for _ in range(5):
                    try: invoke(db)
                    except resend: pass
                guard=mods['participant_combined_guard']
                check(purpose+' límite combinado tras cinco solicitudes',expect(guard.CombinedLimitExceeded,lambda:invoke(db)))
                check(purpose+' límite sin sexto registro',db.execute('SELECT COUNT(*) FROM participant_account_otp_requests').fetchone()[0]==5)
    total=len(checks); good=sum(checks)
    print(f'RESUMEN INTEGRACION OTP: {good}/{total} correctas; {total-good} errores')
    return 0 if total and good==total else 1

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True)
    args=ap.parse_args()
    try: sys.exit(run(Path(args.source)))
    except Exception as e:
        print('ERROR | Excepción en pruebas integradas:',repr(e))
        sys.exit(1)
