"""
Customer-facing invoices (Phase 2).

Self-contained Blueprint. Adds:
  - Invoice list / builder (line items, deposit, P.O. #)
  - One-click conversion of an approved quote into an invoice
  - Mark-as-paid with a payment method, and an option to auto-record the
    payment as Income against the linked project (closes the loop with the
    app's existing profitability tracking)
  - Contract-style PDF (reuses the Phase 1 letterhead) and a public,
    tokenized view link (/i/<token>)
  - One-click email to the customer via the existing Gmail integration

Reuses helpers from quote_routes.py (company header, PDF text escaping,
line-item parsing) without modifying Phase 1.
"""

import base64
import re
from datetime import datetime, timedelta
from io import BytesIO

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    send_file,
)
from flask_login import login_required, current_user

from extensions import db, limiter
from models import Invoice, InvoiceItem, Customer, Quote, Project, Income
from forms import DeleteForm
from quote_routes import (
    COMPANY, LOGO_PATH, _pdf_text, _parse_items, _new_token as _new_quote_token,
)

invoice_bp = Blueprint('invoices', __name__, url_prefix='/invoices')

INVOICE_STATUSES = ['draft', 'sent', 'paid', 'void']
PAYMENT_METHODS = ['Cash', 'Zelle', 'Check', 'Bank transfer', 'Card', 'Other']
PUBLIC_LINK_LIFETIME = timedelta(days=30)


# ── helpers ──────────────────────────────────────────────────────────────

def _new_invoice_token():
    """URL-safe token guaranteed unique among invoices."""
    import secrets
    while True:
        token = secrets.token_urlsafe(16)
        if not Invoice.query.filter_by(public_token=token).first():
            return token


def _public_link_is_active(invoice, now=None):
    now = now or datetime.utcnow()
    return (invoice.public_token_revoked_at is None and
            invoice.public_token_expires_at is not None and
            invoice.public_token_expires_at > now)


def _refresh_public_link(invoice):
    invoice.public_token = _new_invoice_token()
    invoice.public_token_expires_at = datetime.utcnow() + PUBLIC_LINK_LIFETIME
    invoice.public_token_revoked_at = None


def _get_public_invoice(token):
    now = datetime.utcnow()
    return (Invoice.query
            .filter(Invoice.public_token == token,
                    Invoice.public_token_revoked_at.is_(None),
                    Invoice.public_token_expires_at > now)
            .first_or_404())


def _owned_invoice_or_404(invoice_id):
    return Invoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()


def _apply_items(invoice, item_dicts):
    for existing in list(invoice.items):
        db.session.delete(existing)
    invoice.items = []
    for d in item_dicts:
        invoice.items.append(InvoiceItem(
            description=d['description'],
            quantity=d['quantity'],
            unit_price=d['unit_price'],
        ))
    invoice.recalculate_total()


def _next_number():
    """Next per-user invoice number, e.g. INV-0007.

    Derived from the highest existing number rather than a count, so deleting
    an invoice never lets a new one reuse a still-live number.
    """
    best = 0
    for inv in Invoice.query.filter_by(user_id=current_user.id).all():
        match = re.search(r'(\d+)$', inv.number or '')
        if match:
            best = max(best, int(match.group(1)))
    return f"INV-{best + 1:04d}"


def _float_or_none(raw):
    try:
        val = float(raw)
        return val if val else None
    except (TypeError, ValueError):
        return None


def build_invoice_pdf(invoice):
    """Render an invoice as a contract-style PDF matching the Optimal SES letterhead."""
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
    paid_style = ParagraphStyle('paid', parent=normal, fontSize=20,
                                textColor=colors.HexColor('#16a34a'),
                                fontName='Helvetica-Bold', alignment=TA_RIGHT)
    ink = colors.HexColor('#111111')

    elems = []

    # ── Header: logo + company (left) | INVOICE title + number/date (right) ──
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

    date_str = invoice.created_at.strftime('%m/%d/%y') if invoice.created_at else ''
    right_cell = [
        Paragraph('INVOICE', doc_title),
        Spacer(1, 8),
        Paragraph(f"INVOICE # {_pdf_text(invoice.number or invoice.id, 50)}", small_r),
        Paragraph(f"DATE {date_str}", small_r),
    ]
    if invoice.status == 'paid':
        right_cell.append(Spacer(1, 6))
        right_cell.append(Paragraph('PAID', paid_style))

    header = Table([[left_cell, right_cell]], colWidths=[3.6 * inch, 3.4 * inch])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems.append(header)
    elems.append(Spacer(1, 10))

    # ── Bill-to (left) | FOR / P.O. (right) ──
    c = invoice.customer
    bill = [Paragraph('<b>BILL TO</b>', small),
            Paragraph(_pdf_text(c.name, 150), small)]
    if c.address:
        bill.append(Paragraph(_pdf_text(c.address, 250), small))
    if c.phone:
        bill.append(Paragraph(_pdf_text(c.phone, 30), small))
    if c.email:
        bill.append(Paragraph(_pdf_text(c.email, 150), small))

    forpo = [
        Paragraph(f"FOR &nbsp; {_pdf_text(invoice.title, 200)}", small),
        Spacer(1, 4),
        Paragraph(f"P.O. # {_pdf_text(invoice.po_number or 'n/a', 50)}", small),
    ]
    billtable = Table([[bill, forpo]], colWidths=[3.6 * inch, 3.4 * inch])
    billtable.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems.append(billtable)
    elems.append(Spacer(1, 14))

    # ── Description | Amount table ──
    data = [[Paragraph('<b>Description</b>', small),
             Paragraph('<b>Amount</b>', small_r)]]
    for item in invoice.items:
        desc = _pdf_text(item.description, preserve_newlines=True)
        data.append([Paragraph(desc, small),
                     Paragraph(f"${item.line_total:,.2f}", small_r)])
    data.append([Paragraph('<b>Total</b>', small),
                 Paragraph(f"<b>${invoice.total:,.2f}</b>", small_r)])
    if invoice.deposit:
        data.append([Paragraph('Deposit', small),
                     Paragraph(f"-${invoice.deposit:,.2f}", small_r)])
    balance = 0.0 if invoice.status == 'paid' else (invoice.total or 0) - (invoice.deposit or 0)
    data.append([Paragraph('<b>Balance Due</b>', small),
                 Paragraph(f"<b>${balance:,.2f}</b>", small_r)])

    items_table = Table(data, colWidths=[5.2 * inch, 1.8 * inch])
    items_table.setStyle(TableStyle([
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
    elems.append(items_table)
    elems.append(Spacer(1, 16))

    if invoice.status == 'paid' and invoice.paid_at:
        elems.append(Paragraph(
            f"Paid in full on {invoice.paid_at.strftime('%m/%d/%y')}"
            f"{' via ' + _pdf_text(invoice.payment_method, 50) if invoice.payment_method else ''}.",
            section))
        elems.append(Spacer(1, 12))

    if invoice.notes:
        elems.append(Paragraph('Notes:', section))
        elems.append(Spacer(1, 4))
        elems.append(Paragraph(_pdf_text(invoice.notes, preserve_newlines=True), small))
        elems.append(Spacer(1, 12))

    elems.append(Spacer(1, 6))
    elems.append(Paragraph(COMPANY['footer'],
                           ParagraphStyle('foot', parent=normal,
                                          alignment=TA_CENTER, fontSize=10,
                                          fontName='Helvetica-Bold')))

    doc.build(elems)
    buf.seek(0)
    return buf


def send_invoice_email(invoice):
    """Email the invoice (view link + PDF) to the customer via Gmail.
    Returns (ok, message)."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials

    customer = invoice.customer
    if not customer.email:
        return False, 'This customer has no email address on file. Add one on the Customers page.'

    if not _public_link_is_active(invoice):
        _refresh_public_link(invoice)

    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    link = url_for('invoices.public_view', token=invoice.public_token, _external=True)
    html = render_template('invoices/email.html', invoice=invoice, link=link, company=COMPANY)

    msg = MIMEMultipart('mixed')
    msg['To'] = customer.email
    msg['From'] = 'me'
    msg['Subject'] = f"Invoice {invoice.number or invoice.id} from {COMPANY['name']}: {invoice.title}"

    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)

    pdf_bytes = build_invoice_pdf(invoice).read()
    attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
    safe_name = (invoice.number or 'invoice').replace('/', '-')
    attachment.add_header('Content-Disposition', 'attachment',
                          filename=f'{safe_name}.pdf')
    msg.attach(attachment)

    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
    return True, f'Emailed to {customer.email}.'


# ── list ──────────────────────────────────────────────────────────────────

@invoice_bp.route('/')
@login_required
def index():
    invoices = (Invoice.query.filter_by(user_id=current_user.id)
                .order_by(Invoice.created_at.desc()).all())
    return render_template('invoices/list.html', invoices=invoices,
                           delete_form=DeleteForm())


# ── builder (create / edit) ────────────────────────────────────────────────

@invoice_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    return _save_invoice(None)


@invoice_bp.route('/<int:invoice_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)
    return _save_invoice(invoice)


def _save_invoice(invoice):
    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        title = (request.form.get('title') or '').strip()
        notes = (request.form.get('notes') or '').strip()
        project_id = request.form.get('project_id', type=int)
        customer = Customer.query.filter_by(
            id=customer_id, user_id=current_user.id).first()

        if not customer:
            flash('Please choose a customer.', 'error')
        elif not title:
            flash('Please give the invoice a title.', 'error')
        else:
            if invoice is None:
                invoice = Invoice(user_id=current_user.id,
                                  public_token=_new_invoice_token(),
                                  number=_next_number())
                db.session.add(invoice)
            invoice.customer_id = customer.id
            invoice.title = title
            invoice.notes = notes
            invoice.project_id = project_id if project_id else None
            invoice.deposit = _float_or_none(request.form.get('deposit'))
            invoice.po_number = (request.form.get('po_number') or '').strip() or None
            _apply_items(invoice, _parse_items(request.form))
            db.session.commit()
            flash('Invoice saved.', 'success')
            return redirect(url_for('invoices.edit', invoice_id=invoice.id))

    customers = (Customer.query.filter_by(user_id=current_user.id)
                 .order_by(Customer.name.asc()).all())
    projects = Project.query.order_by(Project.name.asc()).all()
    return render_template('invoices/form.html', invoice=invoice,
                           customers=customers, projects=projects,
                           payment_methods=PAYMENT_METHODS,
                           today=datetime.utcnow().strftime('%Y-%m-%d'),
                           public_link_active=(_public_link_is_active(invoice) if invoice else False))


# ── convert an approved quote into an invoice ──────────────────────────────

@invoice_bp.route('/from-quote/<int:quote_id>', methods=['POST'])
@login_required
def from_quote(quote_id):
    quote = Quote.query.filter_by(
        id=quote_id, user_id=current_user.id).first_or_404()

    invoice = Invoice(
        user_id=current_user.id,
        customer_id=quote.customer_id,
        project_id=quote.project_id,
        quote_id=quote.id,
        number=_next_number(),
        title=quote.title,
        notes=quote.notes,
        deposit=quote.deposit,
        po_number=quote.po_number,
        public_token=_new_invoice_token(),
    )
    db.session.add(invoice)
    for item in quote.items:
        invoice.items.append(InvoiceItem(
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
        ))
    invoice.recalculate_total()
    quote.status = 'converted'
    db.session.commit()
    flash('Invoice created from proposal.', 'success')
    return redirect(url_for('invoices.edit', invoice_id=invoice.id))


# ── delete / send / pay ────────────────────────────────────────────────────

@invoice_bp.route('/<int:invoice_id>/delete', methods=['POST'])
@login_required
def delete(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)
    db.session.delete(invoice)
    db.session.commit()
    flash('Invoice deleted.', 'success')
    return redirect(url_for('invoices.index'))


@invoice_bp.route('/<int:invoice_id>/send', methods=['POST'])
@login_required
def send(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)
    if invoice.status == 'draft':
        invoice.status = 'sent'
    if not invoice.sent_at:
        invoice.sent_at = datetime.utcnow()
    if not _public_link_is_active(invoice):
        _refresh_public_link(invoice)
    db.session.commit()
    link = url_for('invoices.public_view', token=invoice.public_token, _external=True)
    flash(f'Invoice marked as sent. Shareable link: {link}', 'success')
    return redirect(url_for('invoices.edit', invoice_id=invoice.id))


@invoice_bp.route('/<int:invoice_id>/mark-paid', methods=['POST'])
@login_required
def mark_paid(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)

    method = (request.form.get('payment_method') or '').strip()
    if method not in PAYMENT_METHODS:
        method = 'Other'
    paid_date_raw = (request.form.get('paid_date') or '').strip()
    try:
        paid_at = datetime.strptime(paid_date_raw, '%Y-%m-%d') if paid_date_raw else datetime.utcnow()
    except ValueError:
        paid_at = datetime.utcnow()

    invoice.status = 'paid'
    invoice.paid_at = paid_at
    invoice.payment_method = method

    # Optionally record the payment as Income on the linked project.
    record_income = request.form.get('record_income') == 'on'
    if record_income and invoice.project_id and invoice.income_id is None:
        income = Income(
            project_id=invoice.project_id,
            amount=invoice.total or 0,
            source=f"Invoice {invoice.number or invoice.id}",
            date=paid_at,
            note=f"Auto-recorded from paid invoice {invoice.number or invoice.id}",
        )
        db.session.add(income)
        db.session.flush()
        invoice.income_id = income.id
        flash('Marked paid and recorded income on the linked project.', 'success')
    else:
        flash('Invoice marked as paid.', 'success')

    db.session.commit()
    return redirect(url_for('invoices.edit', invoice_id=invoice.id))


@invoice_bp.route('/<int:invoice_id>/unpay', methods=['POST'])
@login_required
def unpay(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)
    # Remove any auto-recorded income so we don't leave an orphan row.
    if invoice.income_id is not None:
        income = Income.query.get(invoice.income_id)
        if income is not None:
            db.session.delete(income)
        invoice.income_id = None
    invoice.status = 'sent' if invoice.sent_at else 'draft'
    invoice.paid_at = None
    invoice.payment_method = None
    db.session.commit()
    flash('Payment reverted.', 'success')
    return redirect(url_for('invoices.edit', invoice_id=invoice.id))


@invoice_bp.route('/<int:invoice_id>/email', methods=['POST'])
@login_required
def email(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)
    try:
        ok, message = send_invoice_email(invoice)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        ok, message = False, f'Email failed: {exc}'
    flash(message, 'success' if ok else 'error')
    return redirect(url_for('invoices.edit', invoice_id=invoice.id))


@invoice_bp.route('/<int:invoice_id>/pdf')
@login_required
def pdf(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)
    buf = build_invoice_pdf(invoice)
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f'{invoice.number or invoice.id}.pdf')


# ── public view (no login) ─────────────────────────────────────────────────

@invoice_bp.route('/i/<token>')
@limiter.limit("60 per minute")
def public_view(token):
    invoice = _get_public_invoice(token)
    return render_template('invoices/public.html', invoice=invoice, company=COMPANY)


@invoice_bp.route('/i/<token>/pdf')
@limiter.limit("10 per minute")
def public_pdf(token):
    invoice = _get_public_invoice(token)
    buf = build_invoice_pdf(invoice)
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f'{invoice.number or invoice.id}.pdf')
