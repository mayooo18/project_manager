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
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from permissions import owner_required

from extensions import db, limiter
from models import Invoice, InvoiceItem, Customer, Quote, Project, Income, Reminder
from forms import DeleteForm
from quote_routes import (
    COMPANY, LOGO_PATH, _pdf_text, _parse_items, _new_token as _new_quote_token,
    safe_filename,
)

invoice_bp = Blueprint('invoices', __name__, url_prefix='/invoices')

PAGE_SIZE = 100
# Status groups for the list filter tabs (Active / All / Archived).
INVOICE_ACTIVE_STATUSES = ('draft', 'sent')
INVOICE_ARCHIVED_STATUSES = ('paid', 'void')
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


# ── Payment-deadline reminders (F2) ──────────────────────────────────────────

def _sync_payment_reminder(invoice):
    """Create or update the payment-due reminder for a deadline invoice.

    No-op for invoices without deadlines. Idempotent: one reminder per invoice,
    kept in step with the current due date. Caller commits.
    """
    if not invoice.has_deadlines:
        return
    due = invoice.payment_due_date
    if due is None:
        return
    cust = invoice.customer.name if invoice.customer else 'customer'
    text = f"Payment due — invoice {invoice.number or invoice.id} ({cust})"
    rem = Reminder.query.filter_by(invoice_id=invoice.id).first()
    if rem is None:
        rem = Reminder(user_id=invoice.user_id, invoice_id=invoice.id)
        db.session.add(rem)
    rem.text = text
    rem.due_date = due
    rem.is_done = False


def _complete_payment_reminder(invoice):
    """Mark the invoice's payment reminder done (e.g. once it's paid)."""
    rem = Reminder.query.filter_by(invoice_id=invoice.id).first()
    if rem is not None:
        rem.is_done = True


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
                                  leading=16, spaceAfter=3,
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
    # On a retainage invoice the Total is the gross for the period, and the
    # retainage held is shown as a deduction so the customer sees the net due.
    gross_label = 'Gross this period' if invoice.retainage_amount else 'Total'
    data.append([Paragraph(f'<b>{gross_label}</b>', small),
                 Paragraph(f"<b>${invoice.total:,.2f}</b>", small_r)])
    if invoice.deposit:
        data.append([Paragraph('Deposit', small),
                     Paragraph(f"-${invoice.deposit:,.2f}", small_r)])
    if invoice.retainage_amount:
        pct_txt = f" ({invoice.retainage_percent:g}%)" if invoice.retainage_percent else ""
        data.append([Paragraph(f'Less retainage{pct_txt}', small),
                     Paragraph(f"-${invoice.retainage_amount:,.2f}", small_r)])
    balance = 0.0 if invoice.status == 'paid' else (
        (invoice.total or 0) - (invoice.deposit or 0) - (invoice.retainage_amount or 0))
    due_label = 'Net Due This Period' if invoice.retainage_amount else 'Balance Due'
    data.append([Paragraph(f'<b>{due_label}</b>', small),
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

    # ── Contract progress-billing summary (F1) ──
    # Shown only for invoices on a contract that uses retainage, so ordinary
    # invoices (and Simple-contract progress invoices) are completely unchanged.
    contract = invoice.contract
    if contract is not None and (invoice.retainage_amount
                                 or invoice.is_retainage_release
                                 or contract.retainage_active):
        # "Previously billed" excludes this draw's gross; a retainage release is
        # not a draw, so it counts all draws as previously billed.
        prev_billed = (contract.billed_to_date or 0) - (
            0 if invoice.is_retainage_release else (invoice.total or 0))
        this_label = ('This retainage release' if invoice.is_retainage_release
                      else 'This invoice (gross)')
        summ_rows = [
            ('Contract total', contract.contract_total or 0),
            ('Previously billed', prev_billed),
            ('Retainage held to date', contract.retainage_held_to_date),
            (this_label, invoice.total or 0),
            ('Balance remaining to bill', contract.remaining_to_bill),
        ]
        summ_data = [[Paragraph(k, small), Paragraph(f"${v:,.2f}", small_r)]
                     for k, v in summ_rows]
        summ_table = Table(summ_data, colWidths=[5.2 * inch, 1.8 * inch])
        summ_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('LINEBELOW', (0, 0), (-1, -2), 0.25, colors.HexColor('#dddddd')),
        ]))
        elems.append(Paragraph('Contract Summary', section))
        elems.append(Spacer(1, 4))
        elems.append(summ_table)
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


def build_suspension_notice_pdf(invoice):
    """A 7-day written notice of intent to suspend work on an overdue invoice.

    Reuses the company letterhead. Fills in the property/contract, the invoice
    number, the amount overdue and the date seven calendar days out, so the
    notice documents that written warning was given before any suspension."""
    import os
    from datetime import date
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6 * inch,
                            bottomMargin=0.6 * inch, leftMargin=0.75 * inch,
                            rightMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small = ParagraphStyle('small', parent=normal, fontSize=9, leading=13)
    small_r = ParagraphStyle('small_r', parent=small, alignment=TA_RIGHT)
    body = ParagraphStyle('body', parent=normal, fontSize=10.5, leading=16, spaceAfter=10)
    title = ParagraphStyle('title', parent=styles['Title'], fontSize=15,
                           alignment=TA_CENTER, spaceAfter=2)
    company_name = ParagraphStyle('coname', parent=normal, fontSize=13,
                                  leading=16, fontName='Helvetica-Bold')

    today = date.today()
    deadline = today + timedelta(days=7)
    cust = invoice.customer
    amount = invoice.balance_due
    due = invoice.payment_due_date
    overdue_days = (today - due).days if due else None
    contract = invoice.contract
    prop = (contract.title if contract else invoice.title)

    elems = []
    left = []
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image(LOGO_PATH)
            ratio = logo.imageHeight / float(logo.imageWidth)
            logo.drawWidth = 1.7 * inch
            logo.drawHeight = 1.7 * inch * ratio
            logo.hAlign = 'LEFT'
            left += [logo, Spacer(1, 4)]
        except Exception:
            pass
    left += [Paragraph(COMPANY['name'], company_name),
             Paragraph(COMPANY['address_line1'], small),
             Paragraph(COMPANY['address_line2'], small),
             Paragraph(COMPANY['phone'], small),
             Paragraph(COMPANY['email'], small)]
    right = [Paragraph(f"DATE {today.strftime('%m/%d/%y')}", small_r)]
    head = Table([[left, right]], colWidths=[4.0 * inch, 3.0 * inch])
    head.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                              ('LEFTPADDING', (0, 0), (-1, -1), 0),
                              ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
    elems += [head, Spacer(1, 18)]

    elems.append(Paragraph('NOTICE OF INTENT TO SUSPEND WORK', title))
    elems.append(Spacer(1, 14))

    to = [Paragraph('<b>To:</b>', small), Paragraph(_pdf_text(cust.name, 150), small)]
    if cust.address:
        to.append(Paragraph(_pdf_text(cust.address, 250), small))
    for p in to:
        elems.append(p)
    elems.append(Spacer(1, 6))
    elems.append(Paragraph(f"<b>Re:</b> {_pdf_text(prop, 200)} — invoice "
                           f"{_pdf_text(invoice.number or invoice.id, 50)}", small))
    elems.append(Spacer(1, 14))

    overdue_txt = (f"is now {overdue_days} day{'s' if overdue_days != 1 else ''} past due"
                   if overdue_days is not None else "is past due")
    elems.append(Paragraph(
        f"This letter serves as formal written notice that invoice "
        f"<b>{_pdf_text(invoice.number or invoice.id, 50)}</b> in the amount of "
        f"<b>${amount:,.2f}</b>"
        + (f", due {due.strftime('%B %d, %Y')}," if due else ",")
        + f" remains unpaid and {overdue_txt}.", body))
    elems.append(Paragraph(
        f"In accordance with the terms of our contract, you are hereby given "
        f"<b>seven (7) calendar days</b> from the date of this notice to remit "
        f"payment in full. If payment is not received by "
        f"<b>{deadline.strftime('%B %d, %Y')}</b>, {COMPANY['name']} will suspend "
        f"all work on the above-referenced property until the account is brought "
        f"current. Any resulting delay or cost is the responsibility of the owner "
        f"under the contract.", body))
    elems.append(Paragraph(
        "We value our working relationship and hope to resolve this promptly. "
        "Please contact us if you have any questions regarding this account.", body))
    elems.append(Spacer(1, 20))
    elems.append(Paragraph("Sincerely,", small))
    elems.append(Spacer(1, 26))
    elems.append(Paragraph("_______________________________", small))
    elems.append(Paragraph(COMPANY['name'], small))

    elems.append(Spacer(1, 24))
    elems.append(Paragraph(COMPANY['footer'],
                           ParagraphStyle('foot', parent=normal, alignment=TA_CENTER,
                                          fontSize=9, fontName='Helvetica-Bold')))
    doc.build(elems)
    buf.seek(0)
    return buf


def send_suspension_notice_email(invoice):
    """Email the 7-day suspension notice (PDF) to the customer via Gmail.
    Returns (ok, message)."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials
    from datetime import date

    customer = invoice.customer
    if not customer.email:
        return False, 'This customer has no email address on file. Add one on the Customers page.'
    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    deadline = date.today() + timedelta(days=7)
    html = (
        f"<p>Please find attached a formal notice regarding overdue invoice "
        f"<strong>{invoice.number or invoice.id}</strong> "
        f"(${invoice.balance_due:,.2f}).</p>"
        f"<p>Payment is requested within <strong>seven (7) calendar days</strong> "
        f"(by {deadline.strftime('%B %d, %Y')}) to avoid a suspension of work on "
        f"the project. The attached letter has the details.</p>"
        f"<p>{COMPANY['name']}<br>{COMPANY['phone']}</p>")

    msg = MIMEMultipart('mixed')
    msg['To'] = customer.email
    msg['From'] = 'me'
    msg['Subject'] = (f"Notice of intent to suspend work — invoice "
                      f"{invoice.number or invoice.id}")
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)

    pdf_bytes = build_suspension_notice_pdf(invoice).read()
    att = MIMEApplication(pdf_bytes, _subtype='pdf')
    safe_name = safe_filename(customer.name, invoice.number or ('Invoice ' + str(invoice.id)),
                              'Notice')
    att.add_header('Content-Disposition', 'attachment', filename=f'7-day-notice-{safe_name}.pdf')
    msg.attach(att)

    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
    return True, f'7-day notice emailed to {customer.email}.'


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
    safe_name = safe_filename(invoice.customer.name if invoice.customer else None,
                              invoice.number or ('Invoice ' + str(invoice.id)),
                              'Invoice')
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
    view = request.args.get('view', 'active')
    search = (request.args.get('q') or '').strip()

    base = Invoice.query.filter_by(user_id=current_user.id)
    if search:
        like = f'%{search}%'
        base = base.join(Customer).filter(
            or_(Invoice.title.ilike(like), Invoice.number.ilike(like),
                Customer.name.ilike(like)))

    # Tab counts reflect the current search so the numbers stay consistent.
    status_counts = dict(
        base.with_entities(Invoice.status, db.func.count(Invoice.id))
        .group_by(Invoice.status).all())
    counts = {
        'active': sum(status_counts.get(s, 0) for s in INVOICE_ACTIVE_STATUSES),
        'archived': sum(status_counts.get(s, 0) for s in INVOICE_ARCHIVED_STATUSES),
        'all': sum(status_counts.values()),
    }

    listing = base
    if view == 'active':
        listing = listing.filter(Invoice.status.in_(INVOICE_ACTIVE_STATUSES))
    elif view == 'archived':
        listing = listing.filter(Invoice.status.in_(INVOICE_ARCHIVED_STATUSES))

    invoices = (listing
                .options(selectinload(Invoice.customer), selectinload(Invoice.project))
                .order_by(Invoice.created_at.desc())
                .paginate(page=max(request.args.get('page', 1, type=int) or 1, 1),
                          per_page=PAGE_SIZE, error_out=False))
    return render_template('invoices/list.html', invoices=invoices.items,
                           pagination=invoices, view=view, counts=counts,
                           q=search, delete_form=DeleteForm())


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
    if quote.status != 'approved':
        flash('Only an approved proposal can be converted to an invoice.', 'error')
        return redirect(url_for('quotes.edit', quote_id=quote.id))
    if Invoice.query.filter_by(quote_id=quote.id, user_id=current_user.id).first():
        flash('This proposal already has an invoice.', 'error')
        return redirect(url_for('quotes.edit', quote_id=quote.id))

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
@owner_required
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
    # Start / refresh the payment-deadline reminder (no-op without deadlines).
    _sync_payment_reminder(invoice)
    # Archive a PDF snapshot of exactly what was sent.
    from archive_routes import archive_document
    archive_document(current_user.id, 'invoice', invoice.id,
                     invoice.number, invoice.title, build_invoice_pdf(invoice))
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
    # The deadline is met once it's paid — close its reminder (no-op if none).
    _complete_payment_reminder(invoice)

    # Optionally record the payment as Income on the linked project.
    # Subtract any retainage withheld so income reflects what was actually
    # received this payment. Retainage is null on normal invoices, so this is a
    # no-op for every non-retainage invoice (deposit handling is unchanged).
    net_received = (invoice.total or 0) - (invoice.retainage_amount or 0)
    record_income = request.form.get('record_income') == 'on'
    if record_income and invoice.project_id and invoice.income_id is None:
        income = Income(
            project_id=invoice.project_id,
            amount=net_received,
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
@owner_required
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


def _receipt_context(invoice):
    """Build the receipt's stage + progress info for a paid invoice.

    For a contract draw invoice this names the stage ("Deposit — Payment 2 of 4",
    "Final payment") and the running contract progress. For a plain invoice it just
    carries the amount paid. Returns a dict the receipt template reads.
    """
    ctx = {
        'amount_paid': invoice.net_due,          # total − deposit − retainage held
        'stage_label': None,
        'show_progress': False,
    }
    linked = getattr(invoice, 'contract_draw', None) or []
    if linked:
        draw = linked[0]
        contract = draw.contract
        ordered = list(contract.draws)           # ordered by sequence
        count = len(ordered)
        idx = next((i for i, d in enumerate(ordered, start=1) if d.id == draw.id), None)
        desc = (draw.description or '').strip()
        if idx == count and count:
            stage = 'Final payment'
        elif idx:
            stage = f'Payment {idx} of {count}'
        else:
            stage = 'Payment'
        ctx['stage_label'] = f'{desc} — {stage}' if desc else stage
        total = contract.contract_total or contract.scheduled_total or 0
        ctx['show_progress'] = True
        ctx['contract_total'] = total
        ctx['paid_to_date'] = contract.paid_to_date
        ctx['remaining'] = total - contract.paid_to_date
    return ctx


def send_invoice_receipt_email(invoice):
    """Email a paid receipt (view link + PAID-stamped PDF) to the customer via Gmail.
    Returns (ok, message)."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials

    if invoice.status != 'paid':
        return False, 'This invoice is not marked paid yet.'

    customer = invoice.customer
    if not customer.email:
        return False, 'This customer has no email address on file. Add one on the Customers page.'

    if not _public_link_is_active(invoice):
        _refresh_public_link(invoice)

    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    link = url_for('invoices.public_view', token=invoice.public_token, _external=True)
    html = render_template('invoices/receipt_email.html', invoice=invoice, link=link,
                           company=COMPANY, receipt=_receipt_context(invoice))

    msg = MIMEMultipart('mixed')
    msg['To'] = customer.email
    msg['From'] = 'me'
    msg['Subject'] = f"Receipt for Invoice {invoice.number or invoice.id} from {COMPANY['name']}"

    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)

    pdf_bytes = build_invoice_pdf(invoice).read()   # already stamps PAID when status == 'paid'
    attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
    safe_name = safe_filename(invoice.customer.name if invoice.customer else None,
                              invoice.number or ('Invoice ' + str(invoice.id)),
                              'Receipt')
    attachment.add_header('Content-Disposition', 'attachment',
                          filename=f'{safe_name}.pdf')
    msg.attach(attachment)

    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
    return True, f'Receipt emailed to {customer.email}.'


@invoice_bp.route('/<int:invoice_id>/receipt/email', methods=['POST'])
@login_required
def receipt_email(invoice_id):
    invoice = _owned_invoice_or_404(invoice_id)
    try:
        ok, message = send_invoice_receipt_email(invoice)
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
                     download_name=f"{safe_filename(invoice.customer.name if invoice.customer else None, invoice.number or ('Invoice ' + str(invoice.id)), 'Invoice')}.pdf")


@invoice_bp.route('/<int:invoice_id>/suspension-notice.pdf')
@login_required
def suspension_notice_pdf(invoice_id):
    """Preview / download the 7-day notice of intent to suspend work (F2)."""
    invoice = _owned_invoice_or_404(invoice_id)
    buf = build_suspension_notice_pdf(invoice)
    name = safe_filename(invoice.customer.name if invoice.customer else None,
                         invoice.number or ('Invoice ' + str(invoice.id)), 'Notice')
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f"7-day-notice-{name}.pdf")


@invoice_bp.route('/<int:invoice_id>/suspension-notice/email', methods=['POST'])
@login_required
def suspension_notice_email(invoice_id):
    """Email the 7-day notice to the customer (confirmed from the invoice page)."""
    invoice = _owned_invoice_or_404(invoice_id)
    try:
        ok, message = send_suspension_notice_email(invoice)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        ok, message = False, f'Email failed: {exc}'
    flash(message, 'success' if ok else 'error')
    return redirect(url_for('invoices.edit', invoice_id=invoice.id))


# ── Invoice packet builder (F4) ──────────────────────────────────────────────

def _merge_pdfs(buffers):
    """Concatenate several PDF BytesIO buffers into one. Returns a BytesIO."""
    from pypdf import PdfReader, PdfWriter
    writer = PdfWriter()
    for buf in buffers:
        buf.seek(0)
        reader = PdfReader(buf)
        for page in reader.pages:
            writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    out.seek(0)
    return out


def _packet_waivers(invoice):
    """The customer's lien-waiver documents, offered for inclusion."""
    from models import GcDocument
    if not invoice.customer_id:
        return []
    return (GcDocument.query
            .filter_by(user_id=current_user.id, customer_id=invoice.customer_id)
            .filter(GcDocument.doc_kind != 'completion')
            .order_by(GcDocument.created_at.desc()).all())


def _invoice_draw(invoice):
    """The contract draw this invoice bills, if any (for its evidence)."""
    draws = getattr(invoice, 'contract_draw', None) or []
    return draws[0] if draws else None


def _evidence_as_pdf(ev):
    """Return a BytesIO PDF for one evidence file, or None if it can't be
    embedded. PDFs pass through; images become a single captioned page;
    other document types (docx/xls/…) are skipped."""
    import os
    from flask import current_app
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], ev.filename)
    if not os.path.exists(path):
        return None
    ext = (ev.original_name or ev.filename or '').rsplit('.', 1)[-1].lower()
    if ext == 'pdf':
        with open(path, 'rb') as fh:
            return BytesIO(fh.read())
    if ext in ('png', 'jpg', 'jpeg', 'gif'):
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Image, Spacer, Paragraph
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.utils import ImageReader
            buf = BytesIO()
            doc = SimpleDocTemplate(buf, pagesize=letter,
                                    topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                                    leftMargin=0.6 * inch, rightMargin=0.6 * inch)
            iw, ih = ImageReader(path).getSize()
            max_w, max_h = 7.0 * inch, 8.2 * inch
            scale = min(max_w / iw, max_h / ih, 1.0)
            img = Image(path, width=iw * scale, height=ih * scale)
            styles = getSampleStyleSheet()
            caption = f"{ev.kind.replace('_', ' ').title()}" + (f" — {ev.note}" if ev.note else "")
            doc.build([Paragraph(caption, styles['Normal']), Spacer(1, 8), img])
            buf.seek(0)
            return buf
        except Exception:
            return None
    return None  # docx / xls / etc. can't be embedded in the PDF packet


@invoice_bp.route('/<int:invoice_id>/packet')
@login_required
def packet(invoice_id):
    """Builder page: choose which documents go into the combined packet."""
    invoice = _owned_invoice_or_404(invoice_id)
    contract = invoice.contract
    sworn_enabled = bool(contract and contract.sworn_statements_enabled)
    evidence_required = bool(contract and contract.evidence_required)
    draw = _invoice_draw(invoice)
    evidence = draw.evidence if draw is not None else []
    return render_template(
        'invoices/packet.html', invoice=invoice, contract=contract,
        sworn_statements=invoice.sworn_statements,
        waivers=_packet_waivers(invoice),
        sworn_enabled=sworn_enabled,
        evidence_required=evidence_required,
        evidence=evidence)


@invoice_bp.route('/<int:invoice_id>/packet/build', methods=['POST'])
@login_required
def packet_build(invoice_id):
    """Merge the selected documents into one PDF and return it.

    Warn-but-allow: if a required item was left out, the builder page already
    flagged it; this still generates whatever was selected.
    """
    from models import GcDocument
    invoice = _owned_invoice_or_404(invoice_id)

    parts = [build_invoice_pdf(invoice)]  # the invoice always leads the packet

    sworn_id = request.form.get('sworn_statement_id', type=int)
    if sworn_id:
        from models import SwornStatement
        from sworn_routes import build_sworn_pdf
        st = SwornStatement.query.filter_by(
            id=sworn_id, user_id=current_user.id, invoice_id=invoice.id).first()
        if st is not None:
            parts.append(build_sworn_pdf(st))

    waiver_id = request.form.get('waiver_id', type=int)
    if waiver_id:
        from waiver_routes import build_gc_document_pdf
        doc = GcDocument.query.filter_by(
            id=waiver_id, user_id=current_user.id).first()
        if doc is not None:
            parts.append(build_gc_document_pdf(doc))

    # Evidence attachments (F5): append the billed draw's photos/tickets/reports
    # when the user opted to include them. Images become a page each; PDFs pass
    # through; other document types are skipped.
    if request.form.get('include_evidence'):
        draw = _invoice_draw(invoice)
        if draw is not None:
            for ev in draw.evidence:
                buf = _evidence_as_pdf(ev)
                if buf is not None:
                    parts.append(buf)

    merged = _merge_pdfs(parts)
    name = safe_filename(invoice.customer.name if invoice.customer else None,
                         invoice.number or ('Invoice ' + str(invoice.id)), 'Packet')
    return send_file(merged, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{name}-packet.pdf')


# ── public view (no login) ─────────────────────────────────────────────────

@invoice_bp.route('/i/<token>')
@limiter.limit("60 per minute")
def public_view(token):
    invoice = _get_public_invoice(token)
    # Record the first time the client opens the invoice (F2). This starts the
    # payment clock; a reminder already exists from when it was sent, so refresh
    # its due date to reflect the received date.
    if invoice.received_at is None:
        invoice.received_at = datetime.utcnow()
        _sync_payment_reminder(invoice)
        db.session.commit()
    return render_template('invoices/public.html', invoice=invoice, company=COMPANY)


@invoice_bp.route('/i/<token>/pdf')
@limiter.limit("10 per minute")
def public_pdf(token):
    invoice = _get_public_invoice(token)
    buf = build_invoice_pdf(invoice)
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f"{safe_filename(invoice.customer.name if invoice.customer else None, invoice.number or ('Invoice ' + str(invoice.id)), 'Invoice')}.pdf")
