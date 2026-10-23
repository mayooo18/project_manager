"""Contractor's sworn statements (F3).

An Illinois-style sworn statement per invoice: each subcontractor/supplier with
their contract amount, previously paid, this payment and balance. Opt-in per
contract (the F0 `sworn_statements_enabled` toggle). Each new statement on a
contract pre-fills from the most recent prior one, rolling the amounts forward;
every pre-filled value stays editable.
"""
from io import BytesIO

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    send_file,
)
from flask_login import login_required, current_user

from extensions import db
from models import (
    SwornStatement, SwornStatementLine, Invoice, Subcontractor,
)
from quote_routes import COMPANY, LOGO_PATH, _pdf_text, safe_filename

sworn_bp = Blueprint('sworn', __name__, url_prefix='/sworn')


# ── helpers ──────────────────────────────────────────────────────────────────

def _owned_statement_or_404(statement_id):
    return SwornStatement.query.filter_by(
        id=statement_id, user_id=current_user.id).first_or_404()


def _owned_invoice_or_404(invoice_id):
    return Invoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()


def _float(raw, default=0.0):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _subcontractors():
    return (Subcontractor.query.filter_by(user_id=current_user.id)
            .order_by(Subcontractor.name.asc()).all())


def _latest_prior_statement(contract_id, exclude_id=None):
    """Most recent sworn statement on the same contract (to pre-fill from)."""
    if not contract_id:
        return None
    q = SwornStatement.query.filter_by(
        user_id=current_user.id, contract_id=contract_id)
    if exclude_id is not None:
        q = q.filter(SwornStatement.id != exclude_id)
    return q.order_by(SwornStatement.created_at.desc()).first()


def _prefill_lines(statement, prior):
    """Copy a prior statement's lines forward, rolling the amounts:
    new previously_paid = prior previously_paid + prior this_payment;
    new this_payment starts at 0 (editable). Contract amount carries over."""
    for pl in prior.lines:
        statement.lines.append(SwornStatementLine(
            subcontractor_id=pl.subcontractor_id,
            name=pl.name,
            trade=pl.trade,
            description=pl.description,
            contract_amount=pl.contract_amount,
            previously_paid=(pl.previously_paid or 0) + (pl.this_payment or 0),
            this_payment=0.0,
        ))


def _parse_lines(form):
    """Read the builder's parallel arrays into line dicts.

    A row counts when it names a sub/supplier (typed name or a chosen sub) or
    carries any amount. When a saved sub is chosen and no name is typed, the
    sub's name/trade are snapshotted onto the line.
    """
    sub_ids = form.getlist('line_subcontractor_id')
    names = form.getlist('line_name')
    trades = form.getlist('line_trade')
    descs = form.getlist('line_description')
    contracts = form.getlist('line_contract_amount')
    prev = form.getlist('line_previously_paid')
    thisp = form.getlist('line_this_payment')
    n = max(len(sub_ids), len(names), len(descs), len(contracts),
            len(prev), len(thisp))

    # map chosen subs -> their name/trade for snapshotting
    subs = {s.id: s for s in _subcontractors()}
    rows = []
    for i in range(n):
        def g(lst):
            return lst[i] if i < len(lst) else ''
        name = (g(names) or '').strip()
        trade = (g(trades) or '').strip()
        try:
            sub_id = int(g(sub_ids)) if g(sub_ids) else None
        except ValueError:
            sub_id = None
        c_amt = _float(g(contracts))
        p_paid = _float(g(prev))
        t_pay = _float(g(thisp))
        # snapshot name/trade from the chosen sub when the user didn't type one
        if sub_id in subs:
            if not name:
                name = subs[sub_id].name
            if not trade:
                trade = subs[sub_id].trade or ''
        has_content = bool(name) or c_amt or p_paid or t_pay
        if not has_content:
            continue
        rows.append(dict(subcontractor_id=sub_id, name=name, trade=trade,
                         description=(g(descs) or '').strip(),
                         contract_amount=c_amt, previously_paid=p_paid,
                         this_payment=t_pay))
    return rows


def _apply_lines(statement, rows):
    for existing in list(statement.lines):
        db.session.delete(existing)
    statement.lines = []
    for r in rows:
        statement.lines.append(SwornStatementLine(**r))


# ── create (from an invoice) ────────────────────────────────────────────────

@sworn_bp.route('/for-invoice/<int:invoice_id>', methods=['POST'])
@login_required
def create_for_invoice(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)
    contract = invoice.contract
    if contract is None or not contract.sworn_statements_enabled:
        flash('Sworn statements are not enabled on this contract.', 'error')
        return redirect(url_for('invoices.edit', invoice_id=invoice.id))

    # Find the statement to pre-fill from BEFORE adding the new one, otherwise
    # autoflush would insert the new (empty) statement and pick it as "latest".
    prior = _latest_prior_statement(contract.id)
    statement = SwornStatement(
        user_id=current_user.id, invoice_id=invoice.id,
        contract_id=contract.id)
    db.session.add(statement)
    if prior is not None:
        _prefill_lines(statement, prior)
    db.session.commit()
    msg = ('New sworn statement created, pre-filled from the previous one — '
           'edit the amounts below.') if prior else \
          ('New sworn statement created — add each subcontractor and supplier below.')
    flash(msg, 'success')
    return redirect(url_for('sworn.edit', statement_id=statement.id))


# ── edit / builder ──────────────────────────────────────────────────────────

@sworn_bp.route('/<int:statement_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(statement_id):
    statement = _owned_statement_or_404(statement_id)
    if request.method == 'POST':
        from datetime import datetime
        raw_date = (request.form.get('statement_date') or '').strip()
        if raw_date:
            try:
                statement.statement_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
            except ValueError:
                pass
        statement.notes = (request.form.get('notes') or '').strip()
        _apply_lines(statement, _parse_lines(request.form))
        db.session.commit()
        flash('Sworn statement saved.', 'success')
        return redirect(url_for('sworn.edit', statement_id=statement.id))

    return render_template('sworn/form.html', statement=statement,
                           subcontractors=_subcontractors())


@sworn_bp.route('/<int:statement_id>/delete', methods=['POST'])
@login_required
def delete(statement_id):
    statement = _owned_statement_or_404(statement_id)
    invoice_id = statement.invoice_id
    db.session.delete(statement)
    db.session.commit()
    flash('Sworn statement deleted.', 'success')
    return redirect(url_for('invoices.edit', invoice_id=invoice_id))


# ── PDF ──────────────────────────────────────────────────────────────────────

def build_sworn_pdf(statement):
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
                            bottomMargin=0.55 * inch, leftMargin=0.6 * inch,
                            rightMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small = ParagraphStyle('small', parent=normal, fontSize=8.5, leading=11)
    small_r = ParagraphStyle('small_r', parent=small, alignment=TA_RIGHT)
    body = ParagraphStyle('body', parent=normal, fontSize=9.5, leading=14)
    company_name = ParagraphStyle('coname', parent=normal, fontSize=13,
                                  fontName='Helvetica-Bold')
    title = ParagraphStyle('title', parent=styles['Title'], fontSize=15,
                           alignment=TA_CENTER, spaceAfter=0)
    foot = ParagraphStyle('foot', parent=normal, fontSize=7.5,
                          textColor=colors.grey, alignment=TA_CENTER, leading=10)

    inv = statement.invoice
    contract = statement.contract
    customer = inv.customer if inv else None

    elems = []
    header_left = []
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image(LOGO_PATH)
            ratio = logo.imageHeight / float(logo.imageWidth)
            logo.drawWidth = 1.5 * inch
            logo.drawHeight = 1.5 * inch * ratio
            logo.hAlign = 'LEFT'
            header_left.append(logo)
        except Exception:
            pass
    header_left.append(Paragraph(COMPANY['name'], company_name))
    header_left.append(Paragraph(COMPANY['address_line1'], small))
    header_left.append(Paragraph(COMPANY['address_line2'], small))
    header_left.append(Paragraph(f"{COMPANY['phone']} · {COMPANY['email']}", small))
    elems.append(Table([[header_left]], colWidths=[7.3 * inch],
                       style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0)])))
    elems.append(Spacer(1, 12))
    elems.append(Paragraph("Contractor's Sworn Statement", title))
    elems.append(Spacer(1, 12))

    date_str = statement.statement_date.strftime('%B %d, %Y') if statement.statement_date else ''
    owner = customer.name if customer else ''
    prop = contract.title if contract else (inv.title if inv else '')
    total_contract = contract.contract_total if contract else statement.total_contract
    elems.append(Paragraph(
        f"State of Illinois, County of ______________. The affiant, being duly "
        f"sworn, deposes and says that they are the contractor for the improvement "
        f"of the property known as <b>{_pdf_text(prop, 200)}</b>, owned by "
        f"<b>{_pdf_text(owner, 150)}</b>; that the total amount of the contract is "
        f"<b>${(total_contract or 0):,.2f}</b>; and that the following is a true "
        f"statement of all persons who have furnished labor or materials, with the "
        f"amounts due or to become due to each, as of {date_str} "
        f"(invoice {_pdf_text(inv.number or inv.id if inv else '', 40)}).", body))
    elems.append(Spacer(1, 12))

    head = ['#', 'Name / Supplier', 'Trade', 'Work / Material',
            'Contract', 'Prev. paid', 'This pmt', 'Balance']
    data = [[Paragraph(f'<b>{h}</b>', small) for h in head]]
    for i, ln in enumerate(statement.lines, start=1):
        data.append([
            Paragraph(str(i), small),
            Paragraph(_pdf_text(ln.display_name, 60), small),
            Paragraph(_pdf_text(ln.trade or '', 40), small),
            Paragraph(_pdf_text(ln.description or '', 120), small),
            Paragraph(f"${(ln.contract_amount or 0):,.2f}", small_r),
            Paragraph(f"${(ln.previously_paid or 0):,.2f}", small_r),
            Paragraph(f"${(ln.this_payment or 0):,.2f}", small_r),
            Paragraph(f"${ln.balance:,.2f}", small_r),
        ])
    data.append([
        Paragraph('', small), Paragraph('<b>Totals</b>', small), Paragraph('', small),
        Paragraph('', small),
        Paragraph(f"<b>${statement.total_contract:,.2f}</b>", small_r),
        Paragraph(f"<b>${statement.total_previously_paid:,.2f}</b>", small_r),
        Paragraph(f"<b>${statement.total_this_payment:,.2f}</b>", small_r),
        Paragraph(f"<b>${statement.total_balance:,.2f}</b>", small_r),
    ])
    table = Table(data, colWidths=[0.3 * inch, 1.5 * inch, 0.9 * inch, 1.9 * inch,
                                   0.8 * inch, 0.8 * inch, 0.75 * inch, 0.75 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#111111')),
        ('LINEABOVE', (0, -1), (-1, -1), 0.75, colors.HexColor('#111111')),
        ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#bbbbbb')),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elems.append(table)
    elems.append(Spacer(1, 18))

    if statement.notes:
        elems.append(Paragraph(f"<b>Notes:</b> {_pdf_text(statement.notes, preserve_newlines=True)}", small))
        elems.append(Spacer(1, 14))

    # Signature + notary (jurat) block
    sig = Table([
        [Paragraph('Signature of affiant: ______________________________', small),
         Paragraph('Date: ________________', small)],
        [Paragraph('Printed name / title: ______________________________', small), ''],
    ], colWidths=[4.6 * inch, 2.7 * inch])
    sig.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0),
                             ('TOPPADDING', (0, 0), (-1, -1), 10)]))
    elems.append(sig)
    elems.append(Spacer(1, 16))
    elems.append(Paragraph(
        "Subscribed and sworn to before me this ______ day of "
        "________________, 20____.", small))
    elems.append(Spacer(1, 16))
    elems.append(Paragraph("______________________________   "
                           "Notary Public", small))
    elems.append(Paragraph("My commission expires: ________________", small))
    elems.append(Spacer(1, 18))
    elems.append(Paragraph(
        'This form is provided for convenience. Sworn-statement requirements vary '
        'by state and lender; confirm this document satisfies the requirements '
        'that apply before relying on it. It is not legal advice.', foot))

    pdf.build(elems)
    buf.seek(0)
    return buf


@sworn_bp.route('/<int:statement_id>/pdf')
@login_required
def pdf(statement_id):
    statement = _owned_statement_or_404(statement_id)
    buf = build_sworn_pdf(statement)
    cust = statement.invoice.customer.name if (statement.invoice and statement.invoice.customer) else None
    name = safe_filename(cust, f'Sworn-{statement.id}', 'Sworn')
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{name}.pdf')
