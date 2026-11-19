#!/usr/bin/env python3
"""Pruebas SMTP aisladas de Rifas Benéficas. Sin importación de platform_app ni red.

Uso: python rifas-smtp-tests-0.1.py --source /ruta/a/platform_app
"""
import argparse
import ast
import ipaddress
from pathlib import Path
import re
import smtplib
import socket
import ssl
from email.utils import parseaddr
from unittest.mock import Mock, patch


def extract(source, names, namespace):
    """Compila únicamente las definiciones solicitadas, nunca el módulo completo."""
    tree = ast.parse(source.read_bytes(), filename=str(source))
    for name in names:
        matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name]
        if len(matches) != 1:
            raise ValueError(f'{source.name}: se esperaba exactamente una definición {name}')
        node = matches[0]
        if node.decorator_list:
            raise ValueError(f'{source.name}: decoradores inesperados en {name}')
        module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        exec(compile(module, str(source), 'exec'), namespace)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    required = ('smtp_validation.py', 'smtp_network.py', 'smtp_transport.py')
    for name in required:
        if not (source / name).is_file():
            parser.error(f'Falta {name}')

    # Namespace controlado: no importamos platform_app ni ejecutamos código a nivel de módulo.
    ns = {'__name__': 'rifas_smtp_isolated', 'ipaddress': ipaddress, 're': re,
          'parseaddr': parseaddr, 'socket': socket, 'ssl': ssl, 'smtplib': smtplib}
    extract(source / 'smtp_validation.py', ['valid_hostname', 'valid_email', 'validate_smtp'], ns)
    extract(source / 'smtp_network.py', ['SMTPDestinationError', 'public_ip', 'resolve_smtp_host'], ns)
    extract(source / 'smtp_transport.py',
            ['SecureSMTPMixin', 'SecureSMTPSSL', 'SecureSMTPSTARTTLS', 'open_secure_smtp'], ns)

    cases = 0
    errors = 0

    def check(label, condition):
        nonlocal cases, errors
        cases += 1
        if not condition:
            errors += 1
        print(('OK' if condition else 'ERROR') + ' | ' + label)

    # Cortafuegos: toda resolución o conexión real falla explícitamente.
    def forbidden(*_args, **_kwargs):
        raise AssertionError('Intento de conexión o DNS real durante las pruebas SMTP')

    with patch.object(socket, 'getaddrinfo', side_effect=forbidden), \
         patch.object(socket, 'create_connection', side_effect=forbidden), \
         patch.object(socket.socket, 'connect', side_effect=forbidden), \
         patch.object(socket.socket, 'connect_ex', side_effect=forbidden):
        hostname_cases = {
            'smtp.example.com': True, 'mail.dealfonso.com': True,
            'localhost': False, '127.0.0.1': False, 'servidor_invalido.com': False,
        }
        for host, expected in hostname_cases.items():
            check('Hostname ' + host, ns['valid_hostname'](host) is expected)

        ip_cases = {
            '8.8.8.8': True, '1.1.1.1': True,
            '127.0.0.1': False, '192.168.1.1': False, '10.0.0.1': False,
            '172.16.0.1': False, '169.254.1.1': False, '0.0.0.0': False,
            '224.0.0.1': False, '::1': False, 'fc00::1': False, 'fe80::1': False,
        }
        for address, expected in ip_cases.items():
            check('IP ' + address, ns['public_ip'](address) is expected)

        def records(*ips):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 0)) for ip in ips]

        dns_cases = [
            ('DNS público', records('8.8.8.8', '1.1.1.1'), True),
            ('DNS público y privado', records('8.8.8.8', '192.168.1.1'), False),
            ('DNS vacío', [], False),
            ('DNS error', socket.gaierror('Fallo DNS simulado'), False),
        ]
        for label, answer, expected in dns_cases:
            with patch.object(socket, 'getaddrinfo', side_effect=answer if isinstance(answer, Exception) else None,
                              return_value=None if isinstance(answer, Exception) else answer):
                try:
                    ns['resolve_smtp_host']('smtp.example.com')
                    accepted = True
                except ns['SMTPDestinationError']:
                    accepted = False
                check(label, accepted is expected)

        original_ssl = ns['SecureSMTPSSL']
        original_tls = ns['SecureSMTPSTARTTLS']
        try:
            ssl_mock = Mock()
            ns['SecureSMTPSSL'] = ssl_mock
            connection = ns['open_secure_smtp']('smtp.example.com', 465, 'ssl')
            check('SSL puerto 465', connection is ssl_mock.return_value and
                  ssl_mock.call_args.args == ('smtp.example.com', 465))

            tls_mock = Mock()
            ns['SecureSMTPSTARTTLS'] = tls_mock
            connection = ns['open_secure_smtp']('smtp.example.com', 587, 'starttls')
            check('STARTTLS puerto 587', connection is tls_mock.return_value and
                  tls_mock.return_value.starttls_required.call_count == 1)

            for security, port in [('ssl', 587), ('starttls', 465), ('none', 25), ('ssl', 25)]:
                try:
                    ns['open_secure_smtp']('smtp.example.com', port, security)
                    rejected = False
                except ValueError:
                    rejected = True
                check(f'Rechazo {security}/{port}', rejected)

            tls_mock.reset_mock()
            tls_mock.return_value.starttls_required.side_effect = RuntimeError('Fallo TLS simulado')
            try:
                ns['open_secure_smtp']('smtp.example.com', 587, 'starttls')
            except RuntimeError:
                pass
            check('Cierre ante fallo STARTTLS', tls_mock.return_value.close.call_count == 1)
        finally:
            ns['SecureSMTPSSL'] = original_ssl
            ns['SecureSMTPSTARTTLS'] = original_tls

        with patch.object(ssl, 'create_default_context', return_value=object()):
            smtp = object.__new__(original_tls)
            smtp.ehlo = Mock()
            smtp.has_extn = Mock(return_value=False)
            smtp.starttls = Mock()
            try:
                smtp.starttls_required()
                rejected = False
            except smtplib.SMTPNotSupportedError:
                rejected = True
            check('Rechazo sin STARTTLS', rejected)
            check('No inicia TLS si no está disponible', smtp.starttls.call_count == 0)
            smtp.ehlo.reset_mock()
            smtp.has_extn.return_value = True
            result = smtp.starttls_required()
            check('Activa STARTTLS', smtp.starttls.call_count == 1)
            check('EHLO antes y después', smtp.ehlo.call_count == 2)
            check('Devuelve conexión', result is smtp)

    print(f'RESUMEN SMTP: {cases} casos; {errors} errores')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
