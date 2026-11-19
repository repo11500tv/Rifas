"""Acta PDF de sorteos definitivos de Rifas Benéficas 2.x.

Integración: registrar bp en create_app() después de los demás blueprints.
No escribe en bases de datos ni almacena PDFs en disco.
"""
from io import BytesIO
from pathlib import Path
import sqlite3
from xml.sax.saxutils import escape

from flask import Blueprint, abort, send_file
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

from platform_app.entity_routes import get_entity, protected

bp = Blueprint('raffle_acta_pdf', __name__, url_prefix='/e/<slug>/admin/sorteos')


def _text(value, default='No consta'):
    if value is None or str(value).strip() == '':
        value = default
    return escape(str(value)).replace('\n', '<br/>')


def _money(cents):
    return f'{int(cents or 0) / 100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') + ' €'


def _read_data(slug, raffle_id):
    """Una única transacción de lectura para evitar datos incoherentes."""
    from platform_app import ENTITIES
    # get_entity() comprueba que el slug existe en el registro central.
    entity = get_entity(slug)
    if entity['status'] != 'active':
        abort(403)
    path = Path(ENTITIES) / slug / 'data' / 'rifas.sqlite3'
    # URI con modo ro: la generación no puede escribir accidentalmente.
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.execute('BEGIN')
        raffle = con.execute('SELECT * FROM raffles WHERE id=?', (raffle_id,)).fetchone()
        if raffle is None:
            abort(404)
        if raffle['status'] != 'finished':
            abort(409, 'El acta definitiva exige un sorteo finalizado.')
        rule = con.execute('SELECT * FROM raffle_draw_rules WHERE raffle_id=?', (raffle_id,)).fetchone()
        result = con.execute('SELECT * FROM raffle_draw_results WHERE raffle_id=?', (raffle_id,)).fetchone()
        if rule is None or result is None:
            abort(409, 'No consta un resultado definitivo con regla de adjudicación.')
        winner = None
        if result['outcome'] == 'winner':
            winner = con.execute('SELECT id,name FROM participants WHERE id=?',
                                 (result['winning_participant_id'],)).fetchone()
        delivery = con.execute('SELECT * FROM prize_deliveries WHERE draw_result_id=?',
                               (result['id'],)).fetchone()
        admin = con.execute('SELECT username FROM entity_admins WHERE id=?',
                            (result['recorded_by'],)).fetchone()
        totals = con.execute('''SELECT COUNT(*) AS purchases,
            COALESCE(SUM(quantity),0) AS numbers,
            COALESCE(SUM(total_cents),0) AS amount
            FROM raffle_purchases WHERE raffle_id=?''', (raffle_id,)).fetchone()
        con.execute('COMMIT')
        return dict(entity), dict(raffle), dict(rule), dict(result), (
            dict(winner) if winner else None), (dict(delivery) if delivery else None), (
            dict(admin) if admin else None), dict(totals)
    finally:
        con.close()


def _render_pdf(data):
    entity, raffle, rule, result, winner, delivery, admin, totals = data
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=22*mm,
                            rightMargin=22*mm, topMargin=19*mm,
                            bottomMargin=19*mm, title='Acta de resultado definitivo de sorteo')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ActaHeadingCustom', parent=styles['Heading1'],
                              alignment=TA_CENTER, fontSize=14, leading=18, spaceAfter=12))
    styles.add(ParagraphStyle(name='ActaTextCustom', parent=styles['Normal'],
                              leading=14, spaceAfter=5))
    styles.add(ParagraphStyle(name='ActaSectionCustom', parent=styles['Heading2'],
                              fontSize=10.5, spaceBefore=11, spaceAfter=6))
    def p(label, value):
        return Paragraph(f'<b>{_text(label)}:</b> {_text(value)}', styles['ActaTextCustom'])
    story = [Paragraph('ACTA DE RESULTADO DEFINITIVO DE SORTEO BENÉFICO',
                       styles['ActaHeadingCustom']),
             Paragraph(_text(entity.get('public_name') or entity['name']),
                       styles['ActaHeadingCustom']),
             Paragraph('Identificación del sorteo', styles['ActaSectionCustom']),
             p('Identificador', raffle['id']), p('Sorteo', raffle['title']),
             p('Premios', raffle['prizes']), p('Fecha prevista', raffle['draw_at']),
             p('Donativo por número', _money(raffle['donation_cents'])),
             p('Numeración', f"{str(raffle['number_start']).zfill(raffle['number_width'])}–{str(raffle['number_end']).zfill(raffle['number_width'])}"),
             Paragraph('Regla y resultado externo', styles['ActaSectionCustom']),
             p('Organismo externo', rule['external_organizer']),
             p('Sorteo externo', rule['external_draw']),
             p('Regla aplicada', rule['rule_description']),
             p('Resultado comunicado', result['official_result']),
             p('Fuente indicada', result['official_source']),
             p('Fecha del sorteo externo', result['official_draw_at']),
             p('Número ganador', str(result['winning_number']).zfill(raffle['number_width'])),
             p('Adjudicación', 'Premio adjudicado' if result['outcome'] == 'winner' else 'Premio desierto'),
             p('Participante adjudicatario', winner['name'] if winner else 'No corresponde'),
             Paragraph('Resumen económico de compras confirmadas', styles['ActaSectionCustom'])]
    rows = [['Concepto', 'Total'],
            ['Operaciones de compra', str(totals['purchases'])],
            ['Números adquiridos', str(totals['numbers'])],
            ['Importe de compras confirmadas', _money(totals['amount'])]]
    table = Table(rows, colWidths=[104*mm, 58*mm], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,0), colors.HexColor('#17365a')),
        ('TEXTCOLOR', (0,0),(-1,0), colors.white),
        ('FONTNAME', (0,0),(-1,0), 'Helvetica-Bold'),
        ('GRID',(0,0),(-1,-1),0.4,colors.lightgrey),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('TOPPADDING',(0,0),(-1,-1),7),
        ('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.extend([table, Paragraph('Notificación y entrega del premio', styles['ActaSectionCustom'])])
    if result['outcome'] == 'void':
        story.append(p('Estado', 'No corresponde: premio desierto'))
    else:
        story.extend([
            p('Notificación', 'Notificado' if delivery and delivery['notification_status'] == 'notified' else 'Pendiente o no registrada'),
            p('Entrega', 'Entregado' if delivery and delivery['delivery_status'] == 'delivered' else 'Pendiente o no registrada'),
            p('Fecha de entrega', delivery['delivered_at'] if delivery else None),
            p('Observaciones de entrega', delivery['delivery_notes'] if delivery else None)])
    story.extend([
        Paragraph('Registro y validación', styles['ActaSectionCustom']),
        p('Administrador que registró el resultado', admin['username'] if admin else None),
        p('Fecha de registro del resultado', result['recorded_at']),
        Spacer(1, 8*mm),
        Paragraph('Responsable de la entidad: ____________________________________', styles['ActaTextCustom']),
        Spacer(1, 5*mm),
        Paragraph('Firma: __________________________  Fecha: __________________', styles['ActaTextCustom']),
        Spacer(1, 8*mm),
        Paragraph('El resultado externo fue introducido por un administrador y no se verifica automáticamente con el organismo emisor. Este documento requiere revisión y firma del responsable; por sí solo no acredita la celebración del sorteo ni la recepción del premio.', styles['ActaTextCustom'])])
    doc.build(story)
    buf.seek(0)
    return buf


@bp.get('/<int:raffle_id>/acta.pdf')
@protected
def acta_pdf(slug, raffle_id):
    data = _read_data(slug, raffle_id)
    return send_file(_render_pdf(data), mimetype='application/pdf',
                     as_attachment=True, download_name=f'acta_sorteo_{raffle_id}.pdf',
                     max_age=0)
