"""
Final receipt / paid-invoice feature.

A paid invoice can produce a dedicated RECEIPT PDF — numbered separately from
invoices (RCT-XXXX), showing this payment plus any earlier payments on the same
job, the total paid, and the remaining balance. The receipt can be downloaded,
or emailed to the customer through a preview-then-send screen (the email is
never sent without an explicit confirmation).

Self-contained Blueprint. Reuses the Phase 1/2 letterhead helpers from
quote_routes / invoice_routes without modifying how invoices are built.
"""

import base64
from datetime import datetime
from io import BytesIO

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, send_file, abort,
)
from flask_login import login_required, current_user

from extensions import db
from models import Invoice, ReceiptSend, Project
from quote_routes import COMPANY, LOGO_PATH, _pdf_text, safe_filename
from invoice_routes import _public_link_is_active, _refresh_public_link, _merge_pdfs

receipt_bp = Blueprint('receipts', __name__, url_prefix='/receipts')


# ── helpers ──────────────────────────────────────────────────────────────────

def _owned_invoice_or_404(invoice_id):
    return Invoice.query.filter_by(
        id=invoice_id, user_id=current_user.id).first_or_404()


def _payment_amount(invoice):
    """Cash actually received for a paid invoice.

    Mirrors the income recorded on mark-paid: gross this period minus any
    retainage held back. For a plain invoice (no retainage) this is the total.
    """
    return (invoice.total or 0) - (invoice.retainage_amount or 0)


def _job_paid_invoices(invoice):
    """All paid invoices on the same job, oldest payment first.

    When the invoice isn't linked to a job (project), the receipt simply covers
    this one invoice.
    """
    if not invoice.project_id:
        return [invoice]
    paid = (Invoice.query
            .filter_by(user_id=current_user.id,
                       project_id=invoice.project_id, status='paid')
            .all())
    if invoice not in paid:
        paid.append(invoice)
    paid.sort(key=lambda inv: (inv.paid_at or inv.created_at or datetime.min))
    return paid


def _job_balance(invoice):
    """Remaining balance on the job after the payments counted on this receipt.

    If the job has a contract, it's contract total minus everything paid so far.
    Otherwise it's whatever other invoices on the job are still unpaid (0 for a
    single paid invoice).
    """
    paid_invoices = _job_paid_invoices(invoice)
    total_paid = sum(_payment_amount(inv) for inv in paid_invoices)

    contract = invoice.contract
    if contract is not None:
        job_total = contract.contract_total or getattr(contract, 'scheduled_total', 0) or 0
        if job_total:
            return round(job_total - total_paid, 2)

    if invoice.project_id:
        outstanding = (Invoice.query
                       .filter(Invoice.user_id == current_user.id,
                               Invoice.project_id == invoice.project_id,
                               Invoice.status.notin_(('paid', 'void')))
                       .all())
        return round(sum(inv.balance_due for inv in outstanding), 2)

    return round(invoice.balance_due, 2)


def _next_receipt_number():
    """Next per-user receipt number, e.g. RCT-0007.

    Numbered independently of invoices, derived from the highest existing
    receipt number so a deletion never lets a number be reused.
    """
    import re
    best = 0
    for inv in Invoice.query.filter_by(user_id=current_user.id).all():
        match = re.search(r'(\d+)$', inv.receipt_number or '')
        if match:
            best = max(best, int(match.group(1)))
    return f"RCT-{best + 1:04d}"


def _ensure_receipt_number(invoice):
    """Assign a stable RCT number the first time a receipt is produced. Caller commits."""
    if not invoice.receipt_number:
        invoice.receipt_number = _next_receipt_number()
    return invoice.receipt_number


def _first_name(name):
    return (name or '').strip().split(' ')[0] if name else 'there'


def _default_receipt_email(invoice):
    """The editable default subject + body for the receipt email (approved wording)."""
    cust = invoice.customer
    job = invoice.title or 'your project'
    amount = _payment_amount(invoice)
    method = invoice.payment_method or 'payment'
    date_str = invoice.paid_at.strftime('%m/%d/%Y') if invoice.paid_at else ''
    balance = _job_balance(invoice)

    subject = f"Receipt — Payment Received — {job} ({invoice.number or invoice.id})"
    body = (
        f"Hi {_first_name(cust.name if cust else None)},\n\n"
        f"Thank you — we received your {method} payment of ${amount:,.2f} on "
        f"{date_str} for {job}. Your balance is now ${balance:,.2f}. Your "
        f"receipt is attached.\n\n"
        f"We appreciate your business.\n\n"
        f"Mario, Optimal SES\n"
        f"{COMPANY['phone']}"
    )
    return subject, body


# ── receipt PDF ────────────────────────────────────────────────────────────────

def build_receipt_pdf(invoice):
    """Render a paid-receipt PDF on the Optimal SES letterhead."""
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
                                  leading=16, spaceAfter=3, fontName='Helvetica-Bold')
    section = ParagraphStyle('section', parent=normal,
                             fontName='Helvetica-Bold', fontSize=10)
    green = colors.HexColor('#16a34a')
    ink = colors.HexColor('#111111')

    paid_invoices = _job_paid_invoices(invoice)
    total_paid = sum(_payment_amount(inv) for inv in paid_invoices)
    balance = _job_balance(invoice)
    fully_paid = balance <= 0.005
    earlier = [inv for inv in paid_invoices if inv.id != invoice.id]

    elems = []

    # ── Header: logo + company (left) | RECEIPT title + numbers (right) ──
    left_cell = []
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image(LOGO_PATH)
            ratio = logo.imageHeight / float(logo.imageWidth)
            logo.drawWidth = 1.7 * inch
            logo.drawHeight = 1.7 * inch * ratio
            logo.hAlign = 'LEFT'
            left_cell += [logo, Spacer(1, 4)]
        except Exception:
            pass
    left_cell.append(Paragraph(COMPANY['name'], company_name))
    left_cell.append(Paragraph(COMPANY['address_line1'], small))
    left_cell.append(Paragraph(COMPANY['address_line2'], small))
    left_cell.append(Paragraph(COMPANY['phone'], small))
    left_cell.append(Paragraph(COMPANY['email'], small))

    paid_date = invoice.paid_at.strftime('%m/%d/%y') if invoice.paid_at else ''
    right_cell = [
        Paragraph('RECEIPT', doc_title),
        Spacer(1, 8),
        Paragraph(f"RECEIPT # {_pdf_text(invoice.receipt_number or 'RCT', 50)}", small_r),
        Paragraph(f"FOR INVOICE {_pdf_text(invoice.number or invoice.id, 50)}", small_r),
        Paragraph(f"DATE {paid_date}", small_r),
    ]
    stamp = ParagraphStyle('stamp', parent=normal, fontSize=15, textColor=green,
                           fontName='Helvetica-Bold', alignment=TA_RIGHT, leading=18)
    right_cell.append(Spacer(1, 8))
    right_cell.append(Paragraph(
        'PAID IN FULL' if fully_paid else 'PAYMENT RECEIVED', stamp))

    header = Table([[left_cell, right_cell]], colWidths=[3.6 * inch, 3.4 * inch])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems += [header, Spacer(1, 12)]

    # ── Received from (left) | Job (right) ──
    c = invoice.customer
    recv = [Paragraph('<b>RECEIVED FROM</b>', small),
            Paragraph(_pdf_text(c.name, 150), small)]
    if c.address:
        recv.append(Paragraph(_pdf_text(c.address, 250), small))
    if c.phone:
        recv.append(Paragraph(_pdf_text(c.phone, 30), small))
    if c.email:
        recv.append(Paragraph(_pdf_text(c.email, 150), small))

    job = invoice.project
    jobcell = [Paragraph('<b>JOB</b>', small),
               Paragraph(_pdf_text(job.name if job else invoice.title, 200), small)]
    if job and job.address:
        jobcell.append(Paragraph(_pdf_text(job.address, 250), small))

    jt = Table([[recv, jobcell]], colWidths=[3.6 * inch, 3.4 * inch])
    jt.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems += [jt, Spacer(1, 14)]

    # ── Invoice line items + invoice total ──
    data = [[Paragraph('<b>Description</b>', small),
             Paragraph('<b>Amount</b>', small_r)]]
    for item in invoice.items:
        data.append([Paragraph(_pdf_text(item.description, preserve_newlines=True), small),
                     Paragraph(f"${item.line_total:,.2f}", small_r)])
    data.append([Paragraph('<b>Invoice total</b>', small),
                 Paragraph(f"<b>${invoice.total or 0:,.2f}</b>", small_r)])
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
    elems += [items_table, Spacer(1, 16)]

    # ── This payment + earlier payments on the job ──
    pay_rows = [[Paragraph('<b>THIS PAYMENT</b>', small), Paragraph('', small_r)]]
    this_label = f"{paid_date}" + (f" · {_pdf_text(invoice.payment_method, 40)}"
                                   if invoice.payment_method else "")
    pay_rows.append([Paragraph(this_label, small),
                     Paragraph(f"${_payment_amount(invoice):,.2f}", small_r)])

    if earlier:
        pay_rows.append([Paragraph('<b>EARLIER PAYMENTS ON THIS JOB</b>', small),
                         Paragraph('', small_r)])
        for inv in earlier:
            d = inv.paid_at.strftime('%m/%d/%y') if inv.paid_at else ''
            label = d + (f" · {_pdf_text(inv.payment_method, 40)}" if inv.payment_method else "")
            label += f" · {_pdf_text(inv.number or inv.id, 40)}"
            pay_rows.append([Paragraph(label, small),
                             Paragraph(f"${_payment_amount(inv):,.2f}", small_r)])

    pay_rows.append([Paragraph('<b>Total paid</b>', section),
                     Paragraph(f"<b>${total_paid:,.2f}</b>", small_r)])
    pay_rows.append([Paragraph('<b>Balance due</b>', section),
                     Paragraph(f"<b>${max(balance, 0):,.2f}</b>", small_r)])

    pay_table = Table(pay_rows, colWidths=[5.2 * inch, 1.8 * inch])
    pay_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('LINEABOVE', (0, -2), (-1, -2), 0.75, ink),
    ]))
    elems += [pay_table, Spacer(1, 10)]

    if fully_paid:
        elems.append(Paragraph(
            'Job paid in full — thank you for your business.',
            ParagraphStyle('pif', parent=section, textColor=green, fontSize=11)))
        elems.append(Spacer(1, 6))

    if invoice.notes:
        elems += [Spacer(1, 6), Paragraph('Notes:', section), Spacer(1, 4),
                  Paragraph(_pdf_text(invoice.notes, preserve_newlines=True), small)]

    # ── Signature ──
    elems.append(Spacer(1, 26))
    elems.append(Paragraph('Signature: _______________________________', small))
    elems.append(Spacer(1, 2))
    elems.append(Paragraph('Mario, Optimal SES', small))

    elems.append(Spacer(1, 18))
    elems.append(Paragraph(COMPANY['footer'],
                           ParagraphStyle('foot', parent=normal, alignment=TA_CENTER,
                                          fontSize=10, fontName='Helvetica-Bold')))
    doc.build(elems)
    buf.seek(0)
    return buf


def send_receipt_email(invoice, subject, body):
    """Email the receipt PDF to the customer via Gmail. Returns (ok, message).

    `subject` / `body` are the (possibly edited) values confirmed on the preview
    screen. Records the send and refreshes the invoice's cached receipt fields.
    Caller commits.
    """
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials

    if invoice.status != 'paid':
        return False, 'This invoice is not marked paid yet.'

    customer = invoice.customer
    if not customer or not customer.email:
        return False, 'This customer has no email address on file. Add one on the Customers page.'

    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    _ensure_receipt_number(invoice)
    if not _public_link_is_active(invoice):
        _refresh_public_link(invoice)

    # Plain-text body keeps the customer's wording exactly as previewed.
    msg = MIMEMultipart('mixed')
    msg['To'] = customer.email
    msg['From'] = 'me'
    msg['Subject'] = subject or f"Receipt for Invoice {invoice.number or invoice.id}"
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(body or '', 'plain'))
    msg.attach(alt)

    pdf_bytes = build_receipt_pdf(invoice).read()
    attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
    safe_name = safe_filename(customer.name, invoice.receipt_number or 'Receipt', 'Receipt')
    attachment.add_header('Content-Disposition', 'attachment', filename=f'{safe_name}.pdf')
    msg.attach(attachment)

    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()

    now = datetime.utcnow()
    db.session.add(ReceiptSend(
        user_id=current_user.id, invoice_id=invoice.id,
        receipt_number=invoice.receipt_number, recipient=customer.email, sent_at=now))
    if invoice.receipt_first_sent_at is None:
        invoice.receipt_first_sent_at = now
    invoice.receipt_last_sent_at = now
    invoice.receipt_last_recipient = customer.email
    return True, f'Receipt emailed to {customer.email}.'


# ── routes ─────────────────────────────────────────────────────────────────────

@receipt_bp.route('/<int:invoice_id>/pdf')
@login_required
def pdf(invoice_id):
    """Download / preview the receipt PDF (paid invoices only)."""
    invoice = _owned_invoice_or_404(invoice_id)
    if invoice.status != 'paid':
        flash('A receipt is available only after the invoice is marked paid.', 'error')
        return redirect(url_for('invoices.edit', invoice_id=invoice.id))
    _ensure_receipt_number(invoice)
    db.session.commit()
    buf = build_receipt_pdf(invoice)
    name = safe_filename(invoice.customer.name if invoice.customer else None,
                         invoice.receipt_number or 'Receipt', 'Receipt')
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{name}.pdf')


@receipt_bp.route('/<int:invoice_id>/preview', methods=['GET'])
@login_required
def preview(invoice_id):
    """The preview-then-send screen: editable subject/body + embedded PDF."""
    invoice = _owned_invoice_or_404(invoice_id)
    if invoice.status != 'paid':
        flash('Mark the invoice paid first, then send the receipt.', 'error')
        return redirect(url_for('invoices.edit', invoice_id=invoice.id))
    _ensure_receipt_number(invoice)
    db.session.commit()
    subject, body = _default_receipt_email(invoice)
    no_email = not (invoice.customer and invoice.customer.email)
    return render_template('invoices/receipt_preview.html', invoice=invoice,
                           subject=subject, body=body, company=COMPANY, no_email=no_email)


@receipt_bp.route('/<int:invoice_id>/send', methods=['POST'])
@login_required
def send(invoice_id):
    """Send the receipt using the confirmed (edited) subject/body."""
    invoice = _owned_invoice_or_404(invoice_id)
    subject = (request.form.get('subject') or '').strip()
    body = request.form.get('body') or ''
    try:
        ok, message = send_receipt_email(invoice, subject, body)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        ok, message = False, f'Email failed: {exc}'
    flash(message, 'success' if ok else 'error')
    return redirect(url_for('invoices.edit', invoice_id=invoice.id))


# ── Job-complete email (all receipts attached) ─────────────────────────────────

def _owned_project_or_404(project_id):
    return Project.query.filter_by(id=project_id).first_or_404()


def _project_paid_invoices(project):
    """Paid (non-void) invoices on a job, oldest payment first."""
    paid = [inv for inv in project.invoices
            if inv.status == 'paid' and inv.user_id == current_user.id]
    paid.sort(key=lambda inv: (inv.paid_at or inv.created_at or datetime.min))
    return paid


def build_job_receipts_pdf(project):
    """One PDF holding a receipt page-set for every paid invoice on the job."""
    parts = [build_receipt_pdf(inv) for inv in _project_paid_invoices(project)]
    return _merge_pdfs(parts)


def _default_job_complete_email(project):
    """Editable default subject + body for the job-complete email."""
    cust = project.customer
    name = project.name or 'your project'
    subject = f"Your job is complete — {name}"
    body = (
        f"Hi {_first_name(cust.name if cust else None)},\n\n"
        f"Thank you for your business — {name} is complete and paid in full. "
        f"Your receipts are attached for your records.\n\n"
        f"It was a pleasure working with you.\n\n"
        f"Mario, Optimal SES\n"
        f"{COMPANY['phone']}"
    )
    return subject, body


def send_job_complete_email(project, subject, body):
    """Email the job-complete note with all receipts attached. Returns (ok, message).

    Records a receipt send for each included invoice so the app's "Receipt sent"
    markers and the job's Recent activity stay accurate. Caller commits.
    """
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials

    cust = project.customer
    if not cust or not cust.email:
        return False, 'This job has no customer email on file. Add one on the Customers page.'
    paid = _project_paid_invoices(project)
    if not paid:
        return False, 'This job has no paid invoices to send receipts for.'
    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    for inv in paid:
        _ensure_receipt_number(inv)

    msg = MIMEMultipart('mixed')
    msg['To'] = cust.email
    msg['From'] = 'me'
    msg['Subject'] = subject or f"Your job is complete — {project.name}"
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(body or '', 'plain'))
    msg.attach(alt)

    pdf_bytes = build_job_receipts_pdf(project).read()
    attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
    safe_name = safe_filename(cust.name, project.name or 'Job', 'Receipts')
    attachment.add_header('Content-Disposition', 'attachment', filename=f'{safe_name}.pdf')
    msg.attach(attachment)

    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()

    now = datetime.utcnow()
    for inv in paid:
        db.session.add(ReceiptSend(
            user_id=current_user.id, invoice_id=inv.id,
            receipt_number=inv.receipt_number, recipient=cust.email, sent_at=now))
        if inv.receipt_first_sent_at is None:
            inv.receipt_first_sent_at = now
        inv.receipt_last_sent_at = now
        inv.receipt_last_recipient = cust.email
    return True, f'Job-complete email with {len(paid)} receipt(s) sent to {cust.email}.'


@receipt_bp.route('/job/<int:project_id>/complete/pdf')
@login_required
def job_pdf(project_id):
    """All of the job's receipts merged into one PDF (download / preview)."""
    project = _owned_project_or_404(project_id)
    if not _project_paid_invoices(project):
        flash('This job has no paid invoices yet.', 'error')
        return redirect(url_for('project_detail', project_id=project.id))
    for inv in _project_paid_invoices(project):
        _ensure_receipt_number(inv)
    db.session.commit()
    buf = build_job_receipts_pdf(project)
    name = safe_filename(project.customer.name if project.customer else None,
                         project.name or 'Job', 'Receipts')
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{name}.pdf')


@receipt_bp.route('/job/<int:project_id>/complete/preview', methods=['GET'])
@login_required
def job_preview(project_id):
    """Preview-then-send screen for the job-complete email."""
    project = _owned_project_or_404(project_id)
    paid = _project_paid_invoices(project)
    if not paid:
        flash('This job has no paid invoices yet.', 'error')
        return redirect(url_for('project_detail', project_id=project.id))
    for inv in paid:
        _ensure_receipt_number(inv)
    db.session.commit()
    subject, body = _default_job_complete_email(project)
    no_email = not (project.customer and project.customer.email)
    return render_template('invoices/job_complete_preview.html', project=project,
                           subject=subject, body=body, company=COMPANY,
                           no_email=no_email, receipt_count=len(paid))


@receipt_bp.route('/job/<int:project_id>/complete/send', methods=['POST'])
@login_required
def job_send(project_id):
    """Send the job-complete email with the confirmed (edited) subject/body."""
    project = _owned_project_or_404(project_id)
    subject = (request.form.get('subject') or '').strip()
    body = request.form.get('body') or ''
    try:
        ok, message = send_job_complete_email(project, subject, body)
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        ok, message = False, f'Email failed: {exc}'
    flash(message, 'success' if ok else 'error')
    return redirect(url_for('project_detail', project_id=project.id))
