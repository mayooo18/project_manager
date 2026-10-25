"""Schedule of Values & unit rates (F9).

The Schedule of Values is the existing contract draw schedule (milestones that
feed billing); F9 adds server-side total validation plus a per-contract
unit-rate sheet for extras, a markup %, and a standalone Exhibit-C PDF.
"""
from io import BytesIO

from flask import (
    Blueprint, request, redirect, url_for, flash, send_file,
)
from flask_login import login_required, current_user

from extensions import db
from models import Contract, UnitRate, UNIT_RATE_DEFAULTS
from quote_routes import COMPANY, LOGO_PATH, _pdf_text, safe_filename

sov_bp = Blueprint('sov', __name__, url_prefix='/sov')


def _owned_contract_or_404(contract_id):
    return Contract.query.filter_by(
        id=contract_id, user_id=current_user.id).first_or_404()


def _float(raw, default=0.0):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _float_or_none(raw):
    try:
        v = float(raw)
        return v
    except (TypeError, ValueError):
        return None


# ── unit-rate sheet ──────────────────────────────────────────────────────────

@sov_bp.route('/contract/<int:contract_id>/unit-rates/setup', methods=['POST'])
@login_required
def setup_unit_rates(contract_id):
    contract = _owned_contract_or_404(contract_id)
    if contract.unit_rates:
        flash('Unit rates are already set up for this contract.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))
    for i, (label, unit) in enumerate(UNIT_RATE_DEFAULTS):
        db.session.add(UnitRate(contract_id=contract.id, sequence=i,
                                label=label, unit=unit, rate=0.0))
    db.session.commit()
    flash('Unit-rate sheet created — fill in the rates.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


@sov_bp.route('/contract/<int:contract_id>/unit-rates/save', methods=['POST'])
@login_required
def save_unit_rates(contract_id):
    contract = _owned_contract_or_404(contract_id)
    ids = request.form.getlist('rate_id')
    values = request.form.getlist('rate_value')
    by_id = {r.id: r for r in contract.unit_rates}
    for i, rid in enumerate(ids):
        try:
            r = by_id.get(int(rid))
        except (TypeError, ValueError):
            r = None
        if r is not None and i < len(values):
            r.rate = _float(values[i])
    contract.unit_rate_markup_percent = _float_or_none(request.form.get('markup_percent'))
    db.session.commit()
    flash('Unit rates saved.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


@sov_bp.route('/contract/<int:contract_id>/unit-rates/add', methods=['POST'])
@login_required
def add_unit_rate(contract_id):
    contract = _owned_contract_or_404(contract_id)
    label = (request.form.get('label') or '').strip()
    if not label:
        flash('Give the unit-rate item a name.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))
    seq = max((r.sequence or 0) for r in contract.unit_rates) + 1 if contract.unit_rates else 0
    db.session.add(UnitRate(
        contract_id=contract.id, sequence=seq, label=label,
        unit=(request.form.get('unit') or '').strip() or None,
        rate=_float(request.form.get('rate'))))
    db.session.commit()
    flash('Unit-rate item added.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


@sov_bp.route('/unit-rate/<int:rate_id>/delete', methods=['POST'])
@login_required
def delete_unit_rate(rate_id):
    r = UnitRate.query.get_or_404(rate_id)
    contract = _owned_contract_or_404(r.contract_id)
    db.session.delete(r)
    db.session.commit()
    flash('Unit-rate item removed.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


# ── Exhibit-C PDF ─────────────────────────────────────────────────────────────

def build_exhibit_c_pdf(contract):
    import os
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image)

    buf = BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.55 * inch,
                            bottomMargin=0.55 * inch, leftMargin=0.7 * inch,
                            rightMargin=0.7 * inch)
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small = ParagraphStyle('small', parent=normal, fontSize=9, leading=12)
    small_r = ParagraphStyle('small_r', parent=small, alignment=TA_RIGHT)
    section = ParagraphStyle('section', parent=normal, fontName='Helvetica-Bold',
                             fontSize=11, spaceBefore=10, spaceAfter=4)
    title = ParagraphStyle('title', parent=styles['Title'], fontSize=15,
                           alignment=TA_CENTER, spaceAfter=0)
    company_name = ParagraphStyle('coname', parent=normal, fontSize=12,
                                  fontName='Helvetica-Bold')

    elems = []
    header = []
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image(LOGO_PATH)
            ratio = logo.imageHeight / float(logo.imageWidth)
            logo.drawWidth = 1.4 * inch
            logo.drawHeight = 1.4 * inch * ratio
            logo.hAlign = 'LEFT'
            header.append(logo)
        except Exception:
            pass
    header.append(Paragraph(COMPANY['name'], company_name))
    header.append(Paragraph(f"{COMPANY['phone']} · {COMPANY['email']}", small))
    elems.append(Table([[header]], colWidths=[7.1 * inch],
                       style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0)])))
    elems.append(Spacer(1, 10))
    elems.append(Paragraph('Exhibit C — Schedule of Values &amp; Unit Rates', title))
    sub = f"{_pdf_text(contract.title, 160)}"
    if contract.number:
        sub += f" · {contract.number}"
    if contract.customer:
        sub += f" · {_pdf_text(contract.customer.name, 120)}"
    elems.append(Spacer(1, 4))
    elems.append(Paragraph(sub, ParagraphStyle('sub', parent=small, alignment=TA_CENTER)))
    elems.append(Spacer(1, 10))

    # Schedule of Values (draws)
    elems.append(Paragraph('Schedule of Values', section))
    data = [[Paragraph('<b>#</b>', small), Paragraph('<b>Milestone</b>', small),
             Paragraph('<b>Value</b>', small_r)]]
    for i, d in enumerate(contract.draws, start=1):
        data.append([Paragraph(str(i), small),
                     Paragraph(_pdf_text(d.description, 200), small),
                     Paragraph(f"${(d.amount or 0):,.2f}", small_r)])
    data.append([Paragraph('', small), Paragraph('<b>Scheduled total</b>', small),
                 Paragraph(f"<b>${contract.scheduled_total:,.2f}</b>", small_r)])
    data.append([Paragraph('', small), Paragraph('Contract total', small),
                 Paragraph(f"${(contract.contract_total or 0):,.2f}", small_r)])
    sov = Table(data, colWidths=[0.4 * inch, 5.2 * inch, 1.5 * inch])
    sov.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#111111')),
        ('LINEABOVE', (0, -2), (-1, -2), 0.75, colors.HexColor('#111111')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
    ]))
    elems.append(sov)
    if not contract.sov_balanced and contract.contract_total:
        elems.append(Spacer(1, 4))
        elems.append(Paragraph(
            f"Note: milestones differ from the contract total by "
            f"${abs(contract.sov_variance):,.2f}.", small))

    # Unit rates
    elems.append(Paragraph('Unit Rates for Extra Work', section))
    if contract.unit_rates:
        ur = [[Paragraph('<b>Item</b>', small), Paragraph('<b>Unit</b>', small),
               Paragraph('<b>Rate</b>', small_r)]]
        for r in contract.unit_rates:
            ur.append([Paragraph(_pdf_text(r.label, 120), small),
                       Paragraph(_pdf_text(r.unit or '', 60), small),
                       Paragraph(f"${(r.rate or 0):,.2f}", small_r)])
        urt = Table(ur, colWidths=[3.8 * inch, 2.0 * inch, 1.3 * inch])
        urt.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
            ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#111111')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ]))
        elems.append(urt)
        if contract.unit_rate_markup_percent is not None:
            elems.append(Spacer(1, 4))
            elems.append(Paragraph(
                f"Markup on extras: {contract.unit_rate_markup_percent:g}%", small))
    else:
        elems.append(Paragraph('No unit rates recorded.', small))

    pdf.build(elems)
    buf.seek(0)
    return buf


@sov_bp.route('/contract/<int:contract_id>/exhibit-c.pdf')
@login_required
def exhibit_c(contract_id):
    contract = _owned_contract_or_404(contract_id)
    buf = build_exhibit_c_pdf(contract)
    name = safe_filename(contract.customer.name if contract.customer else None,
                         contract.number or f'Contract-{contract.id}', 'ExhibitC')
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{name}-ExhibitC.pdf')
