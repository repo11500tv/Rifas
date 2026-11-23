"""Compra de participaciones mediante creditos."""

from html import escape
import sqlite3

from flask import (
    Blueprint, abort, flash, redirect,
    request, session, url_for
)

from platform_app.entity_routes import (
    edb, get_entity, layout, token
)
from platform_app.participant_routes import member_only

bp = Blueprint(
    "participant_raffle_purchases",
    __name__,
    url_prefix="/e/<slug>/participantes/sorteos"
)


def money(cents):
    return f"{cents / 100:.2f}"


def active_entity(slug):
    entity = get_entity(slug)
    if entity["status"] != "active":
        abort(403)
    return entity



def account_navigation(slug):
    return (
        '<div class="card">'
        '<a href="' +
        escape(url_for(
            "participants.account",
            slug=slug
        ), quote=True) +
        '">← Volver a Mi cuenta</a>'
        '</div>'
    )


@bp.get("/")
@member_only
def list_raffles(slug):
    entity = active_entity(slug)
    participant_id = session["participant_id"]

    with edb(slug) as db:
        balance = db.execute(
            "SELECT COALESCE(SUM(amount_cents),0) "
            "FROM credit_movements "
            "WHERE participant_id=?",
            (participant_id,)
        ).fetchone()[0]

        raffles = db.execute(
            "SELECT r.id,r.title,r.number_start,"
            "r.number_end,r.number_width,"
            "r.donation_cents,r.image_filename,r.extended_info,"
            "(SELECT COUNT(*) FROM raffle_numbers n "
            "WHERE n.raffle_id=r.id) AS sold "
            "FROM raffles r "
            "WHERE r.status='published' "
            "ORDER BY r.id DESC"
        ).fetchall()

    rows = []

    for r in raffles:
        available = (
            r["number_end"] -
            r["number_start"] + 1 -
            r["sold"]
        )

        photo_html = ""
        if r["image_filename"]:
            from platform_app.raffle_image_storage import valid_filename
            if valid_filename(r["image_filename"]):
                photo_url = url_for(
                    "entity.public_raffle_image",
                    slug=slug,
                    raffle_id=r["id"]
                )
                photo_html = (
                    '<img src="' + escape(photo_url, quote=True) +
                    '" alt="Fotografía del premio" '
                    'loading="lazy" '
                    'style="width:90px;height:75px;'
                    'object-fit:contain;border-radius:6px">'
                )

        info_html = ""
        if (r["extended_info"] or "").strip():
            info_url = url_for(
                "entity.public_raffle_information",
                slug=slug,
                raffle_id=r["id"]
            )
            info_html = (
                '<a href="' + escape(info_url, quote=True) +
                '">Más información</a> · '
            )

        detail_url = url_for(
            "participant_raffle_purchases.detail",
            slug=slug,
            raffle_id=r["id"]
        )

        rows.append(
            "<tr><td>" + photo_html + "</td><td>" +
            escape(r["title"]) +
            "</td><td>" +
            str(available) +
            "</td><td>" +
            money(r["donation_cents"]) +
            " creditos</td><td>" +
            info_html +
            '<a href="' + escape(detail_url, quote=True) +
            '">Elegir números</a></td></tr>'
        )

    body = (
        '<div class="card">'
        '<h2>Sorteos disponibles</h2>'
        '<p>Saldo: <strong>' +
        money(balance) +
        ' creditos</strong></p>'
        '<table><tr><th>Fotografía</th><th>Sorteo</th>'
        '<th>Disponibles</th>'
        '<th>Donativo por numero</th>'
        '<th>Accion</th></tr>' +
        "".join(rows) +
        '</table>'
        '</div>'
    )

    if not raffles:
        body += (
            '<div class="card">'
            '<p>No hay sorteos publicados '
            'en este momento.</p></div>'
        )

    return layout(
        "Comprar participaciones - " +
        entity["name"],
        account_navigation(slug) + body
    )


@bp.get("/<int:raffle_id>")
@member_only
def detail(slug, raffle_id):
    active_entity(slug)
    participant_id = session["participant_id"]

    with edb(slug) as db:
        raffle = db.execute(
            "SELECT * FROM raffles "
            "WHERE id=? AND status='published'",
            (raffle_id,)
        ).fetchone()

        if raffle is None:
            abort(404)


        sold = {
            row["number"]
            for row in db.execute(
                "SELECT number FROM raffle_numbers "
                "WHERE raffle_id=?",
                (raffle_id,)
            )
        }

        balance = db.execute(
            "SELECT COALESCE(SUM(amount_cents),0) "
            "FROM credit_movements "
            "WHERE participant_id=?",
            (participant_id,)
        ).fetchone()[0]

    number_start = raffle["number_start"]
    number_end = raffle["number_end"]
    number_width = raffle["number_width"]
    total_numbers = number_end - number_start + 1

    if total_numbers > 1000:
        return layout(
            "Seleccion de numeros",
            account_navigation(slug) +
            '<div class="card">'
            '<h2>Sorteo de gran numeracion</h2>'
            '<p>Proximamente: panel paginado.</p>'
            '</div>'
        )

    available_count = total_numbers - len(sold)

    options = []

    for n in range(number_start, number_end + 1):
        label = str(n).zfill(number_width)

        if n in sold:
            options.append(
                '<label class="raffle-number sold">'
                '<span>' + label + '</span>'
                '</label>'
            )
        else:
            options.append(
                '<label class="raffle-number available">'
                '<input type="checkbox" '
                'name="numbers" value="' + str(n) + '">'
                '<span>' + label + '</span>'
                '</label>'
            )

    options = "".join(options)

    panel_style = """
    <style>
    .raffle-summary {
        display:flex;
        flex-wrap:wrap;
        gap:12px;
        margin:15px 0;
    }
    .raffle-summary div {
        padding:12px;
        border:1px solid #ddd;
        border-radius:8px;
        flex:1;
        min-width:95px;
        text-align:center;
    }
    .raffle-grid {
        display:grid;
        grid-template-columns:repeat(10,minmax(0,1fr));
        gap:5px;
        margin:18px 0;
    }
    .raffle-number {
        position:relative;
        display:flex;
        justify-content:center;
        align-items:center;
        min-height:38px;
        border-radius:5px;
        font-size:13px;
        font-weight:600;
        border:1px solid #76b48d;
        background:#d7f2e3;
        color:#263a30;
        cursor:pointer;
    }
    .raffle-number input {
        position:absolute;
        opacity:0;
        width:100%;
        height:100%;
        margin:0;
        cursor:pointer;
    }
    .raffle-number.available:has(input:checked) {
        background:#fce8b9;
        border-color:#d6a44b;
    }
    .raffle-number.sold {
        background:#f5caca;
        border-color:#d28a8a;
        cursor:not-allowed;
    }
    .raffle-legend {
        display:flex;
        flex-wrap:wrap;
        gap:12px;
        font-size:13px;
    }
    .raffle-legend span {
        display:inline-flex;
        align-items:center;
        gap:5px;
    }
    .raffle-dot {
        display:inline-block;
        width:13px;
        height:13px;
        border-radius:3px;
        border:1px solid #999;
    }
    @media(max-width:500px) {
        .raffle-grid {
            grid-template-columns:repeat(5,minmax(0,1fr));
        }
    }
    </style>
    """

    legend = (
        '<div class="raffle-legend">'
        '<span><i class="raffle-dot" '
        'style="background:#d7f2e3"></i>Disponible</span>'
        '<span><i class="raffle-dot" '
        'style="background:#fce8b9"></i>Seleccionado</span>'
        '<span><i class="raffle-dot" '
        'style="background:#f5caca"></i>Asignado</span>'
        '</div>'
    )

    summary = (
        '<div class="raffle-summary">'
        '<div><strong>' + str(total_numbers) +
        '</strong><br>Total</div>'
        '<div><strong>' + str(available_count) +
        '</strong><br>Disponibles</div>'
        '<div><strong>' + str(len(sold)) +
        '</strong><br>Asignados</div>'
        '<div><strong id="selected-count">0</strong>'
        '<br>Seleccionados</div>'
        '</div>'
    )

    panel_script = """
    <script>
    (function(){
        const form = document.getElementById("raffle-buy-form");
        if (!form) return;
        const checks = form.querySelectorAll(
            'input[name="numbers"]'
        );
        const counter = document.getElementById("selected-count");
        const total = document.getElementById("selected-total");
        const price = Number(form.dataset.price);

        function update(){
            let count = 0;
            checks.forEach(function(c){
                if(c.checked) count++;
            });
            counter.textContent = count;
            total.textContent = (
                (count * price) / 100
            ).toFixed(2).replace(".", ",");
        }

        checks.forEach(function(c){
            c.addEventListener("change", update);
        });
        update();
    })();
    </script>
    """

    action = url_for(
        "participant_raffle_purchases.confirm",
        slug=slug,
        raffle_id=raffle_id
    )

    photo_html = ""
    if raffle["image_filename"]:
        from platform_app.raffle_image_storage import valid_filename
        if valid_filename(raffle["image_filename"]):
            photo_url = url_for(
                "entity.public_raffle_image",
                slug=slug,
                raffle_id=raffle_id
            )
            photo_html = (
                '<p><img src="' + escape(photo_url, quote=True) +
                '" alt="Fotografía del premio" '
                'style="max-width:100%;max-height:400px;'
                'object-fit:contain;border-radius:8px"></p>'
            )

    description_html = ""
    if raffle["description"]:
        description_html = (
            '<p style="white-space:pre-wrap">' +
            escape(raffle["description"]) +
            '</p>'
        )

    info_html = ""
    if (raffle["extended_info"] or "").strip():
        info_url = url_for(
            "entity.public_raffle_information",
            slug=slug,
            raffle_id=raffle_id
        )
        info_html = (
            '<p><a href="' + escape(info_url, quote=True) +
            '">Más información sobre este sorteo</a></p>'
        )

    body = (
        panel_style +
        '<div class="card">'
        '<h2>' + escape(raffle["title"]) + '</h2>' +
        photo_html + description_html + info_html +
        summary + legend +
        '<div style="margin-top:15px"></div>'
        '<p>Donativo por numero: <strong>' +
        money(raffle["donation_cents"]) +
        ' creditos</strong></p>'
        '<p>Saldo disponible: <strong>' +
        money(balance) +
        ' creditos</strong></p>'
        '<p>Selecciona los numeros que deseas '
        'adquirir.</p>'
        '<form id="raffle-buy-form" data-price="' +
        str(raffle["donation_cents"]) +
        '" method="post" action="' +
        escape(action, quote=True) + '">'
        '<input type="hidden" name="_csrf" value="' +
        escape(str(token()), quote=True) + '">'
        '<div class="raffle-grid">' + options + '</div>'
        '<p><strong>Importe seleccionado: '
        '<span id="selected-total">0,00</span> '
        'creditos</strong></p>'
        '<p><button type="submit">'
        'Revisar compra'
        '</button></p>'
        '</form></div>' +
        panel_script
    )

    return layout(
        "Comprar participaciones",
        account_navigation(slug) + body
    )



@bp.post("/<int:raffle_id>/confirmar")
@member_only
def confirm(slug, raffle_id):
    active_entity(slug)
    participant_id = session["participant_id"]

    raw = request.form.getlist("numbers")

    if not raw or len(raw) > 100:
        abort(400)

    try:
        numbers = [int(value) for value in raw]
    except (ValueError, TypeError):
        abort(400)

    if len(set(numbers)) != len(numbers):
        abort(400)

    numbers.sort()

    with edb(slug) as db:
        raffle = db.execute(
            "SELECT * FROM raffles "
            "WHERE id=? AND status='published'",
            (raffle_id,)
        ).fetchone()

        if raffle is None:
            abort(404)

        price = raffle["donation_cents"]

        if price <= 0:
            abort(400)

        if any(
            n < raffle["number_start"] or
            n > raffle["number_end"]
            for n in numbers
        ):
            abort(400)

        occupied = db.execute(
            "SELECT number FROM raffle_numbers "
            "WHERE raffle_id=? AND number IN (" +
            ",".join("?" for _ in numbers) + ")",
            (raffle_id, *numbers)
        ).fetchall()

        if occupied:
            flash(
                "Alguno de los numeros seleccionados "
                "ya no esta disponible."
            )
            return redirect(url_for(
                "participant_raffle_purchases.detail",
                slug=slug,
                raffle_id=raffle_id
            ))

        balance = db.execute(
            "SELECT COALESCE(SUM(amount_cents),0) "
            "FROM credit_movements "
            "WHERE participant_id=?",
            (participant_id,)
        ).fetchone()[0]

    total = len(numbers) * price

    if balance < total:
        flash("Saldo insuficiente.")
        return redirect(url_for(
            "participant_raffle_purchases.detail",
            slug=slug,
            raffle_id=raffle_id
        ))

    formatted = ", ".join(
        str(n).zfill(raffle["number_width"])
        for n in numbers
    )

    hidden_numbers = "".join(
        '<input type="hidden" name="numbers" value="' +
        str(n) + '">'
        for n in numbers
    )

    action = url_for(
        "participant_raffle_purchases.buy",
        slug=slug,
        raffle_id=raffle_id
    )

    cancel = url_for(
        "participant_raffle_purchases.detail",
        slug=slug,
        raffle_id=raffle_id
    )

    body = (
        '<div class="card">'
        '<h2>Confirmar compra</h2>'
        '<p><strong>Sorteo:</strong> ' +
        escape(raffle["title"]) + '</p>'
        '<p><strong>Numeros:</strong> ' +
        escape(formatted) + '</p>'
        '<p><strong>Cantidad:</strong> ' +
        str(len(numbers)) + '</p>'
        '<p><strong>Donativo por numero:</strong> ' +
        money(price) + ' creditos</p>'
        '<p><strong>Total:</strong> ' +
        money(total) + ' creditos</p>'
        '<p><strong>Saldo disponible:</strong> ' +
        money(balance) + ' creditos</p>'
        '<p><strong>Saldo despues de comprar:</strong> ' +
        money(balance - total) + ' creditos</p>'
        '<p>Comprueba los datos antes de continuar.</p>'
        '<form method="post" action="' +
        escape(action, quote=True) + '">'
        '<input type="hidden" name="_csrf" value="' +
        escape(str(token()), quote=True) + '">' +
        hidden_numbers +
        '<p><button type="submit">'
        'Confirmar compra'
        '</button></p>'
        '</form>'
        '<p><a href="' +
        escape(cancel, quote=True) +
        '">Cancelar y volver a seleccionar</a></p>'
        '</div>'
    )

    return layout(
        "Confirmar compra",
        account_navigation(slug) + body
    )


@bp.post("/<int:raffle_id>/comprar")
@member_only
def buy(slug, raffle_id):
    active_entity(slug)
    participant_id = session["participant_id"]

    raw = request.form.getlist("numbers")

    if not raw or len(raw) > 100:
        abort(400)

    try:
        numbers = [int(value) for value in raw]
    except (ValueError, TypeError):
        abort(400)

    if len(set(numbers)) != len(numbers):
        abort(400)

    with edb(slug) as db:
        db.execute("PRAGMA foreign_keys=ON")

        try:
            db.execute("BEGIN IMMEDIATE")

            raffle = db.execute(
                "SELECT * FROM raffles "
                "WHERE id=? AND status='published'",
                (raffle_id,)
            ).fetchone()

            if raffle is None:
                db.rollback()
                abort(404)

            price = raffle["donation_cents"]

            if price <= 0:
                db.rollback()
                abort(400)

            if any(
                n < raffle["number_start"] or
                n > raffle["number_end"]
                for n in numbers
            ):
                db.rollback()
                abort(400)

            participant = db.execute(
                "SELECT id FROM participants "
                "WHERE id=? AND active=1 "
                "AND email_verified=1",
                (participant_id,)
            ).fetchone()

            if participant is None:
                db.rollback()
                abort(403)

            occupied = db.execute(
                "SELECT number FROM raffle_numbers "
                "WHERE raffle_id=? AND number IN (" +
                ",".join("?" for _ in numbers) + ")",
                (raffle_id, *numbers)
            ).fetchall()

            if occupied:
                db.rollback()
                flash(
                    "Alguno de los numeros ya no "
                    "esta disponible."
                )
                return redirect(url_for(
                    "participant_raffle_purchases.detail",
                    slug=slug,
                    raffle_id=raffle_id
                ))

            total = len(numbers) * price

            balance = db.execute(
                "SELECT COALESCE(SUM(amount_cents),0) "
                "FROM credit_movements "
                "WHERE participant_id=?",
                (participant_id,)
            ).fetchone()[0]

            if balance < total:
                db.rollback()
                flash("Saldo insuficiente.")
                return redirect(url_for(
                    "participant_raffle_purchases.detail",
                    slug=slug,
                    raffle_id=raffle_id
                ))

            # Registrar compra antes del movimiento,
            # vinculando ambos dentro de la transaccion.
            import uuid
            reference = "BUY-" + uuid.uuid4().hex

            movement = db.execute(
                "INSERT INTO credit_movements "
                "(participant_id,amount_cents,"
                "movement_type,reference,notes) "
                "VALUES (?,?,'consume',?,?)",
                (
                    participant_id,
                    -total,
                    reference,
                    "Sorteo #" + str(raffle_id) +
                    ": " + raffle["title"] +
                    ". Numeros: " +
                    ", ".join(
                        str(n).zfill(
                            raffle["number_width"]
                        )
                        for n in numbers
                    )
                )
            )

            purchase = db.execute(
                "INSERT INTO raffle_purchases "
                "(raffle_id,participant_id,quantity,"
                "unit_price_cents,total_cents,"
                "credit_movement_id) "
                "VALUES (?,?,?,?,?,?)",
                (
                    raffle_id,
                    participant_id,
                    len(numbers),
                    price,
                    total,
                    movement.lastrowid
                )
            )

            db.executemany(
                "INSERT INTO raffle_numbers "
                "(raffle_id,purchase_id,"
                "participant_id,number) "
                "VALUES (?,?,?,?)",
                [
                    (
                        raffle_id,
                        purchase.lastrowid,
                        participant_id,
                        n
                    )
                    for n in numbers
                ]
            )

            db.commit()

        except sqlite3.Error:
            db.rollback()
            raise

    flash("Compra realizada correctamente.")

    return redirect(url_for(
        "participant_raffle_purchases.my_purchases",
        slug=slug
    ))


@bp.get("/mis-participaciones")
@member_only
def my_purchases(slug):
    active_entity(slug)
    participant_id = session["participant_id"]

    with edb(slug) as db:
        purchases = db.execute(
            "SELECT p.id,p.raffle_id,p.created_at,"
            "p.quantity,p.total_cents,"
            "r.title,r.number_width,"
            "GROUP_CONCAT(n.number, ',') AS numbers "
            "FROM raffle_purchases p "
            "JOIN raffles r ON r.id=p.raffle_id "
            "JOIN raffle_numbers n ON n.purchase_id=p.id "
            "WHERE p.participant_id=? "
            "GROUP BY p.id "
            "ORDER BY p.id DESC",
            (participant_id,)
        ).fetchall()

    groups = {}

    for p in purchases:
        raffle_id = p["raffle_id"]

        if raffle_id not in groups:
            groups[raffle_id] = {
                "title": p["title"],
                "quantity": 0,
                "total": 0,
                "numbers": [],
                "rows": []
            }

        group = groups[raffle_id]

        numbers = sorted(
            int(n) for n in p["numbers"].split(",")
        )

        formatted = [
            str(n).zfill(p["number_width"])
            for n in numbers
        ]

        group["quantity"] += p["quantity"]
        group["total"] += p["total_cents"]
        group["numbers"].extend(numbers)

        group["rows"].append(
            "<tr><td>" +
            escape(str(p["created_at"])) +
            "</td><td>" +
            escape(", ".join(formatted)) +
            "</td><td>" +
            str(p["quantity"]) +
            "</td><td>" +
            money(p["total_cents"]) +
            "</td></tr>"
        )

        group["width"] = p["number_width"]

    body = (
        '<style>'
        '.raffle-summary{display:flex;flex-wrap:wrap;'
        'gap:18px;margin:12px 0}'
        '.raffle-summary div{padding:12px 18px;'
        'background:#eef6f0;border-radius:8px}'
        '.raffle-summary strong{display:block;'
        'font-size:22px;color:#17633b}'
        '.raffle-number-list{display:flex;'
        'flex-wrap:wrap;gap:8px;margin:12px 0 20px}'
        '.raffle-number-tag{display:inline-block;'
        'padding:8px 12px;border-radius:7px;'
        'background:#e5efe9;color:#17633b;'
        'font-weight:bold}'
        '</style>'
        '<div class="card">'
        '<h2>Mis participaciones</h2>'
        '<p>Participaciones agrupadas por sorteo.</p>'
        '</div>'
    )

    for group in groups.values():
        number_tags = "".join(
            '<span class="raffle-number-tag">' +
            escape(str(n).zfill(group["width"])) +
            '</span>'
            for n in sorted(group["numbers"])
        )

        body += (
            '<div class="card">'
            '<h3>' + escape(group["title"]) + '</h3>'
            '<div class="raffle-summary">'
            '<div>Participaciones adquiridas'
            '<strong>' + str(group["quantity"]) +
            '</strong></div>'
            '<div>Creditos utilizados'
            '<strong>' + money(group["total"]) +
            '</strong></div>'
            '</div>'
            '<h4>Mis numeros</h4>'
            '<div class="raffle-number-list">' +
            number_tags + '</div>'
            '<h4>Detalle de compras</h4>'
            '<table><tr><th>Fecha</th>'
            '<th>Numeros</th>'
            '<th>Cantidad</th>'
            '<th>Creditos</th></tr>' +
            "".join(group["rows"]) +
            '</table>'
            '</div>'
        )

    if not groups:
        body += (
            '<div class="card">'
            '<p>Todavia no tienes participaciones.'
            '</p></div>'
        )

    return layout(
        "Mis participaciones",
        account_navigation(slug) + body
    )
