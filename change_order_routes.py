"""Phase 4: priced, customer-approved amendments to contracts."""

import base64
import re
import secrets
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request,
    send_file, url_for,
)
from flask_login import current_user, login_required
from permissions import owner_required
from sqlalchemy import select

from extensions import db, limiter
from forms import DeleteForm
from models import ChangeOrder, ChangeOrderItem, Contract, ContractDraw
from quote_routes import (
    COMPANY, LOGO_PATH, _parse_items, _pdf_text, _validated_signature_data,
)


change_order_bp = Blueprint(
    'change_orders', __name__, url_prefix='/change-orders')

PUBLIC_LINK_LIFETIME = timedelta(days=30)


def _owned_change_order_or_404(change_order_id):
    return ChangeOrder.query.filter_by(
        id=change_order_id, user_id=current_user.id).first_or_404()


def _owned_contract_or_404(contract_id):
    return Contract.query.filter_by(
        id=contract_id, user_id=current_user.id).first_or_404()


def _new_token():
    while True:
        token = secrets.token_urlsafe(16)
        if not ChangeOrder.query.filter_by(public_token=token).first():
            return token


def _public_link_is_active(change_order, now=None):
    now = now or datetime.utcnow()
    return (change_order.public_token_revoked_at is None and
            change_order.public_token_expires_at is not None and
            change_order.public_token_expires_at > now)


def _refresh_public_link(change_order):
    change_order.public_token = _new_token()
    change_order.public_token_expires_at = (
        datetime.utcnow() + PUBLIC_LINK_LIFETIME)
    change_order.public_token_revoked_at = None


def _get_public_change_order(token, lock=False):
    query = select(ChangeOrder).where(
        ChangeOrder.public_token == token,
        ChangeOrder.public_token_revoked_at.is_(None),
        ChangeOrder.public_token_expires_at > datetime.utcnow(),
    )
    if lock:
        query = query.with_for_update()
    change_order = db.session.execute(query).scalar_one_or_none()
    if change_order is None:
        from flask import abort
        abort(404)
    return change_order


def _apply_items(change_order, item_dicts):
    for existing in list(change_order.items):
        db.session.delete(existing)
    change_order.items = []
    for item in item_dicts:
        change_order.items.append(ChangeOrderItem(
            description=item['description'], quantity=item['quantity'],
            unit_price=item['unit_price']))
    change_order.recalculate_total()


def _change_order_number(contract):
    base = contract.number or f'CON-{contract.id:04d}'
    # Highest existing CO sequence on this contract (the trailing number after
    # "-CO"), so deleting a draft CO can't collide with a surviving one.
    best = 0
    for co in contract.change_orders:
        match = re.search(r'-CO(\d+)$', co.number or '')
        if match:
            best = max(best, int(match.group(1)))
    return f"{base}-CO{best + 1}"


def _totals_for_pdf(change_order):
    if change_order.applied_at is not None:
        return (change_order.contract_total_before or 0.0,
                change_order.contract_total_after or 0.0)
    before = change_order.contract.contract_total or 0.0
    return before, before + (change_order.total or 0.0)


def _money(value):
    value = value or 0.0
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def build_change_order_pdf(change_order):
    """Build a contract-style change-order PDF using escaped stored text."""
    import os
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small = ParagraphStyle('small', parent=normal, fontSize=9, leading=13)
    small_r = ParagraphStyle('small_r', parent=small, alignment=TA_RIGHT)
    title_style = ParagraphStyle(
        'co_title', parent=styles['Title'], fontSize=20,
        alignment=TA_RIGHT, spaceAfter=0)
    company_style = ParagraphStyle(
        'company', parent=normal, fontSize=13, fontName='Helvetica-Bold')
    section = ParagraphStyle(
        'section', parent=normal, fontName='Helvetica-Bold', fontSize=10)
    centered = ParagraphStyle(
        'centered', parent=normal, alignment=TA_CENTER,
        fontName='Helvetica-Bold', fontSize=10)

    left = []
    if os.path.exists(LOGO_PATH):
        try:
            logo = Image(LOGO_PATH)
            ratio = logo.imageHeight / float(logo.imageWidth)
            logo.drawWidth = 1.7 * inch
            logo.drawHeight = 1.7 * inch * ratio
            left.extend([logo, Spacer(1, 4)])
        except Exception:
            pass
    left.extend([
        Paragraph(COMPANY['name'], company_style),
        Paragraph(COMPANY['address_line1'], small),
        Paragraph(COMPANY['address_line2'], small),
        Paragraph(COMPANY['phone'], small),
        Paragraph(COMPANY['email'], small),
    ])
    date_text = (change_order.created_at.strftime('%m/%d/%y')
                 if change_order.created_at else '')
    right = [
        Paragraph('CHANGE ORDER', title_style), Spacer(1, 8),
        Paragraph(f"NUMBER {_pdf_text(change_order.number, 50)}", small_r),
        Paragraph(f"DATE {date_text}", small_r),
        Paragraph(
            f"PARENT CONTRACT {_pdf_text(change_order.contract.number, 50)}",
            small_r),
    ]
    header = Table([[left, right]], colWidths=[3.6 * inch, 3.4 * inch])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    customer = change_order.customer
    details = Table([[
        [Paragraph('<b>PREPARED FOR</b>', small),
         Paragraph(_pdf_text(customer.name, 150), small),
         Paragraph(_pdf_text(customer.address, 250), small)
         if customer.address else Spacer(1, 1)],
        [Paragraph('<b>CHANGE</b>', small),
         Paragraph(_pdf_text(change_order.title, 200), small),
         Paragraph(
             f"Contract: {_pdf_text(change_order.contract.title, 200)}", small)],
    ]], colWidths=[3.6 * inch, 3.4 * inch])
    details.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    item_rows = [[Paragraph('<b>Description</b>', small),
                  Paragraph('<b>Amount</b>', small_r)]]
    for item in change_order.items:
        item_rows.append([
            Paragraph(_pdf_text(item.description, preserve_newlines=True), small),
            Paragraph(_money(item.line_total), small_r),
        ])
    item_rows.append([
        Paragraph('<b>Change Order Total</b>', small),
        Paragraph(f"<b>{_money(change_order.total)}</b>", small_r),
    ])
    items = Table(item_rows, colWidths=[5.2 * inch, 1.8 * inch])
    items.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
        ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.black),
        ('LINEABOVE', (0, -1), (-1, -1), 0.75, colors.black),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    before, after = _totals_for_pdf(change_order)
    elems = [header, Spacer(1, 14), details, Spacer(1, 16), items,
             Spacer(1, 14), Paragraph(
                 f"Original contract {_money(before)} &nbsp;→&nbsp; "
                 f"New contract total {_money(after)}", section)]
    if change_order.reason:
        elems.extend([
            Spacer(1, 12), Paragraph('Reason for change:', section),
            Spacer(1, 4), Paragraph(
                _pdf_text(change_order.reason, preserve_newlines=True), small)])
    if change_order.notes:
        elems.extend([
            Spacer(1, 12), Paragraph('Notes:', section), Spacer(1, 4),
            Paragraph(_pdf_text(change_order.notes, preserve_newlines=True), small)])

    elems.append(Spacer(1, 22))
    client_signature = []
    if change_order.signed_at and change_order.signature_data:
        try:
            raw = base64.b64decode(
                change_order.signature_data.split(',', 1)[1], validate=True)
            signature = Image(BytesIO(raw))
            ratio = signature.imageHeight / float(signature.imageWidth)
            signature.drawWidth = 2.2 * inch
            signature.drawHeight = min(0.8 * inch, 2.2 * inch * ratio)
            client_signature.append(signature)
        except Exception:
            client_signature.append(Spacer(1, 26))
        client_signature.append(Paragraph(
            f"Client Signature — {_pdf_text(change_order.signature_name, 150)} "
            f"({change_order.signed_at.strftime('%m/%d/%y')})", small))
    else:
        client_signature.extend([
            Spacer(1, 26),
            Paragraph('Client Signature _____________________________', small)])
    contractor_signature = [
        Spacer(1, 26),
        Paragraph('Contractor _____________________________', small)]
    signatures = Table(
        [[client_signature, contractor_signature]],
        colWidths=[3.6 * inch, 3.4 * inch])
    signatures.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems.extend([signatures, Spacer(1, 18),
                  Paragraph(COMPANY['footer'], centered)])
    doc.build(elems)
    buf.seek(0)
    return buf


def send_change_order_email(change_order):
    from googleapiclient.discovery import build as google_build
    from google_routes import get_credentials

    customer = change_order.customer
    if not customer.email:
        return False, 'This customer has no email address on file.'
    if not _public_link_is_active(change_order):
        _refresh_public_link(change_order)
    credentials = get_credentials()
    if not credentials:
        return False, 'Google account is not connected.'

    link = url_for(
        'change_orders.public_view', token=change_order.public_token,
        _external=True)
    html = render_template(
        'change_orders/email.html', change_order=change_order, link=link,
        company=COMPANY)
    message = MIMEMultipart('mixed')
    message['To'] = customer.email
    message['From'] = 'me'
    message['Subject'] = (
        f"Change Order {change_order.number} from {COMPANY['name']}: "
        f"{change_order.title}")
    alternative = MIMEMultipart('alternative')
    alternative.attach(MIMEText(html, 'html'))
    message.attach(alternative)
    attachment = MIMEApplication(
        build_change_order_pdf(change_order).read(), _subtype='pdf')
    safe_name = (change_order.number or 'change-order').replace('/', '-')
    attachment.add_header(
        'Content-Disposition', 'attachment', filename=f'{safe_name}.pdf')
    message.attach(attachment)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service = google_build('gmail', 'v1', credentials=credentials)
    service.users().messages().send(
        userId='me', body={'raw': raw}).execute()
    return True, f'Emailed to {customer.email}.'


@change_order_bp.route('/contracts/<int:contract_id>/new', methods=['GET', 'POST'])
@login_required
def new(contract_id):
    contract = _owned_contract_or_404(contract_id)
    return _save_change_order(None, contract)


@change_order_bp.route('/<int:change_order_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(change_order_id):
    change_order = _owned_change_order_or_404(change_order_id)
    return _save_change_order(change_order, change_order.contract)


def _save_change_order(change_order, contract):
    if request.method == 'POST':
        if change_order is not None and change_order.applied_at is not None:
            flash('An approved change order cannot be edited.', 'error')
            return redirect(url_for(
                'change_orders.edit', change_order_id=change_order.id))
        title = (request.form.get('title') or '').strip()
        if not title:
            flash('Please give the change order a title.', 'error')
        else:
            if change_order is None:
                change_order = ChangeOrder(
                    user_id=current_user.id, contract_id=contract.id,
                    customer_id=contract.customer_id,
                    number=_change_order_number(contract), public_token=_new_token())
                db.session.add(change_order)
            change_order.title = title
            change_order.reason = (request.form.get('reason') or '').strip()
            change_order.notes = (request.form.get('notes') or '').strip()
            change_order.add_as_draw = request.form.get('add_as_draw') == 'on'
            _apply_items(change_order, _parse_items(request.form))
            db.session.commit()
            flash('Change order saved.', 'success')
            return redirect(url_for(
                'change_orders.edit', change_order_id=change_order.id))
    return render_template(
        'change_orders/form.html', change_order=change_order, contract=contract,
        public_link_active=(
            _public_link_is_active(change_order) if change_order else False))


@change_order_bp.route('/<int:change_order_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete(change_order_id):
    change_order = _owned_change_order_or_404(change_order_id)
    contract_id = change_order.contract_id
    if change_order.applied_at is not None:
        flash('An approved change order cannot be deleted.', 'error')
    else:
        db.session.delete(change_order)
        db.session.commit()
        flash('Change order deleted.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract_id))


@change_order_bp.route('/<int:change_order_id>/send', methods=['POST'])
@login_required
def send(change_order_id):
    change_order = _owned_change_order_or_404(change_order_id)
    if change_order.status == 'draft':
        change_order.status = 'sent'
    if change_order.sent_at is None:
        change_order.sent_at = datetime.utcnow()
    if not _public_link_is_active(change_order):
        _refresh_public_link(change_order)
    db.session.commit()
    flash('Change order marked as sent.', 'success')
    return redirect(url_for(
        'change_orders.edit', change_order_id=change_order.id))


@change_order_bp.route('/<int:change_order_id>/email', methods=['POST'])
@login_required
def email(change_order_id):
    change_order = _owned_change_order_or_404(change_order_id)
    try:
        ok, message = send_change_order_email(change_order)
        if ok:
            if change_order.status == 'draft':
                change_order.status = 'sent'
            if change_order.sent_at is None:
                change_order.sent_at = datetime.utcnow()
            db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'Failed to email change order %s', change_order.id)
        ok, message = False, 'Email failed. Please try again or use the share link.'
    flash(message, 'success' if ok else 'error')
    return redirect(url_for(
        'change_orders.edit', change_order_id=change_order.id))


@change_order_bp.route('/<int:change_order_id>/pdf')
@login_required
def pdf(change_order_id):
    change_order = _owned_change_order_or_404(change_order_id)
    return send_file(
        build_change_order_pdf(change_order), mimetype='application/pdf',
        as_attachment=False,
        download_name=f'{change_order.number or change_order.id}.pdf')


@change_order_bp.route('/co/<token>')
@limiter.limit('60 per minute')
def public_view(token):
    change_order = _get_public_change_order(token)
    return render_template(
        'change_orders/public.html', change_order=change_order, company=COMPANY)


@change_order_bp.route('/co/<token>/approve', methods=['POST'])
@limiter.limit('5 per minute')
def public_approve(token):
    change_order = _get_public_change_order(token, lock=True)
    if change_order.applied_at is not None:
        flash('This change order has already been approved.', 'success')
        return redirect(url_for(
            'change_orders.public_view', token=change_order.public_token))

    name = (request.form.get('signature_name') or '').strip()
    signature = _validated_signature_data(
        (request.form.get('signature_data') or '').strip())
    if not name or len(name) > 150 or signature is None:
        flash('Please type your name and sign before approving.', 'error')
        return redirect(url_for(
            'change_orders.public_view', token=change_order.public_token))

    contract = db.session.execute(
        select(Contract).where(Contract.id == change_order.contract_id)
        .with_for_update()).scalar_one()
    before = contract.contract_total or 0.0
    projected = before + (change_order.total or 0.0)
    # A deduction/credit must not pull the contract below what's already paid.
    if projected < (contract.paid_to_date or 0.0):
        flash('This change order cannot be approved because it would reduce the '
              'contract below the amount already paid. Please contact the '
              'contractor.', 'error')
        return redirect(url_for(
            'change_orders.public_view', token=change_order.public_token))
    contract.contract_total = projected
    change_order.contract_total_before = before
    change_order.contract_total_after = contract.contract_total
    change_order.signature_name = name
    change_order.signature_data = signature
    change_order.signed_at = datetime.utcnow()
    change_order.applied_at = datetime.utcnow()
    change_order.status = 'approved'
    if change_order.add_as_draw and (change_order.total or 0.0) > 0:
        contract.draws.append(ContractDraw(
            sequence=len(contract.draws),
            description=(
                f"Change Order {change_order.number}: {change_order.title}"),
            amount=change_order.total, status='pending'))
    if contract.status == 'draft':
        contract.status = 'active'
    db.session.commit()
    flash('Thank you — the change order has been approved.', 'success')
    return redirect(url_for(
        'change_orders.public_view', token=change_order.public_token))


@change_order_bp.route('/co/<token>/pdf')
@limiter.limit('10 per minute')
def public_pdf(token):
    change_order = _get_public_change_order(token)
    return send_file(
        build_change_order_pdf(change_order), mimetype='application/pdf',
        as_attachment=False,
        download_name=f'{change_order.number or change_order.id}.pdf')
