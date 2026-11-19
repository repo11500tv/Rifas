#!/usr/bin/env python3
"""Pruebas aisladas de las funciones reales buy/manage. Nunca abre BBDD de producción.
Uso: python -B rifas-purchase-credit-tests-0.1.py --source /ruta/platform_app
"""
import argparse
import ast
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
import uuid
from decimal import Decimal, InvalidOperation
from html import escape
from flask import Flask, abort, flash, redirect, request, session, url_for

SCHEMA = '''
CREATE TABLE participants (id INTEGER PRIMARY KEY,name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 150),email TEXT NOT NULL COLLATE NOCASE UNIQUE,phone TEXT NOT NULL UNIQUE,email_verified INTEGER NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1)),phone_verified INTEGER NOT NULL DEFAULT 0 CHECK(phone_verified IN (0,1)),preferred_login TEXT NOT NULL DEFAULT 'email' CHECK(preferred_login IN ('email','sms')),active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE raffles (id INTEGER PRIMARY KEY,title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 150),description TEXT NOT NULL DEFAULT '',prizes TEXT NOT NULL DEFAULT '',number_start INTEGER NOT NULL CHECK(number_start>=0),number_end INTEGER NOT NULL CHECK(number_end>=number_start),number_width INTEGER NOT NULL CHECK(number_width BETWEEN 1 AND 12),donation_cents INTEGER NOT NULL CHECK(donation_cents>=0),draw_at TEXT,status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','closed','finished')),created_by TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE credit_movements (id INTEGER PRIMARY KEY,participant_id INTEGER NOT NULL REFERENCES participants(id),amount_cents INTEGER NOT NULL CHECK(amount_cents != 0),movement_type TEXT NOT NULL CHECK(movement_type IN ('topup','consume','refund','adjustment')),reference TEXT NOT NULL UNIQUE,notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE raffle_purchases (id INTEGER PRIMARY KEY,raffle_id INTEGER NOT NULL REFERENCES raffles(id),participant_id INTEGER NOT NULL REFERENCES participants(id),quantity INTEGER NOT NULL CHECK(quantity > 0),unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),total_cents INTEGER NOT NULL CHECK(total_cents > 0),credit_movement_id INTEGER NOT NULL UNIQUE REFERENCES credit_movements(id),created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,CHECK(total_cents = quantity * unit_price_cents));
CREATE TABLE raffle_numbers (id INTEGER PRIMARY KEY,raffle_id INTEGER NOT NULL REFERENCES raffles(id),purchase_id INTEGER NOT NULL REFERENCES raffle_purchases(id),participant_id INTEGER NOT NULL REFERENCES participants(id),number INTEGER NOT NULL CHECK(number >= 0),created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(raffle_id,number),UNIQUE(purchase_id,number));
'''
ALLOWED_IMPORTS = {
 'participant_raffle_purchases.py': {'html','sqlite3','flask','platform_app.entity_routes','platform_app.participant_routes'},
 'participant_credits_admin.py': {'sqlite3','uuid','decimal','html','flask','platform_app.entity_routes'},
}
EXPECTED_FUNCTIONS = {'participant_raffle_purchases.py': {'buy','active_entity'},'participant_credits_admin.py': {'manage','euros_to_cents','money'}}

def extract_functions(source, filename, names, namespace):
    tree = ast.parse(source.read_bytes(), filename=str(source))
    allowed = ALLOWED_IMPORTS[filename]
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(a.name in allowed for a in node.names), 'Importación inesperada'
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module in allowed, 'Dependencia inesperada'
        elif isinstance(node, ast.Assign):
            assert len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'bp' and isinstance(node.value, ast.Call), 'Inicialización inesperada'
        elif isinstance(node, ast.FunctionDef):
            assert node.name in {'money','active_entity','account_navigation','list_raffles','detail','confirm','buy','my_purchases','euros_to_cents','manage'}, 'Función inesperada'
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value,str):
            pass
        else:
            raise AssertionError('Código superior inesperado: '+type(node).__name__)
    selected=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in names:
            node.decorator_list=[]
            selected.append(node)
    assert {n.name for n in selected} == names, 'Funciones requeridas ausentes'
    module=ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[]))
    exec(compile(module,str(source),'exec'),namespace)

class Harness:
    def __init__(self, folder):
        self.tmp=tempfile.TemporaryDirectory(prefix='rifas-funcional-')
        self.paths={slug:Path(self.tmp.name)/(slug+'.sqlite3') for slug in ('pruebas','otraentidad')}
        for path in self.paths.values():
            with sqlite3.connect(path) as c:
                c.executescript(SCHEMA)
                c.execute("INSERT INTO participants(id,name,email,phone,email_verified,phone_verified) VALUES(1,'Persona ficticia',?, '600000001',1,1)",(path.stem+'@example.invalid',))
                c.execute("INSERT INTO raffles(id,title,number_start,number_end,number_width,donation_cents,status,created_by) VALUES(1,'Sorteo ficticio',0,99,2,200,'published','test')")
                c.execute("INSERT INTO credit_movements(participant_id,amount_cents,movement_type,reference) VALUES(1,1000,'topup','INITIAL')")
                c.commit()
        self.app=Flask('rifas_funcional_aislado')
        self.app.secret_key='TEST_ONLY_NOT_FOR_PRODUCTION_SECRET_KEY'
        self.app.config.update(TESTING=True)
        def edb(slug):
            if slug not in self.paths: abort(404)
            c=sqlite3.connect(self.paths[slug],timeout=2)
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            return c
        def get_entity(slug):
            if slug not in self.paths: abort(404)
            return {'status':'active','name':'Entidad ficticia'}
        common=dict(sqlite3=sqlite3,abort=abort,flash=flash,redirect=redirect,request=request,session=session,url_for=url_for,edb=edb,get_entity=get_entity,escape=escape,uuid=uuid,Decimal=Decimal,InvalidOperation=InvalidOperation,layout=lambda title,body:body,token=lambda:'token-ficticio')
        purchases=dict(common)
        credits=dict(common)
        extract_functions(folder/'participant_raffle_purchases.py','participant_raffle_purchases.py',EXPECTED_FUNCTIONS['participant_raffle_purchases.py'],purchases)
        extract_functions(folder/'participant_credits_admin.py','participant_credits_admin.py',EXPECTED_FUNCTIONS['participant_credits_admin.py'],credits)
        self.purchases=purchases; self.credits=credits
        self.app.add_url_rule('/e/<slug>/participantes/sorteos/<int:raffle_id>/comprar',endpoint='purchase_test',view_func=purchases['buy'],methods=['POST'])
        self.app.add_url_rule('/e/<slug>/creditos/',endpoint='credit_test',view_func=credits['manage'],methods=['GET','POST'])
        self.app.add_url_rule('/e/<slug>/participantes/sorteos/<int:raffle_id>',endpoint='participant_raffle_purchases.detail',view_func=lambda slug,raffle_id:'Detalle')
        self.app.add_url_rule('/e/<slug>/participantes/sorteos/mis-participaciones',endpoint='participant_raffle_purchases.my_purchases',view_func=lambda slug:'Mis participaciones')
        self.client=self.app.test_client()
        with self.client.session_transaction() as s:
            s.update(participant_id=1,participant_slug='pruebas',entity_user_id=1,entity_user='admin-ficticio',entity_slug='pruebas')
    def query(self,slug,sql,args=()):
        with sqlite3.connect(f'file:{self.paths[slug]}?mode=ro',uri=True) as c:
            c.execute('PRAGMA query_only=ON')
            return c.execute(sql,args).fetchall()
    def balance(self,slug='pruebas'):
        return self.query(slug,'SELECT COALESCE(SUM(amount_cents),0) FROM credit_movements')[0][0]
    def counts(self,slug='pruebas'):
        return tuple(self.query(slug,'SELECT COUNT(*) FROM '+t)[0][0] for t in ('credit_movements','raffle_purchases','raffle_numbers'))
    def buy(self,numbers,slug='pruebas'):
        return self.client.post(f'/e/{slug}/participantes/sorteos/1/comprar',data={'numbers':numbers})
    def admin(self,operation,amount,operation_id=None,slug='pruebas',notes='Prueba ficticia'):
        return self.client.post(f'/e/{slug}/creditos/',data={'participant_id':'1','operation':operation,'amount':amount,'notes':notes,'operation_id':operation_id or uuid.uuid4().hex})
    def close(self): self.tmp.cleanup()

def run(folder):
    h=Harness(folder); checks=[]
    def check(label,condition):
        checks.append(bool(condition)); print(('OK' if condition else 'ERROR')+' | '+label)
    try:
        r=h.buy(['3','4']); check('Compra válida redirige',r.status_code==302)
        check('Compra descuenta 400 céntimos',h.balance()==600)
        check('Compra registra movimiento, compra y dos números',h.counts()==(2,1,2))
        check('Números adjudicados',h.query('pruebas','SELECT number FROM raffle_numbers ORDER BY number')==[(3,),(4,)])
        before=(h.balance(),h.counts());r=h.buy(['3']);check('Número ocupado rechazado sin cargo',r.status_code==302 and (h.balance(),h.counts())==before)
        r=h.buy(['5','6','7','8']);check('Saldo insuficiente rechazado sin cargo',r.status_code==302 and (h.balance(),h.counts())==before)
        for label,raw in [('Duplicados',['9','9']),('Valor no numérico',['x']),('Fuera de rango',['100'])]:
            r=h.buy(raw);check(label+' rechazado sin cambios',r.status_code==400 and (h.balance(),h.counts())==before)
        r=h.admin('recarga','5,00');check('Recarga administrativa',r.status_code==200 and h.balance()==1100)
        ref=uuid.uuid4().hex;r=h.admin('recarga','2,00',ref);check('Recarga identificada',r.status_code==200 and h.balance()==1300)
        r=h.admin('recarga','2,00',ref);check('Recarga repetida bloqueada',r.status_code==200 and h.balance()==1300)
        r=h.admin('ajuste','3,00');check('Ajuste administrativo',r.status_code==200 and h.balance()==1000)
        before=(h.balance(),h.counts());r=h.admin('ajuste','20,00');check('Ajuste con saldo insuficiente rechazado',r.status_code==200 and (h.balance(),h.counts())==before)
        r=h.admin('recarga','0,001');check('Importe con tres decimales rechazado',r.status_code==200 and (h.balance(),h.counts())==before)
        r=h.admin('recarga','2,00',notes='');check('Operación sin concepto rechazada',r.status_code==200 and (h.balance(),h.counts())==before)
        check('Segunda entidad sin cambios',h.balance('otraentidad')==1000 and h.counts('otraentidad')==(1,0,0))
        r=h.buy(['10'],slug='otraentidad');check('Compra en entidad aislada',r.status_code==302 and h.balance('otraentidad')==800 and h.balance()==1000)
        check('Compras de ambas entidades independientes',h.counts('otraentidad')==(2,1,1) and h.counts('pruebas')[1]==1)
        # Error de integridad deliberado al insertar números: comprueba reversión atómica.
        with sqlite3.connect(h.paths['pruebas']) as c:
            c.execute('CREATE TRIGGER fail_number BEFORE INSERT ON raffle_numbers WHEN NEW.number=11 BEGIN SELECT RAISE(ABORT,"fallo ficticio"); END;')
        before=(h.balance(),h.counts())
        try:
            h.buy(['11']);failed=False
        except sqlite3.Error:
            failed=True
        check('Error SQLite de inserción propagado',failed)
        check('Error SQLite revierte movimiento y compra', (h.balance(),h.counts())==before)
    finally:
        h.close()
    errors=len(checks)-sum(checks)
    print(f'RESUMEN COMPRAS Y CREDITOS: {len(checks)} casos; {errors} errores')
    return 0 if errors==0 else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True,type=Path)
    args=parser.parse_args()
    try: raise SystemExit(run(args.source))
    except Exception as exc:
        print('ERROR | Fallo de preparación o ejecución:',repr(exc))
        raise SystemExit(2)
