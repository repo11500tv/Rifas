#!/usr/bin/env python3
"""Pruebas aisladas del motor OTP de Rifas Benéficas. No modifica producción."""
import argparse
import importlib.util
import pathlib
import sqlite3
import sys
from unittest.mock import patch

SCHEMA = '''CREATE TABLE participant_codes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 participant_id INTEGER NOT NULL,
 channel TEXT NOT NULL,
 purpose TEXT NOT NULL,
 code_hash TEXT NOT NULL,
 expires_at INTEGER NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,
 used_at INTEGER
)'''
SECRET = b'clave-ficticia-exclusiva-para-pruebas'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--module', default='/var/www/vhosts/dealfonso.com/rifas/platform_app/participant_otp.py')
    args = parser.parse_args()
    path = pathlib.Path(args.module)
    if not path.is_file() or path.name != 'participant_otp.py':
        parser.error('No se encuentra el módulo OTP esperado')
    spec = importlib.util.spec_from_file_location('rifas_otp_under_test', path)
    otp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(otp)
    db = sqlite3.connect(':memory:')
    db.execute(SCHEMA)
    results = []

    def check(name, condition):
        results.append((name, bool(condition)))
        print(('OK' if condition else 'ERROR') + ' | ' + name)

    try:
        code = otp.generate_code()
        check('Formato de 6 dígitos ASCII', isinstance(code, str) and len(code) == 6 and code.isascii() and code.isdigit())
        check('HMAC estable', otp.code_digest(SECRET, 1, 'email', 'login', '123456') == otp.code_digest(SECRET, 1, 'email', 'login', '123456'))
        check('HMAC vinculado al participante', otp.code_digest(SECRET, 1, 'email', 'login', '123456') != otp.code_digest(SECRET, 2, 'email', 'login', '123456'))
        check('HMAC vinculado a la finalidad', otp.code_digest(SECRET, 1, 'email', 'login', '123456') != otp.code_digest(SECRET, 1, 'email', 'register', '123456'))
        check('HMAC vinculado al canal', otp.code_digest(SECRET, 1, 'email', 'login', '123456') != otp.code_digest(SECRET, 1, 'sms', 'login', '123456'))
        for name, channel, purpose in [('Canal inválido', 'fax', 'login'), ('Finalidad inválida', 'email', 'other')]:
            try:
                otp.create_code(db, SECRET, 1, channel, purpose)
                rejected = False
            except ValueError:
                rejected = True
            check(name + ' rechazado', rejected)
        with patch.object(otp.time, 'time', return_value=1000000):
            code1 = otp.create_code(db, SECRET, 1, 'email', 'login')
            row = db.execute('SELECT code_hash, expires_at, attempts FROM participant_codes ORDER BY id DESC LIMIT 1').fetchone()
            check('Caducidad establecida en 300 segundos', row[1] == 1000300)
            check('Código no guardado en claro', row[0] != code1 and len(row[0]) == 64)
            check('Código válido aceptado', otp.verify_code(db, SECRET, 1, 'email', 'login', code1))
            check('Reutilización rechazada', not otp.verify_code(db, SECRET, 1, 'email', 'login', code1))
            code2 = otp.create_code(db, SECRET, 1, 'email', 'login')
            check('Otro participante no puede usar el código', not otp.verify_code(db, SECRET, 2, 'email', 'login', code2))
            check('Finalidad distinta no acepta el código', not otp.verify_code(db, SECRET, 1, 'email', 'register', code2))
            check('Canal distinto no acepta el código', not otp.verify_code(db, SECRET, 1, 'sms', 'login', code2))
            check('Formato incorrecto rechazado', all(not otp.verify_code(db, SECRET, 1, 'email', 'login', v) for v in ('12345', '1234567', 'abcdef', '１２３４５６', None, 123456)))
            code3 = otp.create_code(db, SECRET, 1, 'email', 'login')
            check('Nuevo código invalida anterior', not otp.verify_code(db, SECRET, 1, 'email', 'login', code2))
            check('Nuevo código es válido', otp.verify_code(db, SECRET, 1, 'email', 'login', code3))
            code4 = otp.create_code(db, SECRET, 1, 'email', 'login')
            for _ in range(5):
                otp.verify_code(db, SECRET, 1, 'email', 'login', 'xxxxxx')
            # Las entradas con formato inválido no incrementan intentos; usar código válido pero incorrecto.
            wrong = '000000' if code4 != '000000' else '999999'
            for _ in range(5):
                otp.verify_code(db, SECRET, 1, 'email', 'login', wrong)
            check('Cinco intentos fallidos bloquean el código', not otp.verify_code(db, SECRET, 1, 'email', 'login', code4))
            code5 = otp.create_code(db, SECRET, 1, 'email', 'login')
        with patch.object(otp.time, 'time', return_value=1000300):
            check('Caducidad exacta rechazada', not otp.verify_code(db, SECRET, 1, 'email', 'login', code5))
        with patch.object(otp.time, 'time', return_value=1000299):
            check('Código anterior a caducidad aceptado', otp.verify_code(db, SECRET, 1, 'email', 'login', code5))
        with patch.object(otp.time, 'time', return_value=1000000):
            code_id, code6 = otp.create_code_with_id(db, SECRET, 3, 'sms', 'recovery')
            check('Creación devuelve ID y código verificables', isinstance(code_id, int) and otp.verify_code(db, SECRET, 3, 'sms', 'recovery', code6))
    finally:
        db.close()
    failed = sum(not ok for _, ok in results)
    print(f'RESUMEN OTP: {len(results) - failed}/{len(results)} correctas; {failed} errores')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
