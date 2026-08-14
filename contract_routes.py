"""
Contracts + draw schedule / progress billing (Phase 3).

Self-contained Blueprint. Adds:
  - A Contract = a project's agreed total plus an ordered draw schedule
    (Deposit / Rough-in / Drywall / Final ...), with optional retainage.
  - Create a contract from an approved proposal (inherits total, customer,
    project) or from scratch.
  - "Bill this draw" turns a milestone into a normal Phase-2 Invoice for just
    that amount, so it reuses the existing PDF / send / mark-paid / auto-income
    machinery. The contract tracks billed-to-date vs paid-to-date vs remaining.
  - Contract PDF with a Schedule of Values (reuses the Phase 1 letterhead).

Builds on Phases 1-2 without modifying them.
"""

import re
from datetime import datetime
from io import BytesIO

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, send_file,
    abort,
)
from flask_login import login_required, current_user
from permissions import owner_required
from sqlalchemy import select

from extensions import db
from models import (
    Contract, ContractDraw, Customer, Quote, Project, Invoice, InvoiceItem,
    find_or_create_location,
)
from forms import DeleteForm
from quote_routes import COMPANY, LOGO_PATH, _pdf_text
from invoice_routes import _new_invoice_token, _next_number

contract_bp = Blueprint('contracts', __name__, url_prefix='/contracts')


# ── helpers ──────────────────────────────────────────────────────────────

def _owned_contract_or_404(contract_id):
    return Contract.query.filter_by(
        id=contract_id, user_id=current_user.id).first_or_404()


def _max_trailing_int(numbers):
    """Highest trailing integer across a list of number strings (0 if none).

    Using the max of existing numbers (rather than a count) means deleting a
    record never lets a later one reuse a still-live number.
    """
    best = 0
    for n in numbers or []:
        match = re.search(r'(\d+)$', n or '')
        if match:
            best = max(best, int(match.group(1)))
    return best


def _next_contract_number():
    numbers = [c.number for c in
               Contract.query.filter_by(user_id=current_user.id).all()]
    return f"CON-{_max_trailing_int(numbers) + 1:04d}"


def _float(raw, default=0.0):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _float_or_none(raw):
    try:
        val = float(raw)
        return val if val else None
    except (TypeError, ValueError):
        return None


def _parse_draws(form):
    """Read parallel draw_description[]/draw_amount[] arrays into dicts."""
    descriptions = form.getlist('draw_description')
    amounts = form.getlist('draw_amount')
    draws = []
    for i, desc in enumerate(descriptions):
        desc = (desc or '').strip()
        if not desc:
            continue
        amount = _float(amounts[i]) if i < len(amounts) else 0.0
        draws.append({'description': desc, 'amount': amount})
    return draws


def _apply_draws(contract, draw_dicts):
    """Replace a contract's *un-billed* draws with the submitted set.

    Draws that have already been billed to an invoice are preserved so history
    stays intact; only pending draws are editable.
    """
    for existing in list(contract.draws):
        if not existing.is_billed:
            db.session.delete(existing)
    # Re-sequence: billed draws first (kept), then the newly submitted pending ones.
    kept = [d for d in contract.draws if d.is_billed]
    seq = 0
    for d in sorted(kept, key=lambda x: x.sequence or 0):
        d.sequence = seq
        seq += 1
    for d in draw_dicts:
        contract.draws.append(ContractDraw(
            sequence=seq, description=d['description'],
            amount=d['amount'], status='pending'))
        seq += 1


def build_contract_pdf(contract):
    """Render a contract with its Schedule of Values as a PDF."""
    import os
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small = ParagraphStyle('small', parent=normal, fontSize=9, leading=13)
    small_r = ParagraphStyle('small_r', parent=small, alignment=TA_RIGHT)
    doc_title = ParagraphStyle('doctitle', parent=styles['Title'],
                               fontSize=22, alignment=TA_RIGHT, spaceAfter=0)
    company_name = ParagraphStyle('coname', parent=normal, fontSize=13,
                                  fontName='Helvetica-Bold')
    section = ParagraphStyle('section', parent=normal,
                             fontName='Helvetica-Bold', fontSize=10)
    ink = colors.HexColor('#111111')

    elems = []

    left_cell = []
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image(LOGO_PATH)
            ratio = logo.imageHeight / float(logo.imageWidth)
            logo.drawWidth = 1.7 * inch
            logo.drawHeight = 1.7 * inch * ratio
            logo.hAlign = 'LEFT'
            left_cell.append(logo)
            left_cell.append(Spacer(1, 4))
        except Exception:
            pass
    left_cell.append(Paragraph(COMPANY['name'], company_name))
    left_cell.append(Paragraph(COMPANY['address_line1'], small))
    left_cell.append(Paragraph(COMPANY['address_line2'], small))
    left_cell.append(Paragraph(COMPANY['phone'], small))
    left_cell.append(Paragraph(COMPANY['email'], small))

    date_str = contract.created_at.strftime('%m/%d/%y') if contract.created_at else ''
    right_cell = [
        Paragraph('CONTRACT', doc_title),
        Spacer(1, 8),
        Paragraph(f"CONTRACT # {_pdf_text(contract.number or contract.id, 50)}", small_r),
        Paragraph(f"DATE {date_str}", small_r),
    ]
    header = Table([[left_cell, right_cell]], colWidths=[3.6 * inch, 3.4 * inch])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems.append(header)
    elems.append(Spacer(1, 10))

    c = contract.customer
    bill = [Paragraph('<b>OWNER / CLIENT</b>', small),
            Paragraph(_pdf_text(c.name, 150), small)]
    if c.address:
        bill.append(Paragraph(_pdf_text(c.address, 250), small))
    forpo = [Paragraph(f"PROJECT &nbsp; {_pdf_text(contract.title, 200)}", small)]
    billtable = Table([[bill, forpo]], colWidths=[3.6 * inch, 3.4 * inch])
    billtable.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems.append(billtable)
    elems.append(Spacer(1, 14))

    elems.append(Paragraph('Schedule of Values', section))
    elems.append(Spacer(1, 6))
    data = [[Paragraph('<b>#</b>', small), Paragraph('<b>Milestone / Draw</b>', small),
             Paragraph('<b>Amount</b>', small_r), Paragraph('<b>Status</b>', small_r)]]
    for i, d in enumerate(contract.draws, 1):
        status = 'Paid' if d.is_paid else ('Invoiced' if d.is_billed else 'Pending')
        data.append([Paragraph(str(i), small),
                     Paragraph(_pdf_text(d.description, 200), small),
                     Paragraph(f"${d.amount:,.2f}", small_r),
                     Paragraph(status, small_r)])
    data.append([Paragraph('', small), Paragraph('<b>Contract Total</b>', small),
                 Paragraph(f"<b>${contract.contract_total:,.2f}</b>", small_r),
                 Paragraph('', small_r)])

    table = Table(data, colWidths=[0.4 * inch, 4.0 * inch, 1.3 * inch, 1.3 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, ink),
        ('LINEABOVE', (0, -1), (-1, -1), 0.75, ink),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
    ]))
    elems.append(table)
    elems.append(Spacer(1, 12))

    if contract.retainage_percent:
        elems.append(Paragraph(
            f"Retainage: {contract.retainage_percent:g}% "
            f"(${contract.retainage_amount:,.2f}) held until final completion.", small))
        elems.append(Spacer(1, 10))

    if contract.notes:
        elems.append(Paragraph('Notes:', section))
        elems.append(Spacer(1, 4))
        elems.append(Paragraph(_pdf_text(contract.notes, preserve_newlines=True), small))
        elems.append(Spacer(1, 12))

    elems.append(Spacer(1, 18))
    sig = Table([[Paragraph('Owner _____________________________', small),
                  Paragraph('Contractor _____________________________', small)]],
                colWidths=[3.5 * inch, 3.5 * inch])
    sig.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0)]))
    elems.append(sig)

    doc.build(elems)
    buf.seek(0)
    return buf


# ── list ──────────────────────────────────────────────────────────────────

@contract_bp.route('/')
@login_required
def index():
    contracts = (Contract.query.filter_by(user_id=current_user.id)
                 .order_by(Contract.created_at.desc()).all())
    return render_template('contracts/list.html', contracts=contracts,
                           delete_form=DeleteForm())


# ── builder (create / edit) ─────────────────────────────────────────────────

@contract_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    return _save_contract(None)


@contract_bp.route('/<int:contract_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(contract_id):
    contract = _owned_contract_or_404(contract_id)
    return _save_contract(contract)


def _save_contract(contract):
    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        title = (request.form.get('title') or '').strip()
        customer = Customer.query.filter_by(
            id=customer_id, user_id=current_user.id).first()

        if not customer:
            flash('Please choose a customer.', 'error')
        elif not title:
            flash('Please give the contract a title.', 'error')
        else:
            if contract is None:
                contract = Contract(user_id=current_user.id,
                                    number=_next_contract_number())
                db.session.add(contract)
            contract.customer_id = customer.id
            contract.title = title
            contract.project_id = request.form.get('project_id', type=int) or None
            contract.contract_total = _float(request.form.get('contract_total'))
            contract.retainage_percent = _float_or_none(request.form.get('retainage_percent'))
            contract.notes = (request.form.get('notes') or '').strip()
            _apply_draws(contract, _parse_draws(request.form))
            db.session.commit()
            flash('Contract saved.', 'success')
            return redirect(url_for('contracts.edit', contract_id=contract.id))

    customers = (Customer.query.filter_by(user_id=current_user.id)
                 .order_by(Customer.name.asc()).all())
    projects = Project.query.order_by(Project.name.asc()).all()
    return render_template('contracts/form.html', contract=contract,
                           customers=customers, projects=projects)


# ── create a contract from an approved proposal ─────────────────────────────

@contract_bp.route('/from-quote/<int:quote_id>', methods=['POST'])
@login_required
def from_quote(quote_id):
    quote = Quote.query.filter_by(
        id=quote_id, user_id=current_user.id).first_or_404()

    # A signed proposal becomes active work — make sure it has a Job. If the
    # proposal wasn't already linked to one, create it now (carrying the
    # customer + address → Location), so "convert" produces contract + Job.
    project_id = quote.project_id
    if not project_id:
        customer = quote.customer
        project = Project(
            name=quote.title or (f"Job for {customer.name}" if customer else 'New job'),
            address=customer.address if customer else None,
            status='Active',
            customer_id=quote.customer_id,
        )
        db.session.add(project)
        db.session.flush()
        loc = find_or_create_location(current_user.id, quote.customer_id,
                                      customer.address if customer else None)
        if loc:
            project.location_id = loc.id
        project_id = project.id

    contract = Contract(
        user_id=current_user.id,
        customer_id=quote.customer_id,
        project_id=project_id,
        quote_id=quote.id,
        number=_next_contract_number(),
        title=quote.title,
        contract_total=quote.total or 0,
        notes=quote.notes,
        status='draft',
    )
    db.session.add(contract)
    # Seed a starting draw schedule: deposit (if the proposal had one) + balance.
    seq = 0
    if quote.deposit:
        contract.draws.append(ContractDraw(
            sequence=seq, description='Deposit', amount=quote.deposit, status='pending'))
        seq += 1
        balance = (quote.total or 0) - quote.deposit
        if balance > 0:
            contract.draws.append(ContractDraw(
                sequence=seq, description='Balance on completion',
                amount=balance, status='pending'))
    # The proposal has now been actioned into a contract — take it off the
    # pending list (mirrors how converting to an invoice marks it converted).
    quote.status = 'converted'
    db.session.commit()
    flash('Contract created from proposal. Set up the draw schedule below.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


# ── delete ──────────────────────────────────────────────────────────────────

@contract_bp.route('/<int:contract_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete(contract_id):
    contract = _owned_contract_or_404(contract_id)
    # Guard: billed draws leave invoices pointing at this contract, and change
    # orders are legal records with a NOT-NULL contract_id — deleting the
    # contract out from under either would error or orphan data. Require the
    # user to clear those first.
    if any(d.is_billed for d in contract.draws):
        flash('This contract has billed draws (invoices reference it). '
              'Delete or void those invoices first.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))
    if contract.change_orders:
        flash('This contract has change orders. Delete those first.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))
    db.session.delete(contract)
    db.session.commit()
    flash('Contract deleted.', 'success')
    return redirect(url_for('contracts.index'))


# ── bill a draw → creates a Phase-2 invoice for that milestone ─────────────

@contract_bp.route('/<int:contract_id>/draws/<int:draw_id>/bill', methods=['POST'])
@login_required
def bill_draw(contract_id, draw_id):
    contract = _owned_contract_or_404(contract_id)
    # Lock the draw row so two concurrent "Bill" clicks can't both create an
    # invoice for the same milestone.
    draw = db.session.execute(
        select(ContractDraw)
        .where(ContractDraw.id == draw_id,
               ContractDraw.contract_id == contract.id)
        .with_for_update()
    ).scalar_one_or_none()
    if draw is None:
        abort(404)

    if draw.is_billed:
        flash('That draw has already been billed.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))

    n = len(contract.draws)
    inv = Invoice(
        user_id=current_user.id,
        customer_id=contract.customer_id,
        project_id=contract.project_id,
        contract_id=contract.id,
        number=_next_number(),
        title=f"{contract.title} — {draw.description}",
        public_token=_new_invoice_token(),
    )
    db.session.add(inv)
    inv.items.append(InvoiceItem(
        description=f"{draw.description} (Draw {(draw.sequence or 0) + 1} of {n}) "
                    f"— progress billing on contract {contract.number}",
        quantity=1, unit_price=draw.amount))
    inv.recalculate_total()
    db.session.flush()

    draw.invoice_id = inv.id
    draw.status = 'invoiced'
    if contract.status == 'draft':
        contract.status = 'active'
    db.session.commit()
    flash(f'Draw billed as invoice {inv.number}. Send it to the customer below.', 'success')
    return redirect(url_for('invoices.edit', invoice_id=inv.id))


@contract_bp.route('/<int:contract_id>/pdf')
@login_required
def pdf(contract_id):
    contract = _owned_contract_or_404(contract_id)
    buf = build_contract_pdf(contract)
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f'{contract.number or contract.id}.pdf')
