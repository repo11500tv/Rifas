#!/usr/bin/env python3
"""Pruebas aisladas de decoradores de acceso de Rifas Benéficas.

Extrae exclusivamente funciones AST de fuentes existentes, sin importar platform_app.
Todas las consultas SQLite se realizan sobre bases temporales creadas aquí.
"""
import argparse
import ast
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import sqlite3
import tempfile
from flask import Flask, abort, redirect, session, url_for
from werkzeug.exceptions import HTTPException


def extract(path, names, namespace):
    tree = ast.parse(path.read_bytes(), filename=str(path))
    for name in names:
        matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
        if len(matches) != 1:
            raise ValueError(f'{path.name}: se esperaba una función {name}')
        node = matches[0]
        if node.decorator_list or node.returns or any(a.annotation for a in node.args.args):
            raise ValueError(f'{name}: firma/decoradores inesperados')
        module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        exec(compile(module, str(path), 'exec'), namespace)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    src = args.source.resolve()
    required = ['entity_routes.py', 'participant_routes.py', 'participant_account_access_v2.py', 'participant_session_validation.py']
    for name in required:
        if not (src / name).is_file():
            parser.error(f'Falta {name}')
    app = Flask('rifas_permissions_isolated')
    app.secret_key = 'TEST_ONLY_NOT_FOR_PRODUCTION_SECRET_KEY'
    app.add_url_rule('/e/<slug>/login', endpoint='entity.login', view_func=lambda slug: 'login')
    app.add_url_rule('/e/<slug>/codigo', endpoint='participant_access_v2.request_code', view_func=lambda slug: 'codigo')
    cases = 0
    errors = 0
    def check(label, condition):
        nonlocal cases, errors
        cases += 1
        if not condition:
            errors += 1
        print(('OK' if condition else 'ERROR') + ' | ' + label)

    with tempfile.TemporaryDirectory(prefix='rifas-permisos-') as td:
        paths = {}
        for slug in ('entidada', 'entidadb'):
            path = Path(td) / (slug + '.sqlite3')
            con = sqlite3.connect(path)
            con.executescript('''
                CREATE TABLE entity_admins (id INTEGER PRIMARY KEY, username TEXT UNIQUE, role TEXT, active INTEGER);
                CREATE TABLE participants (id INTEGER PRIMARY KEY, active INTEGER, email_verified INTEGER);
                INSERT INTO entity_admins VALUES (1,'admin','owner',1);
                INSERT INTO entity_admins VALUES (2,'editor','editor',1);
                INSERT INTO entity_admins VALUES (3,'baja','owner',0);
                INSERT INTO participants VALUES (1,1,1);
                INSERT INTO participants VALUES (2,0,1);
                INSERT INTO participants VALUES (3,1,0);
            ''')
            con.commit()
            con.close()
            paths[slug] = path

        @contextmanager
        def edb(slug):
            if slug not in paths:
                abort(404)
            con = sqlite3.connect(paths[slug])
            con.row_factory = sqlite3.Row
            try:
                yield con
            finally:
                con.close()

        entities = {'entidada': {'status': 'active'}, 'entidadb': {'status': 'active'}, 'suspendida': {'status': 'inactive'}}
        def get_entity(slug):
            if slug not in entities:
                abort(404)
            return entities[slug]

        ns = {'wraps': wraps, 'session': session, 'redirect': redirect, 'url_for': url_for,
              'abort': abort, 'edb': edb, 'get_entity': get_entity}
        extract(src / 'participant_session_validation.py', ['valid_participant_id'], ns)
        extract(src / 'participant_account_access_v2.py', ['participant_can_access'], ns)
        extract(src / 'participant_routes.py', ['active_entity', 'member_only'], ns)
        member_only = ns['member_only']
        extract(src / 'entity_routes.py', ['protected', 'owner_required'], ns)
        protected = ns['protected']
        owner_required = ns['owner_required']
        member = member_only(lambda slug: 'ACCESO_PARTICIPANTE')
        admin = protected(lambda slug: 'ACCESO_ADMIN')
        owner = owner_required(lambda slug: 'ACCESO_OWNER')

        def run(view, slug, values):
            with app.test_request_context('/e/' + slug + '/'):
                session.update(values)
                try:
                    result = view(slug)
                    if isinstance(result, str):
                        status, location = 200, ''
                    else:
                        status, location = result.status_code, result.headers.get('Location', '')
                except HTTPException as exc:
                    status, location = exc.code, ''
                return status, location, dict(session)

        a1 = {'entity_slug':'entidada', 'entity_user':'admin', 'entity_user_id':1}
        a2 = {'entity_slug':'entidada', 'entity_user':'editor', 'entity_user_id':2}
        p1 = {'participant_slug':'entidada', 'participant_id':1}
        check('Administrador válido accede', run(admin, 'entidada', a1)[0] == 200)
        check('Administrador no autenticado redirigido', run(admin, 'entidada', {})[0] == 302)
        check('Administrador no accede a otra entidad', run(admin, 'entidadb', a1)[0] == 302)
        check('Administrador con ID/usuario discordantes bloqueado', run(admin, 'entidada', dict(a1, entity_user='editor'))[0] == 403)
        check('Administrador inactivo bloqueado', run(admin, 'entidada', {'entity_slug':'entidada','entity_user':'baja','entity_user_id':3})[0] == 403)
        check('Entidad inactiva bloqueada para administrador', run(admin, 'suspendida', a1)[0] == 403)
        check('Propietario válido accede', run(owner, 'entidada', a1)[0] == 200)
        check('Editor no puede actuar como propietario', run(owner, 'entidada', a2)[0] == 403)
        check('Propietario no accede a otra entidad', run(owner, 'entidadb', a1)[0] == 302)
        check('Participante verificado accede', run(member, 'entidada', p1)[0] == 200)
        check('Participante sin sesión redirigido', run(member, 'entidada', {})[0] == 302)
        check('Participante no accede a otra entidad', run(member, 'entidadb', p1)[0] == 302)
        s = run(member, 'entidada', {'participant_slug':'entidada','participant_id':2})
        check('Participante inactivo redirigido', s[0] == 302)
        check('Participante inactivo pierde sesión', 'participant_id' not in s[2] and 'participant_slug' not in s[2])
        s = run(member, 'entidada', {'participant_slug':'entidada','participant_id':3})
        check('Correo no verificado bloqueado', s[0] == 302)
        check('Correo no verificado elimina sesión', 'participant_id' not in s[2])
        check('ID de participante inexistente bloqueado', run(member, 'entidada', {'participant_slug':'entidada','participant_id':999})[0] == 302)
        check('ID de participante de tipo texto bloqueado', run(member, 'entidada', {'participant_slug':'entidada','participant_id':'1'})[0] == 302)
        check('Entidad inactiva bloqueada para participante', run(member, 'suspendida', p1)[0] == 404)
        check('Sesión de participante no autoriza administración', run(admin, 'entidada', p1)[0] == 302)
        check('Sesión de administrador no autoriza participante', run(member, 'entidada', a1)[0] == 302)
    print(f'RESUMEN PERMISOS: {cases} casos; {errors} errores')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
