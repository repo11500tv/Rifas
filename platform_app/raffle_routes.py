"""Módulo 2.2.0: gestión administrativa de sorteos por entidad."""
import html
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, abort, flash, redirect, request, url_for
from platform_app.entity_routes import edb, get_entity, layout, protected, token
from platform_app.raffle_image_storage import save_raffle_image, valid_filename

bp = Blueprint('raffles', __name__, url_prefix='/e/<slug>/admin/sorteos')
MAX_NUMBERS = 100000

ALLOWED_STATUS_TRANSITIONS = {
    'draft': {'draft', 'published'},
    'published': {'published', 'closed'},
    'closed': {'closed', 'published', 'finished'},
    'finished': {'finished'},
}

def status_transition_allowed(current, requested):
    return requested in ALLOWED_STATUS_TRANSITIONS.get(
        current, set()
    )


def esc(value):
    return html.escape(str(value), quote=True)

def _form(slug, raffle=None):
    editing = raffle is not None
    value = lambda key, default='': esc(raffle[key] if editing else default)
    action = url_for('raffles.edit', slug=slug, raffle_id=raffle['id']) if editing else url_for('raffles.create', slug=slug)
    status_labels = [
        ('draft', 'Borrador'),
        ('published', 'Publicado'),
        ('closed', 'Cerrado'),
        ('finished', 'Finalizado'),
    ]
    current_status = raffle['status'] if editing else None
    allowed = (
        ALLOWED_STATUS_TRANSITIONS[current_status]
        if editing else {'draft'}
    )
    opts = ''.join(
        f'<option value="{s}" '
        f'{"selected" if current_status == s else ""}>'
        f'{label}</option>'
        for s, label in status_labels
        if s in allowed
    )
    current_photo_html = ''
    if editing and valid_filename(raffle['image_filename']):
        photo_url = url_for(
            'raffles.admin_raffle_image',
            slug=slug,
            raffle_id=raffle['id']
        )
        current_photo_html = (
            '<p><strong>Fotografía actual:</strong></p>'
            '<p><img src="' + esc(photo_url) +
            '" alt="Fotografía actual del premio" '
            'style="max-width:100%;max-height:300px;'
            'object-fit:contain;border-radius:8px"></p>'
        )

    return f'''<div class="card"><h2>{'Editar sorteo' if editing else 'Nuevo sorteo'}</h2>
    <form method="post" enctype="multipart/form-data" action="{action}"><input type="hidden" name="_csrf" value="{token()}">
    <label>Título<input name="title" maxlength="150" required value="{value('title')}"></label>
    <label>Descripción<textarea name="description" maxlength="4000" rows="4">{value('description')}</textarea></label>
    <label>Premios<textarea name="prizes" maxlength="4000" rows="3">{value('prizes')}</textarea></label>
    <h3>Fotografía e información ampliada (opcional)</h3>
    {current_photo_html}
    <label>Fotografía del premio (JPEG, PNG o WebP; máximo 5 MB)
    <input type="file" name="raffle_image" accept="image/jpeg,image/png,image/webp"></label>
    {('<label><input type="checkbox" name="remove_raffle_image" value="1"> Eliminar fotografía actual</label>' if editing and valid_filename(raffle['image_filename']) else '')}
    <label>Información ampliada
    <textarea name="extended_info" maxlength="10000" rows="7">{value('extended_info')}</textarea></label>
    <p>Estos datos son opcionales. La página explicativa se generará automáticamente cuando exista información ampliada.</p>
    <label>Primer número (entero no negativo)<input type="number" name="number_start" min="0" max="999999999" required value="{value('number_start',0)}" {'readonly' if editing else ''}></label>
    <label>Último número<input type="number" name="number_end" min="0" max="999999999" required value="{value('number_end',99)}" {'readonly' if editing else ''}></label>
    <label>Dígitos para mostrar (ej.: 2 = 00–99)<input type="number" name="number_width" min="1" max="12" required value="{value('number_width',2)}" {'readonly' if editing else ''}></label>
    <label>Donativo por número (€)<input name="donation_eur" inputmode="decimal" required value="{(format(Decimal(raffle['donation_cents'])/100,'.2f') if editing else '1,00')}" {'readonly' if editing and raffle['sold_count'] else ''}></label>
    {'<p><strong>Precio bloqueado:</strong> este sorteo ya tiene participaciones vendidas.</p>' if editing and raffle['sold_count'] else ''}
    <label>Fecha del sorteo (opcional)<input type="datetime-local" name="draw_at" value="{value('draw_at')}"></label>
    <label>Estado<select name="status" {"disabled" if editing and current_status == "finished" else ""}>{opts}</select></label>{"<input type=hidden name=status value=finished>" if editing and current_status == "finished" else ""}
    <p>La numeración no puede modificarse después de crear el sorteo. Las compras se realizan con saldo disponible, sin reservas temporales. Los sorteos finalizados no pueden reabrirse.</p>
    <button>Guardar</button></form><p><a href="{url_for('raffles.list_raffles',slug=slug)}">Volver a sorteos</a></p></div>'''

def _parse(form, editing=False):
    title=form.get('title','').strip()
    description=form.get('description','').strip()
    prizes=form.get('prizes','').strip()
    extended_info=form.get('extended_info','').strip()
    status=form.get('status','draft')
    draw_at=form.get('draw_at','').strip()
    if not title or len(title)>150 or len(description)>4000 or len(prizes)>4000 or len(extended_info)>10000:
        raise ValueError('Revisa título, descripción y premios.')
    if status not in ('draft','published','closed','finished'):
        raise ValueError('Estado no válido.')
    if draw_at:
        try: datetime.strptime(draw_at,'%Y-%m-%dT%H:%M')
        except ValueError: raise ValueError('Fecha no válida.')
    try:
        euros=Decimal(form.get('donation_eur','').strip().replace(',','.'))
        cents=euros*100
        if not euros.is_finite() or euros<0 or euros>Decimal('1000000') or cents!=cents.to_integral_value(): raise ValueError()
        cents=int(cents)
    except (InvalidOperation, ValueError):
        raise ValueError('El donativo debe tener un máximo de dos decimales y ser no negativo.')
    data={'title':title,'description':description,'prizes':prizes,'extended_info':extended_info,'status':status,'draw_at':draw_at or None,'donation_cents':cents}
    if not editing:
        try:
            start=int(form.get('number_start',''))
            end=int(form.get('number_end',''))
            width=int(form.get('number_width',''))
        except ValueError: raise ValueError('Numeración no válida.')
        if start<0 or end<start or end>999999999 or end-start+1>MAX_NUMBERS or not 1<=width<=12 or len(str(end))>width:
            raise ValueError('Intervalo inválido: máximo 100.000 números y ancho suficiente.')
        data.update(number_start=start,number_end=end,number_width=width)
    return data


@bp.get('/<int:raffle_id>/fotografia')
@protected
def admin_raffle_image(slug, raffle_id):
    from flask import send_file
    from platform_app import ENTITIES

    with edb(slug) as con:
        raffle = con.execute(
            'SELECT image_filename FROM raffles WHERE id=?',
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
        max_age=0
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@bp.get('/')
@protected
def list_raffles(slug):
    ent = get_entity(slug)

    with edb(slug) as con:
        rows = con.execute(
            'SELECT * FROM raffles ORDER BY id DESC'
        ).fetchall()

    items = []

    for r in rows:
        detail_url = url_for(
            'raffles.detail',
            slug=slug,
            raffle_id=r['id']
        )

        photo_html = ''
        if valid_filename(r['image_filename']):
            photo_url = url_for(
                'raffles.admin_raffle_image',
                slug=slug,
                raffle_id=r['id']
            )
            photo_html = (
                '<img src="' + esc(photo_url) +
                '" alt="Fotografía del premio" '
                'loading="lazy" '
                'style="width:85px;height:70px;'
                'object-fit:contain;border-radius:6px">'
            )

        info_html = ''
        if (
            r['status'] == 'published'
            and (r['extended_info'] or '').strip()
        ):
            info_url = url_for(
                'entity.public_raffle_information',
                slug=slug,
                raffle_id=r['id']
            )
            info_html = (
                ' · <a href="' + esc(info_url) +
                '">Más información</a>'
            )

        items.append(
            '<tr><td>' + str(r['id']) +
            '</td><td>' + photo_html +
            '</td><td><a href="' + esc(detail_url) +
            '">' + esc(r['title']) + '</a>' +
            info_html +
            '</td><td>' + esc(r['status']) +
            '</td><td>' +
            str(r['number_end'] - r['number_start'] + 1) +
            '</td><td>' +
            f"{Decimal(r['donation_cents']) / 100:.2f}" +
            ' €</td></tr>'
        )

    body = (
        '<div class="card">'
        '<h2>Sorteos · ' + esc(ent['name']) + '</h2>'
        '<p><a href="' +
        esc(url_for('raffles.create', slug=slug)) +
        '">Crear sorteo</a> · <a href="' +
        esc(url_for('entity.admin', slug=slug)) +
        '">Panel de entidad</a></p>'
        '<table><tr><th>ID</th><th>Fotografía</th>'
        '<th>Título</th><th>Estado</th>'
        '<th>Números</th><th>Donativo</th></tr>' +
        ''.join(items) +
        '</table></div>'
    )

    return layout('Sorteos · ' + ent['name'], body)


@bp.route('/nuevo',methods=['GET','POST'])
@protected
def create(slug):
    if request.method=='POST':
        try: data=_parse(request.form)
        except ValueError as exc:
            flash(str(exc)); return redirect(url_for('raffles.create',slug=slug))
        if data['status'] != 'draft':
            flash('Los sorteos nuevos deben crearse como borrador. Configure la regla antes de publicar.')
            return redirect(url_for('raffles.create',slug=slug))
        from platform_app import ENTITIES

        uploaded = request.files.get('raffle_image')
        image_filename = None

        try:
            if uploaded and uploaded.filename:
                image_filename = save_raffle_image(
                    uploaded, ENTITIES / slug
                )

            with edb(slug) as con:
                cur=con.execute('''INSERT INTO raffles(title,description,prizes,extended_info,image_filename,number_start,number_end,number_width,donation_cents,draw_at,status,created_by)
                VALUES(:title,:description,:prizes,:extended_info,:image_filename,:number_start,:number_end,:number_width,:donation_cents,:draw_at,:status,:created_by)''',dict(data,created_by=request_user(),image_filename=image_filename))
                rid=cur.lastrowid

        except Exception as exc:
            if image_filename:
                (ENTITIES / slug / 'uploads' / 'sorteos' / image_filename).unlink(
                    missing_ok=True
                )
            flash('No se pudo crear el sorteo: ' + str(exc))
            return redirect(url_for('raffles.create',slug=slug))

        flash('Sorteo creado correctamente.')
        return redirect(url_for('raffles.detail',slug=slug,raffle_id=rid))
    return layout('Nuevo sorteo',_form(slug))

def request_user():
    from flask import session
    return session.get('entity_user','')

@bp.get('/<int:raffle_id>')
@protected
def detail(slug,raffle_id):
    with edb(slug) as con:
        r = con.execute(
            'SELECT * FROM raffles WHERE id=?',
            (raffle_id,)
        ).fetchone()

        if r is None:
            abort(404)

        sales = con.execute(
            "SELECT COUNT(*) AS sold,"
            "COUNT(DISTINCT participant_id) AS buyers "
            "FROM raffle_numbers WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()

        revenue = con.execute(
            "SELECT COALESCE(SUM(total_cents),0) "
            "FROM raffle_purchases WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()[0]

        assigned = con.execute(
            "SELECT n.number,p.name,p.email,"
            "n.created_at "
            "FROM raffle_numbers n "
            "JOIN participants p "
            "ON p.id=n.participant_id "
            "WHERE n.raffle_id=? "
            "ORDER BY n.number",
            (raffle_id,)
        ).fetchall()

    with edb(slug) as con:
        participant_sales = con.execute(
            "SELECT p.id,p.name,p.email,"
            "COUNT(rp.id) AS purchases,"
            "COALESCE(SUM(rp.quantity),0) AS quantity,"
            "COALESCE(SUM(rp.total_cents),0) AS amount "
            "FROM raffle_purchases rp "
            "JOIN participants p "
            "ON p.id=rp.participant_id "
            "WHERE rp.raffle_id=? "
            "GROUP BY p.id,p.name,p.email "
            "ORDER BY amount DESC,p.name",
            (raffle_id,)
        ).fetchall()

    start = r['number_start']
    end = r['number_end']
    width = r['number_width']

    total = end-start+1
    sold = sales['sold']
    available = total-sold
    buyers = sales['buyers']
    percentage = sold*100/total if total else 0

    # Mapa paginado: 100 numeros por pagina.
    try:
        page = int(request.args.get('pagina', '1'))
    except (ValueError, TypeError):
        page = 1

    pages = (total + 99) // 100
    page = max(1, min(page, pages))

    first = start + (page - 1) * 100
    last = min(end, first + 99)

    sold_map = {
        int(item['number']): item
        for item in assigned
    }

    number_cells = []

    for number in range(first, last + 1):
        item = sold_map.get(number)
        label = str(number).zfill(width)

        if item:
            tooltip = (
                'Vendido a ' + str(item['name']) +
                ' - ' + str(item['created_at'])
            )
            css = 'sold'
        else:
            tooltip = 'Disponible'
            css = 'available'

        number_cells.append(
            '<span class="admin-number ' + css +
            '" title="' + esc(tooltip) + '">' +
            esc(label) + '</span>'
        )

    page_links = []

    for n in range(1, pages + 1):
        if pages > 20 and abs(n-page) > 2 and n not in (1, pages):
            continue

        page_links.append(
            '<a href="' +
            esc(url_for(
                'raffles.detail',
                slug=slug,
                raffle_id=raffle_id,
                pagina=n
            )) +
            '">' + str(n) + '</a>'
            if n != page else '<strong>' + str(n) + '</strong>'
        )

    map_html = (
        '<div class="card">'
        '<h3>Mapa de numeros</h3>'
        '<p><span style="color:#17633b">■</span> '
        'Disponible &nbsp; '
        '<span style="color:#982f2f">■</span> '
        'Vendido</p>'
        '<p>Mostrando ' +
        esc(str(first).zfill(width)) + ' a ' +
        esc(str(last).zfill(width)) + '</p>'
        '<div class="admin-number-grid">' +
        ''.join(number_cells) + '</div>'
        '<p>Paginas: ' + ' | '.join(page_links) +
        '</p>'
        '<p>Coloca el cursor sobre un numero vendido '
        'para consultar su titular.</p>'
        '</div>'
    )

    preview = ', '.join(
        str(n).zfill(width)
        for n in range(start,min(end+1,start+30))
    )

    if total > 30:
        preview += ' ...'

    number_rows = ''.join(
        '<tr><td>' +
        esc(str(n['number']).zfill(width)) +
        '</td><td>' +
        esc(n['name']) +
        '</td><td>' +
        esc(n['email']) +
        '</td><td>' +
        esc(n['created_at']) +
        '</td></tr>'
        for n in assigned
    )

    photo_html = ''
    if valid_filename(r['image_filename']):
        photo_url = url_for(
            'raffles.admin_raffle_image',
            slug=slug,
            raffle_id=raffle_id
        )
        photo_html = (
            '<p><img src="' + esc(photo_url) +
            '" alt="Fotografía del premio" '
            'style="max-width:100%;max-height:420px;'
            'object-fit:contain;border-radius:8px"></p>'
        )

    extended_html = ''
    if (r['extended_info'] or '').strip():
        extended_html = (
            '<h3>Información ampliada</h3>'
            '<p style="white-space:pre-wrap">' +
            esc(r['extended_info']) +
            '</p>'
        )

        if r['status'] == 'published':
            public_url = url_for(
                'entity.public_raffle_information',
                slug=slug,
                raffle_id=raffle_id
            )
            extended_html += (
                '<p><a href="' + esc(public_url) +
                '">Ver página pública de información</a></p>'
            )

    body = (
        '<style>'
        '.raffle-stats{display:grid;'
        'grid-template-columns:repeat(3,minmax(0,1fr));'
        'gap:12px;margin:16px 0}'
        '.raffle-stat{background:#eef6f0;'
        'padding:15px;border-radius:9px}'
        '.raffle-stat strong{display:block;'
        'font-size:25px;color:#17633b}'
        '@media(max-width:650px){'
        '.raffle-stats{grid-template-columns:'
        'repeat(2,minmax(0,1fr))}}'
        '.admin-number-grid{display:grid;'
        'grid-template-columns:repeat(10,minmax(0,1fr));'
        'gap:5px;margin:14px 0}'
        '.admin-number{display:block;text-align:center;'
        'padding:9px 2px;border-radius:5px;'
        'font-size:13px;font-weight:600}'
        '.admin-number.available{background:#dcefe2;'
        'color:#17633b}'
        '.admin-number.sold{background:#f4d5d5;'
        'color:#982f2f}'
        '@media(max-width:550px){'
        '.admin-number-grid{grid-template-columns:'
        'repeat(5,minmax(0,1fr))}}'
        '</style>'
        '<div class="card">'
        '<h2>' + esc(r['title']) + '</h2>' +
        photo_html + extended_html +
        '<p><strong>Estado:</strong> ' +
        esc(r['status']) + '</p>'
        '<p><strong>Descripcion:</strong> ' +
        esc(r['description']) + '</p>'
        '<p><strong>Premios:</strong> ' +
        esc(r['prizes']) + '</p>'
        '<p><strong>Numeracion:</strong> ' +
        esc(str(start).zfill(width)) +
        ' a ' + esc(str(end).zfill(width)) +
        ' (' + str(total) + ' numeros)</p>'
        '<p><strong>Donativo por numero:</strong> ' +
        f"{Decimal(r['donation_cents'])/100:.2f}" +
        ' euros</p>'
        '<p><strong>Fecha prevista:</strong> ' +
        esc(r['draw_at'] or 'Sin definir') +
        '</p>'
        '<p><a href="' +
        url_for('raffles.edit',slug=slug,raffle_id=raffle_id) +
        '">Editar sorteo</a> | '
        '<a href="' +
        url_for('raffle_draw_rules.configure',slug=slug,raffle_id=raffle_id) +
        '">Regla de adjudicación</a> | '
        '<a href="' +
        url_for('raffle_draw_results.result',slug=slug,raffle_id=raffle_id) +
        '">Resultado y adjudicación</a> | '
        '<a href="' +
        url_for('raffles.list_raffles',slug=slug) +
        '">Volver a sorteos</a></p>'
        '</div>'

        '<div class="card">'
        '<h3>Resumen de ventas</h3>'
        '<div class="raffle-stats">'
        '<div class="raffle-stat">Total numeros'
        '<strong>' + str(total) + '</strong></div>'
        '<div class="raffle-stat">Vendidos'
        '<strong>' + str(sold) + '</strong></div>'
        '<div class="raffle-stat">Disponibles'
        '<strong>' + str(available) + '</strong></div>'
        '<div class="raffle-stat">Porcentaje vendido'
        '<strong>' + f'{percentage:.1f}%' +
        '</strong></div>'
        '<div class="raffle-stat">Recaudacion'
        '<strong>' + f'{revenue/100:.2f}' +
        ' euros</strong></div>'
        '<div class="raffle-stat">Participantes'
        '<strong>' + str(buyers) + '</strong></div>'
        '</div>'
        '</div>'

        '<div class="card">'
        '<h3>Numeros vendidos y titulares</h3>'
        '<table><tr><th>Numero</th>'
        '<th>Participante</th><th>Correo</th>'
        '<th>Fecha</th></tr>' +
        number_rows +
        '</table>'
        '</div>'
    )

    if not assigned:
        body += (
            '<div class="card">'
            '<p>Todavia no hay participaciones '
            'vendidas.</p></div>'
        )

    report_rows = []

    for item in participant_sales:
        numbers = sorted(
            n['number']
            for n in assigned
            if n['email'] == item['email']
        )

        number_text = ', '.join(
            str(number).zfill(width)
            for number in numbers
        )

        report_rows.append(
            '<tr><td>' + esc(item['name']) +
            '</td><td>' + str(item['purchases']) +
            '</td><td>' + str(item['quantity']) +
            '</td><td>' + esc(number_text) +
            '</td><td>' +
            f"{item['amount']/100:.2f}" +
            ' euros</td></tr>'
        )

    report_html = (
        '<div class="card">'
        '<h3>Ventas por participante</h3>'
        '<div style="overflow-x:auto">'
        '<table>'
        '<tr><th>Participante</th>'
        '<th>Compras</th>'
        '<th>Cantidad</th>'
        '<th>Numeros adquiridos</th>'
        '<th>Aportacion</th></tr>' +
        ''.join(report_rows) +
        '</table></div>'
        '</div>'
    )

    if not participant_sales:
        report_html = (
            '<div class="card">'
            '<h3>Ventas por participante</h3>'
            '<p>Todavia no hay ventas.</p>'
            '</div>'
        )

    body += report_html

    body += map_html

    return layout('Detalle de sorteo',body)

@bp.route('/<int:raffle_id>/editar',methods=['GET','POST'])
@protected
def edit(slug,raffle_id):
    with edb(slug) as con:
        r=con.execute(
            'SELECT r.*,'
            '(SELECT COUNT(*) FROM raffle_numbers n '
            'WHERE n.raffle_id=r.id) AS sold_count '
            'FROM raffles r WHERE r.id=?',
            (raffle_id,)
        ).fetchone()
    if r is None: abort(404)
    if request.method=='POST':
        try: data=_parse(request.form,editing=True)
        except ValueError as exc:
            flash(str(exc)); return redirect(url_for('raffles.edit',slug=slug,raffle_id=raffle_id))
        from platform_app import ENTITIES

        uploaded = request.files.get('raffle_image')
        remove_image = request.form.get('remove_raffle_image') == '1'

        if remove_image and uploaded and uploaded.filename:
            flash('No puedes subir y eliminar una fotografía simultáneamente.')
            return redirect(url_for('raffles.edit',slug=slug,raffle_id=raffle_id))

        new_image = None
        previous_image = None
        cleanup_previous = False

        try:
            if uploaded and uploaded.filename:
                new_image = save_raffle_image(
                    uploaded, ENTITIES / slug
                )
        except (ValueError, OSError) as exc:
            flash('Fotografía no válida: ' + str(exc))
            return redirect(url_for('raffles.edit',slug=slug,raffle_id=raffle_id))

        try:
            with edb(slug) as con:
                con.execute('BEGIN IMMEDIATE')
                current = con.execute(
                    'SELECT donation_cents, status, image_filename '
                    'FROM raffles WHERE id=?',
                    (raffle_id,)
                ).fetchone()

                if current is None:
                    abort(404)

                sold = con.execute(
                    'SELECT COUNT(*) FROM raffle_numbers WHERE raffle_id=?',
                    (raffle_id,)
                ).fetchone()[0]

                error = None

                if sold and data['donation_cents'] != current['donation_cents']:
                    error = (
                        'No se puede cambiar el precio: '
                        'existen participaciones vendidas.'
                    )

                elif (
                    current['status'] == 'draft'
                    and data['status'] == 'published'
                ):
                    configured = con.execute(
                        'SELECT 1 FROM raffle_draw_rules WHERE raffle_id=?',
                        (raffle_id,)
                    ).fetchone()

                    if configured is None:
                        error = (
                            'Antes de publicar debe configurar '
                            'la regla de adjudicación.'
                        )

                if not error and not status_transition_allowed(
                    current['status'], data['status']
                ):
                    error = (
                        'Cambio de estado no permitido: '
                        + current['status'] + ' a ' + data['status']
                    )

                if not error:
                    image_filename = current['image_filename']

                    if remove_image:
                        image_filename = None
                    elif new_image:
                        image_filename = new_image

                    if image_filename != current['image_filename']:
                        previous_image = current['image_filename']
                        cleanup_previous = bool(previous_image)

                    con.execute(
                        """UPDATE raffles SET
                            title=:title,
                            description=:description,
                            prizes=:prizes,
                            extended_info=:extended_info,
                            image_filename=:image_filename,
                            donation_cents=:donation_cents,
                            draw_at=:draw_at,
                            status=:status,
                            updated_at=CURRENT_TIMESTAMP
                           WHERE id=:raffle_id""",
                        dict(
                            data,
                            raffle_id=raffle_id,
                            image_filename=image_filename
                        )
                    )

            if error:
                if new_image:
                    (ENTITIES / slug / 'uploads' / 'sorteos' / new_image).unlink(
                        missing_ok=True
                    )
                flash(error)
                return redirect(url_for(
                    'raffles.edit',
                    slug=slug,
                    raffle_id=raffle_id
                ))

        except BaseException:
            if new_image:
                (ENTITIES / slug / 'uploads' / 'sorteos' / new_image).unlink(
                    missing_ok=True
                )
            raise

        if cleanup_previous:
            try:
                from platform_app.raffle_image_cleanup import (
                    cleanup_unreferenced_image
                )
                cleanup_unreferenced_image(
                    ENTITIES / slug,
                    previous_image
                )
            except (OSError, ValueError, sqlite3.Error):
                import logging
                logging.getLogger(__name__).exception(
                    'No se pudo limpiar la fotografia anterior '
                    'del sorteo %s de la entidad %s',
                    raffle_id, slug
                )

        flash('Sorteo actualizado.')
        return redirect(url_for('raffles.detail',slug=slug,raffle_id=raffle_id))
    return layout('Editar sorteo',_form(slug,r))
