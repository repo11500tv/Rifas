import html, sqlite3, secrets
from flask import Blueprint, abort, flash, redirect, request, session, url_for
from werkzeug.security import generate_password_hash
from platform_app.entity_routes import get_entity, edb

bp=Blueprint('central21',__name__)

def require_superadmin():
    if not session.get('admin'): abort(403)

@bp.route('/entidades/<slug>/administrador',methods=['GET','POST'])
def provision(slug):
    require_superadmin()
    ent=get_entity(slug)
    with edb(slug) as check_db:
        has_admin = check_db.execute('SELECT COUNT(*) FROM entity_admins').fetchone()[0] > 0
    if has_admin and request.method == 'GET':
        return redirect(url_for('entity.admin', slug=slug) if session.get('entity_slug') == slug and session.get('entity_user_id') else url_for('entity.login', slug=slug))
    if request.method=='POST':
        username=request.form.get('username','').strip()
        p1=request.form.get('password','')
        p2=request.form.get('password_repeat','')
        if not (3<=len(username)<=80) or len(p1)<12 or p1!=p2:
            flash('Comprueba el usuario y la contraseña (mínimo 12 caracteres)')
        else:
            try:
                with edb(slug) as con:
                    existing=con.execute('SELECT COUNT(*) FROM entity_admins').fetchone()[0]
                    if existing:
                        flash('Ya existe un administrador. No se sobrescriben credenciales desde este formulario.')
                    else:
                        con.execute(
                            'INSERT INTO entity_admins(username,password_hash,role,email) VALUES(?,?,?,?)',
                            (
                                username,
                                generate_password_hash(p1,method='scrypt'),
                                'owner',
                                ent['admin_email']
                            )
                        )
                        flash('Administrador de entidad creado')
            except sqlite3.IntegrityError:
                flash('El usuario ya existe')
        return redirect(url_for('central21.provision',slug=slug))
    from platform_app.entity_routes import layout,token
    name=html.escape(ent['name'])
    return layout('Administrador inicial · '+ent['name'],f'<div class="card"><h2>{name}</h2><p>Solo permite crear el primer administrador de esta entidad.</p><form method="post"><input type="hidden" name="_csrf" value="{token()}"><label>Usuario<input name="username" required minlength="3" maxlength="80"></label><label>Contraseña<input name="password" type="password" minlength="12" required></label><label>Repetir contraseña<input name="password_repeat" type="password" minlength="12" required></label><button>Crear administrador</button></form><p><a href="{url_for("index")}">Volver al panel central</a></p></div>')

@bp.post('/entidades/<slug>/estado')
def set_status(slug):
    require_superadmin()
    from platform_app import DB
    state=request.form.get('status')
    if state not in ('active','suspended'): abort(400)
    with sqlite3.connect(f'file:{DB}?mode=rw',uri=True) as c:
        c.execute('UPDATE entities SET status=? WHERE slug=?',(state,slug))
        c.execute('INSERT INTO audit(actor,action,entity_id) SELECT ?,?,id FROM entities WHERE slug=?',(session['admin'],'status_'+state,slug))
    flash('Estado actualizado')
    return redirect(url_for('index'))


@bp.route('/entidades/<slug>/eliminar', methods=['GET', 'POST'])
def delete_entity(slug):
    """Eliminacion de entidades reservada al superadministrador."""
    from platform_app.entity_deletion import (
        require_superadmin,
        deletion_confirmation_page,
        delete_entity_safely,
    )

    require_superadmin()

    if request.method == 'GET':
        return deletion_confirmation_page(slug)

    confirmation = request.form.get('confirmation', '')
    acknowledge = request.form.get('acknowledge', '')

    if acknowledge != 'yes':
        abort(400, description='Debe aceptar la eliminacion irreversible')

    if confirmation != slug:
        abort(400, description='El codigo de confirmacion no coincide')

    try:
        delete_entity_safely(
            slug=slug,
            confirmation=confirmation,
            actor=str(session['admin'])
        )
    except ValueError:
        abort(400, description='No se ha podido validar la eliminacion')
    except Exception:
        import logging
        logging.exception('Error durante la eliminacion de entidad')
        abort(500, description='No se ha completado la eliminacion')

    flash('Entidad eliminada correctamente')
    return redirect(url_for('index'))
