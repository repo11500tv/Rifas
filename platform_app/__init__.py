import os, sqlite3, secrets, re, json
from pathlib import Path
from functools import wraps
from flask import Flask, request, redirect, url_for, session, render_template_string, render_template, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

ROOT = Path(os.environ.get('RIFAS_DATA_ROOT') or Path(__file__).resolve().parents[1]).resolve()
DB = ROOT / 'central' / 'plataforma.sqlite'
ENTITIES = ROOT / 'entidades'
PLATFORM_VERSION = '2.3.1'
REQUIRED_RAFFLE_VERSION = '2.4.0'
SCHEMA = """CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL, admin_email TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', version TEXT NOT NULL DEFAULT '2.0.0', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS releases (version TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, notes TEXT);
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, entity_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""
PAGE = """<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Rifas Benéficas 2.3.1</title><style>body{font:16px system-ui;background:#f5f7fa;color:#152438;margin:0}header{background:#17365a;color:white;padding:20px}main{max-width:950px;margin:30px auto;padding:0 18px}.card{background:white;border:1px solid #dfe4ec;border-radius:12px;padding:24px;margin:18px 0}input,button{padding:11px;margin:6px 0;box-sizing:border-box}input{width:100%;border:1px solid #cbd5e1;border-radius:7px}button{background:#17365a;color:white;border:0;border-radius:7px;cursor:pointer}a{color:#13599d}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #e4e8ef}.notice{padding:10px;background:#e9f4eb;border-radius:6px}</style></head><body><header><h2>Rifas Benéficas 2.3.1</h2><small>Administración central · Versión 2.3.1</small></header><main>{% with messages=get_flashed_messages() %}{% for m in messages %}<p class='notice'>{{m}}</p>{% endfor %}{% endwith %}{{body|safe}}</main></body></html>"""

def create_app():
    app = Flask(__name__)
    secret_file=ROOT/'central'/'secret.key'
    if not secret_file.exists():
        raise RuntimeError('Falta central/secret.key; ejecutar init_platform.py')
    app.secret_key=secret_file.read_text().strip()
    app.config.update(SESSION_COOKIE_NAME='rifas_produccion_session',SESSION_COOKIE_PATH='/rifas',SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE='Lax',PERMANENT_SESSION_LIFETIME=7200,MAX_CONTENT_LENGTH=6*1024*1024)
    app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1,x_prefix=1)
    @app.before_request
    def check_session_inactivity():
        from datetime import datetime, timezone
        from flask import session

        now = int(datetime.now(timezone.utc).timestamp())
        profiles = (
            ("admin", "_activity_central", 3600, ("admin",)),
            ("entity_user_id", "_activity_entity", 7200,
             ("entity_slug", "entity_user", "entity_user_id")),
            ("participant_id", "_activity_participant", 3600,
             ("participant_slug", "participant_id")),
        )
        active = False
        for identity, clock, limit, keys in profiles:
            if not session.get(identity):
                session.pop(clock, None)
                continue
            previous = session.get(clock)
            # Existing sessions with the former shared activity clock retain
            # their expiry when upgrading, rather than being reset blindly.
            if previous is None:
                previous = session.get("_last_activity", now)
            try:
                elapsed = now - int(previous)
            except (TypeError, ValueError):
                elapsed = limit + 1
            if elapsed < 0 or elapsed > limit:
                for key in keys:
                    session.pop(key, None)
                session.pop(clock, None)
            else:
                session[clock] = now
                active = True
        session.pop("_last_activity", None)
        if active:
            session.permanent = True

    def db():
        con=sqlite3.connect(f'file:{DB}?mode=rw',uri=True,timeout=15)
        con.row_factory=sqlite3.Row
        return con
    def csrf():
        if '_csrf' not in session: session['_csrf']=secrets.token_urlsafe(32)
        return session['_csrf']
    def page(body):
        return render_template_string(PAGE,body=body)
    def guard(fn):
        @wraps(fn)
        def inner(*args,**kwargs):
            if not session.get('admin'): return redirect(url_for('login'))
            return fn(*args,**kwargs)
        return inner
    @app.before_request
    def protect():
        if request.method=='POST' and not (session.get('_csrf') and secrets.compare_digest(request.form.get('_csrf',''),session['_csrf'])): abort(400)
    @app.get('/')
    def index():
        if not session.get('admin'): return redirect(url_for('login'))
        with db() as con: rows=con.execute('SELECT * FROM entities ORDER BY id DESC').fetchall()
        import html
        tr=''.join(f'<tr><td>{html.escape(r["name"])}</td><td>{html.escape(r["slug"])}</td><td>{html.escape(r["status"])}</td><td>{html.escape(r["version"])}</td><td><a href="{url_for('central21.provision',slug=r['slug'])}">Administrador</a> · <a href="{url_for('entity.home',slug=r['slug'])}">Ver</a> · <a href="{url_for('central21.delete_entity',slug=r['slug'])}">Eliminar entidad</a><form method="post" action="{url_for('central21.set_status',slug=r['slug'])}"><input type="hidden" name="_csrf" value="{csrf()}"><select name="status"><option value="active">Activa</option><option value="suspended">Suspendida</option></select><button>Aplicar</button></form></td></tr>' for r in rows)
        return page(f'<div class="card"><h3>Entidades</h3><p>{len(rows)} entidades registradas</p><table><tr><th>Entidad</th><th>Código</th><th>Estado</th><th>Versión</th><th>Gestión</th></tr>{tr}</table><p><a href="{url_for("new_entity")}">Dar de alta una entidad</a> · <a href="{url_for("update_center.home")}">Centro de actualizaciones</a></p><form method="post" action="{url_for('logout')}"><input type="hidden" name="_csrf" value="{csrf()}"><button>Salir</button></form></div>')
    @app.route('/login',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            from platform_app.security import allow_attempt, record_failure, clear_failures
            identity=request.form.get('username','').strip().lower()[:254]
            if not allow_attempt('central_login', identity): abort(429)
            with db() as con: admin=con.execute('SELECT * FROM admins WHERE username=?',(request.form.get('username',''),)).fetchone()
            if admin and check_password_hash(admin['password_hash'],request.form.get('password','')):
                clear_failures('central_login',identity)
                session['admin']=admin['username'];session['_activity_central']=int(__import__('time').time());csrf();return redirect(url_for('index'))
            record_failure('central_login',identity)
            flash('Credenciales incorrectas')
        return page(f'<div class="card"><h3>Acceso de administración general</h3><form method="post"><input type="hidden" name="_csrf" value="{csrf()}"><label>Usuario<input name="username" required autocomplete="username"></label><label>Contraseña<input type="password" name="password" required autocomplete="current-password"></label><button>Entrar</button></form></div>')
    @app.post('/logout')
    def logout():
        session.pop('admin', None);session.pop('_activity_central', None);return redirect(url_for('login'))
    @app.route('/entidades/nueva',methods=['GET','POST'])
    @guard
    def new_entity():
        if request.method=='POST':
            slug=request.form.get('slug','').strip().lower();name=request.form.get('name','').strip();email=request.form.get('email','').strip()
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,49}',slug) or not name or len(name)>150 or '@' not in email or len(email)>254:
                flash('Revisa el código, nombre y correo');return redirect(url_for('new_entity'))
            dest=ENTITIES/slug
            if dest.exists(): flash('El directorio ya existe');return redirect(url_for('new_entity'))
            try:
                with db() as con:
                    cur=con.execute('INSERT INTO entities(slug,name,admin_email) VALUES(?,?,?)',(slug,name,email))
                    dest.mkdir(mode=0o700)
                    for folder in ['data','uploads','config','backups']: (dest/folder).mkdir(mode=0o700)
                    template_db = ROOT / 'central' / 'plantillas' / 'entidad_maestra.sqlite3'
                    if not template_db.is_file():
                        raise RuntimeError('No existe la plantilla maestra')
                    with sqlite3.connect(
                        template_db.resolve().as_uri() + '?mode=ro',
                        uri=True
                    ) as check_connection:
                        if check_connection.execute(
                            'PRAGMA integrity_check'
                        ).fetchone()[0] != 'ok':
                            raise RuntimeError('Plantilla maestra no integra')
                        fields = {
                            row[1] for row in check_connection.execute(
                                'PRAGMA table_info(raffles)'
                            )
                        }
                        if not {'image_filename', 'extended_info'} <= fields:
                            raise RuntimeError('Plantilla maestra desactualizada')
                        version = check_connection.execute(
                            "SELECT version FROM module_versions WHERE module='sorteos'"
                        ).fetchone()
                        if not version or version[0] != REQUIRED_RAFFLE_VERSION:
                            raise RuntimeError('Version de sorteos incorrecta')
                    entity_db = dest / 'data' / 'rifas.sqlite3'
                    if not template_db.is_file():
                        raise RuntimeError('No existe la plantilla maestra de entidades')
                    with sqlite3.connect(
                        f'file:{template_db}?mode=ro', uri=True
                    ) as template_connection:
                        with sqlite3.connect(entity_db) as entity_connection:
                            template_connection.backup(entity_connection)
                            integrity = entity_connection.execute(
                                'PRAGMA integrity_check'
                            ).fetchone()[0]
                            if integrity != 'ok':
                                raise RuntimeError(
                                    'La base de datos de la nueva entidad no es valida'
                                )
                    (dest/'config'/'entity.json').write_text(json.dumps({'slug':slug,'name':name,'admin_email':email,'version':PLATFORM_VERSION},ensure_ascii=False,indent=2))
                    con.execute('UPDATE entities SET version=? WHERE id=?',(PLATFORM_VERSION,cur.lastrowid))
                    con.execute('INSERT INTO audit(actor,action,entity_id) VALUES(?,?,?)',(session['admin'],'create_entity',cur.lastrowid))
                return redirect(url_for('entity_created', slug=slug))
            except sqlite3.IntegrityError:
                flash('Ese código ya está registrado');return redirect(url_for('new_entity'))
        return page(f'<div class="card"><h3>Nueva entidad</h3><form method="post"><input type="hidden" name="_csrf" value="{csrf()}"><label>Nombre<input name="name" maxlength="150" required></label><label>Código URL (minúsculas, números y guiones)<input name="slug" pattern="[a-z0-9][a-z0-9-]{{2,49}}" required></label><label>Correo del futuro administrador<input name="email" type="email" required></label><button>Crear entidad</button></form><p><a href="{url_for("index")}">Volver</a></p></div>')

    @app.get('/entidades/<slug>/creada')
    @guard
    def entity_created(slug):
        import html
        with db() as con:
            ent = con.execute(
                'SELECT name, slug FROM entities WHERE slug=?',
                (slug,)
            ).fetchone()
        if not ent:
            abort(404)

        name = html.escape(ent['name'])
        public_url = url_for('entity.home', slug=slug, _external=True)
        admin_url = url_for('entity.admin', slug=slug, _external=True)
        setup_url = url_for('central21.provision', slug=slug, _external=True)

        def link(label, url):
            safe = html.escape(url, quote=True)
            return (
                '<p><strong>' + label + '</strong></p>'
                '<p><a href="' + safe + '">' + safe + '</a></p>'
                '<p><button type="button" onclick="navigator.clipboard.writeText(this.dataset.url)" '
                'data-url="' + safe + '">Copiar enlace</button></p>'
            )

        body = (
            '<div class="card">'
            '<h3>Entidad creada correctamente</h3>'
            '<p><strong>Entidad:</strong> ' + name + '</p>'
            '<p><strong>Código:</strong> ' + html.escape(slug) + '</p>'
            + link('Portal público', public_url)
            + link('Administración de la entidad', admin_url)
            + link('Configuración del primer administrador', setup_url)
            + '<p>Conserva el enlace de configuración inicial para crear el administrador.</p>'
            + '<p><a href="' + url_for('index') + '">Volver al panel general</a></p>'
            '</div>'
        )
        return page(body)

    @app.get('/health')
    def health(): return {'status':'ok','version':'2.3.1'}
    from platform_app.entity_routes import bp as entity_bp
    from platform_app.central_routes import bp as central_bp
    app.register_blueprint(entity_bp)
    from platform_app.admin_password_recovery import bp as admin_password_recovery_bp
    app.register_blueprint(admin_password_recovery_bp)
    app.register_blueprint(central_bp)
    from platform_app.update_center import bp as update_center_bp
    app.register_blueprint(update_center_bp)
    from platform_app.raffle_routes import bp as raffles_bp
    app.register_blueprint(raffles_bp)
    from platform_app.raffle_draw_rules import bp as raffle_draw_rules_bp
    from platform_app.raffle_draw_results import bp as raffle_draw_results_bp
    app.register_blueprint(raffle_draw_rules_bp)
    app.register_blueprint(raffle_draw_results_bp)
    from platform_app.raffle_acta_pdf import bp as raffle_acta_pdf_bp
    app.register_blueprint(raffle_acta_pdf_bp)
    from platform_app.participant_routes import bp as participants_bp
    app.register_blueprint(participants_bp)
    from platform_app.participant_edit_admin import bp as participant_edit_admin_bp
    app.register_blueprint(participant_edit_admin_bp)
    from platform_app.participant_registration_form_v2 import bp as participant_registration_v2_bp
    app.register_blueprint(participant_registration_v2_bp)
    from platform_app.participant_access_routes_v2 import bp as participant_access_v2_bp
    app.register_blueprint(participant_access_v2_bp)
    from platform_app.participant_credits_admin import bp as credits_admin_bp
    app.register_blueprint(credits_admin_bp)
    from platform_app.participant_topup_requests import bp as topup_requests_bp
    app.register_blueprint(topup_requests_bp)
    from platform_app.participant_topup_admin import bp as topup_admin_bp
    app.register_blueprint(topup_admin_bp)
    from platform_app.participant_raffle_purchases import bp as purchases_bp
    app.register_blueprint(purchases_bp)
    from platform_app.prize_management import bp as prize_management_bp
    app.register_blueprint(prize_management_bp)
    from platform_app.prize_communications_admin import bp as prize_communications_admin_bp
    app.register_blueprint(prize_communications_admin_bp)
    from platform_app.prize_delivery_admin import bp as prize_delivery_admin_bp
    app.register_blueprint(prize_delivery_admin_bp)
    from platform_app.prize_notification_settings import bp as prize_notification_settings_bp
    app.register_blueprint(prize_notification_settings_bp)
    return app
