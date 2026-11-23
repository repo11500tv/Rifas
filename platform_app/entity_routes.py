from flask import render_template
import html, re, secrets, sqlite3
from functools import wraps
from flask import Blueprint, abort, current_app, flash, redirect, render_template_string, request, session, url_for, g
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint('entity', __name__, url_prefix='/e/<slug>')

def get_entity(slug):
    from platform_app import DB, ENTITIES
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,49}', slug): abort(404)
    with sqlite3.connect(f'file:{DB}?mode=ro', uri=True) as c:
        c.row_factory=sqlite3.Row
        row=c.execute('SELECT * FROM entities WHERE slug=?',(slug,)).fetchone()
    if row is None: abort(404)
    return row

def edb(slug):
    from platform_app import ENTITIES
    path=ENTITIES/slug/'data'/'rifas.sqlite3'
    con=sqlite3.connect(f'file:{path}?mode=rw',uri=True,timeout=15)
    con.row_factory=sqlite3.Row
    return con

def token():
    if '_csrf' not in session: session['_csrf']=secrets.token_urlsafe(32)
    return session['_csrf']


def navigation_back_url():
    """Use stable GET endpoints; never return to a POST-only URL."""
    slug = request.view_args.get("slug") if request.view_args else None
    if not slug:
        return None
    endpoint = request.endpoint or ""
    if endpoint == "entity.login":
        return url_for("entity.home", slug=slug)
    if endpoint == "entity.admin":
        return url_for("entity.home", slug=slug)
    if endpoint.startswith("participant_topup_admin.") or endpoint.startswith("participant_credits_admin."):
        return url_for("entity.admin", slug=slug)
    if endpoint.startswith("participant_") or endpoint.startswith("participants."):
        if session.get("participant_slug") == slug and session.get("participant_id"):
            return url_for("participants.account", slug=slug)
        return url_for("entity.home", slug=slug)
    if endpoint.startswith("entity.") and endpoint != "entity.home":
        if session.get("entity_slug") == slug and session.get("entity_user_id"):
            return url_for("entity.admin", slug=slug)
    if session.get("entity_slug") == slug and session.get("entity_user_id"):
        return url_for("entity.admin", slug=slug)
    return url_for("entity.home", slug=slug)

def layout(title, body):
    destination = navigation_back_url()

    if destination:
        back_button = (
            '<nav class="rifas-navigation" '
            'style="margin:0 0 16px">'
            '<a href="' +
            html.escape(destination, quote=True) +
            '" style="display:inline-block;'
            'padding:9px 16px;'
            'border:1px solid #aaa;'
            'border-radius:7px;'
            'text-decoration:none;'
            'font-weight:600">'
            '&#8592; Volver</a></nav>'
        )
        body = back_button + body

    return render_template_string('''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{title}}</title><style>body{font:16px system-ui;margin:0;background:#f4f7fb;color:#18304b}header{background:#17365a;color:white;padding:22px}main{max-width:860px;margin:30px auto;padding:0 16px}.card{background:white;border:1px solid #dde4ed;border-radius:12px;padding:24px;margin:16px 0}input,button{padding:11px;border-radius:7px}input{display:block;width:100%;box-sizing:border-box;border:1px solid #cbd5e1;margin:7px 0 16px}button{border:0;background:#17365a;color:white;cursor:pointer}a{color:#165b9d}.notice{background:#fff4d6;padding:10px;border-radius:8px}</style></head><body><header><strong>{{title}}</strong></header><main>{% for message in get_flashed_messages() %}<p class="notice">{{message}}</p>{% endfor %}{{body|safe}}</main></body></html>''', title=title, body=body)

def protected(fn):
    @wraps(fn)
    def wrapper(slug,*args,**kwargs):
        ent=get_entity(slug)
        if ent['status']!='active': abort(403)
        if session.get('entity_slug') != slug or not session.get('entity_user'):
            return redirect(url_for('entity.login',slug=slug))
        with edb(slug) as c:
            user=c.execute('SELECT id,role,active FROM entity_admins WHERE id=? AND username=?',(session.get('entity_user_id'),session['entity_user'])).fetchone()
        if not user or not user['active']: abort(403)
        return fn(slug,*args,**kwargs)
    return wrapper

def owner_required(fn):
    @wraps(fn)
    @protected
    def wrapper(slug, *args, **kwargs):
        with edb(slug) as c:
            admin = c.execute(
                "SELECT role, active FROM entity_admins "
                "WHERE id=? AND username=?",
                (
                    session.get("entity_user_id"),
                    session.get("entity_user"),
                ),
            ).fetchone()

        if not admin or not admin["active"] or admin["role"] != "owner":
            abort(403)

        return fn(slug, *args, **kwargs)

    return wrapper


@bp.get('/')
def home(slug):
    ent = get_entity(slug)
    if ent['status'] != 'active':
        abort(403)

    import re

    def safe_color(value, default):
        if value and re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            return value
        return default

    public_name = ent['public_name'] or ent['name']

    from flask import url_for

    logo = ''
    if ent['logo_path']:
        logo = url_for('entity.public_logo', slug=slug)

    return render_template(
        "entity_portal.html",
        google_enabled="participant_google_oauth" in current_app.extensions,
        slug=slug,
        entity_name=public_name,
        primary_color=safe_color(
            ent['primary_color'], '#176b59'
        ),
        secondary_color=safe_color(
            ent['secondary_color'], '#344b67'
        ),
        logo_path=logo,
    )


@bp.get('/sorteos/<int:raffle_id>/fotografia')
def public_raffle_image(slug, raffle_id):
    from pathlib import Path
    from flask import abort, send_file
    from platform_app import ENTITIES
    from platform_app.raffle_image_storage import valid_filename

    entity = get_entity(slug)
    if entity['status'] != 'active':
        abort(404)

    with edb(slug) as con:
        raffle = con.execute(
            "SELECT image_filename FROM raffles "
            "WHERE id=? AND status='published'",
            (raffle_id,)
        ).fetchone()

    if not raffle or not valid_filename(raffle['image_filename']):
        abort(404)

    filename = raffle['image_filename']
    directory = (ENTITIES / slug / 'uploads' / 'sorteos').resolve()
    path = directory / filename

    if path.is_symlink() or not path.is_file():
        abort(404)

    mime = {
        '.jpg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp'
    }.get(path.suffix.lower())

    if not mime:
        abort(404)

    response = send_file(
        path,
        mimetype=mime,
        conditional=True,
        max_age=300
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@bp.get('/sorteos/<int:raffle_id>/informacion')
def public_raffle_information(slug, raffle_id):
    from html import escape
    from flask import abort, url_for

    entity = get_entity(slug)
    if entity['status'] != 'active':
        abort(404)

    with edb(slug) as con:
        raffle = con.execute(
            "SELECT id,title,description,prizes,"
            "extended_info,image_filename "
            "FROM raffles WHERE id=? AND status='published'",
            (raffle_id,)
        ).fetchone()

    if not raffle or not (raffle['extended_info'] or '').strip():
        abort(404)

    image_html = ''
    if raffle['image_filename']:
        from platform_app.raffle_image_storage import valid_filename
        if valid_filename(raffle['image_filename']):
            image_url = url_for(
                'entity.public_raffle_image',
                slug=slug,
                raffle_id=raffle_id
            )
            image_html = (
                '<p><img src="' + escape(image_url, quote=True) +
                '" alt="Fotografía del premio" '
                'style="max-width:100%;max-height:480px;'
                'object-fit:contain;border-radius:8px"></p>'
            )

    def paragraph(value):
        return (
            '<p style="white-space:pre-wrap">' +
            escape(value or '') +
            '</p>'
        )

    body = (
        '<div class="card">'
        '<h2>' + escape(raffle['title']) + '</h2>' +
        image_html +
        '<h3>Descripción del sorteo</h3>' +
        paragraph(raffle['description']) +
        '<h3>Premios</h3>' +
        paragraph(raffle['prizes']) +
        '<h3>Más información</h3>' +
        paragraph(raffle['extended_info']) +
        '</div>'
    )

    return layout('Información del sorteo', body)


@bp.route('/admin/login',methods=['GET','POST'])
def login(slug):
    ent=get_entity(slug)
    if ent['status']!='active': abort(403)
    if request.method=='POST':
        from platform_app.security import allow_attempt, record_failure, clear_failures
        identity=request.form.get('username','').strip().lower()[:254]
        if not allow_attempt('entity_login:'+slug,identity): abort(429)
        with edb(slug) as c:
            user=c.execute('SELECT * FROM entity_admins WHERE username=? AND active=1',(request.form.get('username',''),)).fetchone()
        if user and check_password_hash(user['password_hash'],request.form.get('password','')):
            clear_failures('entity_login:'+slug,identity)
            session['entity_slug']=slug;session['entity_user']=user['username'];session['entity_user_id']=user['id'];session['_activity_entity']=int(__import__('time').time());token()
            return redirect(url_for('entity.admin',slug=slug))
        record_failure('entity_login:'+slug,identity)
        flash('Credenciales incorrectas')
    logo = (
        f'<img src="{url_for("entity.public_logo",slug=slug)}" '
        'alt="Logotipo de la entidad" '
        'style="display:block;max-width:180px;max-height:140px;'
        'width:auto;height:auto;object-fit:contain;margin:0 auto 22px">'
        if ent['logo_path'] else
        f'<h2 style="text-align:center">{html.escape(ent["name"])}</h2>'
    )
    return layout('Acceso · '+ent['name'], f'<div class="card">{logo}<form method="post"><input type="hidden" name="_csrf" value="{token()}"><label>Usuario<input name="username" autocomplete="username" required></label><label>Contraseña<input type="password" name="password" autocomplete="current-password" required></label><button>Entrar</button></form><p><a href="{url_for('admin_password_recovery.request_recovery',slug=slug)}">¿Has olvidado tu contraseña?</a></p></div>')

@bp.get('/admin/')
@protected
def admin(slug):
    ent=get_entity(slug)
    with edb(slug) as c:
        users=c.execute('SELECT username,role,active FROM entity_admins ORDER BY id').fetchall()
        cfg=c.execute('SELECT key,value FROM entity_settings WHERE key != ? ORDER BY key', ('smtp_password_encrypted',)).fetchall()
        current_admin=c.execute(
            'SELECT role FROM entity_admins WHERE id=? AND username=? AND active=1',
            (session.get('entity_user_id'), session.get('entity_user'))
        ).fetchone()
    users_html=''.join(f'<li>{html.escape(u["username"])} · {html.escape(u["role"])} · {"activo" if u["active"] else "inactivo"}</li>' for u in users)
    settings_html=''.join(f'<li>{html.escape(x["key"])}: {html.escape(x["value"])}</li>' for x in cfg)
    smtp_link = (
        '<p><a href="' +
        html.escape(
            url_for('entity.smtp_settings', slug=slug),
            quote=True
        ) +
        '">Configurar correo SMTP</a></p>'
        if current_admin and current_admin['role'] == 'owner'
        else ''
    )
    # ENTITY_BRANDING_ADMIN_LINK_V1
    branding_link = (
        '<p><a href="' +
        html.escape(
            url_for('entity.branding', slug=slug),
            quote=True
        ) +
        '">Personalizar entidad</a></p>'
        if current_admin and current_admin['role'] == 'owner'
        else ''
    )
    return layout('Administración · '+ent['name'],(f'<div class="card"><h2>Administradores</h2><ul>{users_html}</ul><h2>Configuración</h2><ul>{settings_html}</ul>{smtp_link}{branding_link}<p><a href="{url_for('raffles.list_raffles',slug=slug)}">Gestionar sorteos</a> · <a href="{url_for('prize_management.list_prizes',slug=slug)}">Gestionar premios</a> · <a href="{url_for('participants.admin_list',slug=slug)}">Participantes</a> · <a href="{url_for('participant_credits_admin.manage',slug=slug)}">Gestionar créditos</a></p><form method="post" action="{url_for('entity.logout',slug=slug)}"><input type="hidden" name="_csrf" value="{token()}"><button>Cerrar sesión</button></form></div>' + ('<p><a href="' + html.escape(url_for('participant_topup_admin.manage', slug=slug), quote=True) + '">Administrar solicitudes de recarga</a></p>')))


@bp.route('/admin/smtp', methods=['GET', 'POST'])
@owner_required
def smtp_settings(slug):
    """Configuración SMTP exclusiva del propietario de la entidad."""
    from platform_app.entity_smtp import (
        read_settings, save_settings, encrypt_password
    )
    from platform_app.smtp_validation import validate_smtp

    ent = get_entity(slug)

    if request.method == 'POST':
        host = request.form.get('smtp_host', '').strip()
        port_text = request.form.get('smtp_port', '').strip()
        security = request.form.get('smtp_security', '').strip()
        username = request.form.get('smtp_username', '').strip()
        sender = request.form.get('smtp_sender', '').strip()
        sender_name = request.form.get('smtp_sender_name', '').strip()
        password = request.form.get('smtp_password', '')

        errors = validate_smtp(
            host, port_text, security, username, sender
        )

        if not sender_name:
            errors.append('Indique el nombre del remitente')
        elif len(sender_name) > 120 or '\r' in sender_name or '\n' in sender_name:
            errors.append('Nombre del remitente no válido')

        if len(password) > 1024:
            errors.append('La contraseña SMTP es demasiado larga')

        if errors:
            for error in errors:
                flash(error)
        else:
            with edb(slug) as connection:
                current = read_settings(connection)

                updated = {
                    'smtp_host': host,
                    'smtp_port': str(int(port_text)),
                    'smtp_security': security,
                    'smtp_username': username,
                    'smtp_sender': sender,
                    'smtp_sender_name': sender_name,
                }

                if password:
                    updated['smtp_password_encrypted'] = (
                        encrypt_password(password)
                    )
                elif not current['smtp_password_encrypted']:
                    flash(
                        'Configuración guardada sin contraseña SMTP. '
                        'El envío de correos no estará disponible.'
                    )

                save_settings(connection, updated)

            flash('Configuración SMTP guardada correctamente')
            return redirect(
                url_for('entity.smtp_settings', slug=slug)
            )

    with edb(slug) as connection:
        cfg = read_settings(connection)

    def value(key):
        return html.escape(cfg.get(key, ''), quote=True)

    security = cfg.get('smtp_security') or 'ssl'
    ssl_selected = ' selected' if security == 'ssl' else ''
    tls_selected = ' selected' if security == 'starttls' else ''

    password_status = (
        'Hay una contraseña guardada. '
        'Deje el campo vacío para conservarla.'
        if cfg.get('smtp_password_encrypted')
        else 'Todavía no hay contraseña SMTP guardada.'
    )

    body = f"""
    <div class="card">
      <h2>Configuración de correo SMTP</h2>
      <p>Estos datos se utilizan exclusivamente para enviar
      correos electrónicos de esta entidad.</p>

      <form method="post">
        <input type="hidden" name="_csrf" value="{token()}">

        <label>Servidor SMTP
          <input name="smtp_host"
                 value="{value('smtp_host')}"
                 maxlength="253" required>
        </label>

        <label>Puerto
          <input name="smtp_port" type="number"
                 value="{value('smtp_port') or '465'}"
                 min="1" max="65535" required>
        </label>

        <label>Seguridad
          <select name="smtp_security" required>
            <option value="ssl"{ssl_selected}>
              SSL/TLS (puerto 465)
            </option>
            <option value="starttls"{tls_selected}>
              STARTTLS (puerto 587)
            </option>
          </select>
        </label>

        <p><small>Utilice el puerto 465 para SSL/TLS
        o el 587 para STARTTLS.</small></p>

        <label>Usuario SMTP
          <input name="smtp_username"
                 value="{value('smtp_username')}"
                 maxlength="254" autocomplete="off" required>
        </label>

        <label>Contraseña SMTP
          <input name="smtp_password" type="password"
                 maxlength="1024"
                 autocomplete="new-password">
        </label>

        <p><small>{html.escape(password_status)}</small></p>

        <label>Nombre del remitente
          <input name="smtp_sender_name"
                 value="{value('smtp_sender_name')}"
                 maxlength="120" required>
        </label>

        <label>Correo remitente
          <input name="smtp_sender" type="email"
                 value="{value('smtp_sender')}"
                 maxlength="254" required>
        </label>

        <button type="submit">Guardar configuración SMTP</button>
      </form>

      <hr>

      <h3>Enviar correo de prueba</h3>

      <p>
        Introduzca una dirección de correo para comprobar
        el funcionamiento de la configuración SMTP guardada.
      </p>

      <form method="post"
            action="{url_for('entity.smtp_test', slug=slug)}">

        <input type="hidden"
               name="_csrf"
               value="{token()}">

        <label>Correo de destino para la prueba
          <input type="email"
                 name="test_destination"
                 maxlength="254"
                 placeholder="destinatario@ejemplo.com"
                 required>
        </label>

        <button type="submit">
          Enviar correo de prueba
        </button>

      </form>

      <p><small>
        Primero guarde cualquier cambio en la configuración SMTP.
        El resultado del envío aparecerá en esta página.
      </small></p>

      <p><a href="{url_for('entity.admin', slug=slug)}">
        Volver a administración
      </a></p>
    </div>
    """

    return layout(
        'Correo SMTP · ' + ent['name'],
        body,
    )



@bp.post('/admin/smtp/test')
@owner_required
def smtp_test(slug):
    from platform_app.entity_mailer import (
        send_entity_email,
        EntityMailError,
    )
    from platform_app.smtp_validation import valid_email

    ent = get_entity(slug)

    destino = request.form.get('test_destination', '').strip()

    if not valid_email(destino):
        flash('Introduzca una dirección de correo válida.')
        return redirect(url_for('entity.smtp_settings', slug=slug))

    asunto = 'Prueba de correo SMTP - ' + ent['name']

    mensaje = (
        'Este es un mensaje de prueba del sistema '
        'Rifas Benéficas.\\n\\n'
        'Entidad: ' + ent['name'] + '\\n'
        'La configuración SMTP ha permitido enviar '
        'este mensaje.\\n'
    )

    try:
        with edb(slug) as connection:
            send_entity_email(
                connection,
                destino,
                asunto,
                mensaje,
            )

    except EntityMailError:
        flash(
            'No se ha podido enviar el correo de prueba. '
            'Revise la configuración SMTP.'
        )

    except Exception:
        flash(
            'Se ha producido un error al intentar '
            'enviar el correo de prueba.'
        )

    else:
        flash(
            'El servidor SMTP ha aceptado el correo '
            'de prueba dirigido a ' + destino
        )

    return redirect(
        url_for('entity.smtp_settings', slug=slug)
    )


@bp.post('/admin/logout')
def logout(slug):
    for key in ('entity_slug', 'entity_user', 'entity_user_id', '_activity_entity'):
        session.pop(key, None)
    return redirect(url_for('entity.login',slug=slug))


# ENTITY_BRANDING_V1
@bp.route('/admin/personalizacion', methods=['GET', 'POST'])
@owner_required
def branding(slug):
    from platform_app import DB
    from flask import render_template, url_for
    import re

    ent = get_entity(slug)

    def safe_color(value, default):
        if value and re.fullmatch(r'#[0-9a-fA-F]{6}', value):
            return value
        return default

    message = ''

    public_name = ent['public_name'] or ent['name']
    primary_color = safe_color(
        ent['primary_color'], '#176b59'
    )
    secondary_color = safe_color(
        ent['secondary_color'], '#344b67'
    )

    if request.method == 'POST':
        # ENTITY_LOGO_UPLOAD_V1
        from platform_app import ENTITIES
        from platform_app.entity_logo_storage import save_logo

        uploaded = request.files.get('logo')
        new_logo = None

        # ENTITY_LOGO_REMOVE_BACKEND_V1
        remove_logo = request.form.get('remove_logo') == '1'

        if remove_logo and uploaded and uploaded.filename:
            abort(
                400,
                description='No se puede subir y eliminar el logotipo a la vez.'
            )

        new_name = request.form.get(
            'public_name', ''
        ).strip()

        new_primary = request.form.get(
            'primary_color', ''
        ).strip()

        new_secondary = request.form.get(
            'secondary_color', ''
        ).strip()

        if not new_name or len(new_name) > 120:
            abort(400)

        if not re.fullmatch(
            r'#[0-9a-fA-F]{6}', new_primary
        ):
            abort(400)

        if not re.fullmatch(
            r'#[0-9a-fA-F]{6}', new_secondary
        ):
            abort(400)

        if uploaded and uploaded.filename:
            try:
                new_logo = save_logo(
                    uploaded,
                    ENTITIES / slug,
                )
            except ValueError as exc:
                abort(400, description=str(exc))

        with sqlite3.connect(
            f'file:{DB}?mode=rw', uri=True, timeout=15
        ) as db:
            cursor = db.execute(
                """
                UPDATE entities
                SET public_name=?,
                    primary_color=?,
                    secondary_color=?,
                    logo_path=CASE
                        WHEN ? = 1 THEN NULL
                        ELSE COALESCE(?, logo_path)
                    END
                WHERE slug=? AND status='active'
                """,
                (
                    new_name,
                    new_primary,
                    new_secondary,
                    int(remove_logo),
                    new_logo,
                    slug,
                ),
            )

            if cursor.rowcount != 1:
                abort(403)

        public_name = new_name
        primary_color = new_primary
        secondary_color = new_secondary
        message = 'Configuración guardada correctamente.'

    return render_template(
        'entity_branding.html',
        slug=slug,
        entity_name=ent['name'],
        public_name=public_name,
        primary_color=primary_color,
        secondary_color=secondary_color,
        csrf_token=token(),
        message=message,
        logo_url=(
            url_for('entity.public_logo', slug=slug)
            if get_entity(slug)['logo_path']
            else ''
        ),
    )



# ENTITY_LOGO_PUBLIC_V1
@bp.get('/logo')
def public_logo(slug):
    from pathlib import Path
    from flask import send_file
    from platform_app import ENTITIES
    import re

    ent = get_entity(slug)

    if ent['status'] != 'active':
        abort(403)

    filename = ent['logo_path'] or ''

    if not re.fullmatch(
        r'logo_[0-9a-f]{32}\.(png|jpg|webp)',
        filename
    ):
        abort(404)

    base = (ENTITIES / slug / 'uploads' / 'logos').resolve()
    path = base / filename

    if not path.is_file() or path.is_symlink():
        abort(404)

    if path.resolve().parent != base:
        abort(404)

    return send_file(
        path,
        conditional=True,
        max_age=300,
        mimetype={
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.webp': 'image/webp',
        }[path.suffix],
    )

# ENTITY_LOGO_PREVIEW_V1
