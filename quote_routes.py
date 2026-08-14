"""
Customer-facing quotes (Phase 1).

Self-contained Blueprint. Adds:
  - Customer directory (create / list / delete)
  - Quote builder with line items and an "Suggest with AI" helper
  - Server-side PDF generation (reportlab)
  - A public, tokenized approval page (/q/<token>) where the customer
    reviews the quote and e-signs to approve — no login required.

Nothing in the existing app is modified; this only reads/writes the new
Customer / Quote / QuoteItem tables.
"""

import os
import json
import secrets
import base64
import binascii
import struct
import zlib
from datetime import datetime, timedelta
from io import BytesIO
from xml.sax.saxutils import escape

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request,
    jsonify, send_file, abort, current_app,
)
from flask_login import login_required, current_user
from permissions import owner_required

from extensions import db, limiter
from models import (
    Customer, Quote, QuoteItem, Project, Invoice, Contract, ChangeOrder,
    GcDocument, Location, find_or_create_location,
)
from forms import CustomerForm, DeleteForm

quote_bp = Blueprint('quotes', __name__, url_prefix='/quotes')

QUOTE_STATUSES = ['draft', 'sent', 'approved', 'declined', 'converted']
MAX_SIGNATURE_BYTES = 512 * 1024
MAX_SIGNATURE_DIMENSION = 2048
PUBLIC_LINK_LIFETIME = timedelta(days=30)

# Company details for the PDF letterhead (from the Optimal SES contract template).
COMPANY = {
    'name': 'Optimal SES',
    'address_line1': '1204 W County Line Rd',
    'address_line2': 'Beecher, Illinois 60401',
    'phone': '708-769-9181',
    'email': 'Office@OptimalSES.com',
    'doc_title': 'CONTRACT',
    'footer': 'THANK YOU FOR YOUR BUSINESS!',
}
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'static', 'images', 'Optimal.png')


# ── helpers ──────────────────────────────────────────────────────────────

def _new_token():
    """A URL-safe token that is guaranteed unique among existing quotes."""
    while True:
        token = secrets.token_urlsafe(16)
        if not Quote.query.filter_by(public_token=token).first():
            return token


def _public_link_is_active(quote, now=None):
    now = now or datetime.utcnow()
    return (quote.public_token_revoked_at is None and
            quote.public_token_expires_at is not None and
            quote.public_token_expires_at > now)


def _refresh_public_link(quote):
    quote.public_token = _new_token()
    quote.public_token_expires_at = datetime.utcnow() + PUBLIC_LINK_LIFETIME
    quote.public_token_revoked_at = None


def _get_public_quote(token):
    now = datetime.utcnow()
    return (Quote.query
            .filter(Quote.public_token == token,
                    Quote.public_token_revoked_at.is_(None),
                    Quote.public_token_expires_at > now)
            .first_or_404())


def _owned_quote_or_404(quote_id):
    return Quote.query.filter_by(
        id=quote_id, user_id=current_user.id).first_or_404()


def _pdf_text(value, max_length=5000, preserve_newlines=False):
    """Escape untrusted text before passing it to ReportLab Paragraph.

    ReportLab Paragraph accepts an XML-like markup language. Passing stored
    customer or quote text to it directly could allow tags such as ``<img>``
    to trigger external resource loading while a PDF is generated.
    """
    text = str(value or '')[:max_length]
    escaped = escape(text)
    if preserve_newlines:
        return escaped.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br/>')
    return escaped


def _validated_signature_data(value):
    """Return a normalized PNG data URL, or None for an unsafe image."""
    prefix = 'data:image/png;base64,'
    if not value.startswith(prefix):
        return None

    encoded = value[len(prefix):]
    # Reject oversized input before allocating memory for base64 decoding.
    if not encoded or len(encoded) > ((MAX_SIGNATURE_BYTES + 2) // 3) * 4:
        return None
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if len(image) > MAX_SIGNATURE_BYTES or len(image) < 33:
        return None
    if image[:8] != b'\x89PNG\r\n\x1a\n':
        return None

    # Validate the PNG chunk structure and CRCs, and require a safe IHDR.
    offset = 8
    saw_ihdr = False
    saw_idat = False
    saw_iend = False
    while offset + 12 <= len(image):
        length = struct.unpack('>I', image[offset:offset + 4])[0]
        chunk_end = offset + 12 + length
        if chunk_end > len(image):
            return None
        chunk_type = image[offset + 4:offset + 8]
        chunk_data = image[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack('>I', image[offset + 8 + length:chunk_end])[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xffffffff != expected_crc:
            return None
        if not saw_ihdr:
            if chunk_type != b'IHDR' or length != 13:
                return None
            width, height = struct.unpack('>II', chunk_data[:8])
            if not (1 <= width <= MAX_SIGNATURE_DIMENSION and
                    1 <= height <= MAX_SIGNATURE_DIMENSION):
                return None
            saw_ihdr = True
        elif chunk_type == b'IHDR':
            return None
        if chunk_type == b'IDAT':
            saw_idat = True
        if chunk_type == b'IEND':
            if length != 0 or chunk_end != len(image):
                return None
            saw_iend = True
            break
        offset = chunk_end

    if not (saw_ihdr and saw_idat and saw_iend):
        return None
    return prefix + base64.b64encode(image).decode('ascii')


def _parse_items(form):
    """Read the parallel item_* arrays from the builder form into dicts."""
    descriptions = form.getlist('item_description')
    quantities = form.getlist('item_quantity')
    prices = form.getlist('item_price')
    items = []
    for i, desc in enumerate(descriptions):
        desc = (desc or '').strip()
        if not desc:
            continue

        def _num(seq, idx, default):
            try:
                return float(seq[idx])
            except (IndexError, ValueError, TypeError):
                return default

        items.append({
            'description': desc,
            'quantity': _num(quantities, i, 1.0),
            'unit_price': _num(prices, i, 0.0),
        })
    return items


def _apply_items(quote, item_dicts):
    """Replace a quote's line items and recompute its total."""
    for existing in list(quote.items):
        db.session.delete(existing)
    quote.items = []
    for d in item_dicts:
        quote.items.append(QuoteItem(
            description=d['description'],
            quantity=d['quantity'],
            unit_price=d['unit_price'],
        ))
    quote.recalculate_total()


def build_quote_pdf(quote):
    """Render a quote as a contract-style PDF matching the Optimal SES template."""
    import base64
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
    center = ParagraphStyle('center', parent=normal, alignment=TA_CENTER,
                            fontName='Helvetica-Bold', fontSize=12)
    ink = colors.HexColor('#111111')

    elems = []

    # ── Header: logo + company (left) | doc title + invoice/date (right) ──
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

    date_str = quote.created_at.strftime('%m/%d/%y') if quote.created_at else ''
    right_cell = [
        Paragraph(COMPANY['doc_title'], doc_title),
        Spacer(1, 8),
        Paragraph(f"INVOICE # {quote.id}", small_r),
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

    # ── Bill-to (left) | FOR / P.O. (right) ──
    c = quote.customer
    bill = [Paragraph('<b>BILL TO</b>', small),
            Paragraph(_pdf_text(c.name, 150), small)]
    if c.address:
        bill.append(Paragraph(_pdf_text(c.address, 250), small))
    if c.phone:
        bill.append(Paragraph(_pdf_text(c.phone, 30), small))
    if c.email:
        bill.append(Paragraph(_pdf_text(c.email, 150), small))

    forpo = [
        Paragraph(f"FOR &nbsp; {_pdf_text(quote.title, 200)}", small),
        Spacer(1, 4),
        Paragraph(f"P.O. # {_pdf_text(quote.po_number or 'n/a', 50)}", small),
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
    for item in quote.items:
        desc = _pdf_text(item.description, preserve_newlines=True)
        data.append([Paragraph(desc, small),
                     Paragraph(f"${item.line_total:,.2f}", small_r)])
    data.append([Paragraph('<b>Total</b>', small),
                 Paragraph(f"<b>${quote.total:,.2f}</b>", small_r)])

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

    # ── Payment & Project Schedule (auto deposit sentence + notes) ──
    schedule_bits = []
    if quote.deposit:
        balance = (quote.total or 0) - quote.deposit
        schedule_bits.append(
            f"The Owner shall pay an initial deposit of ${quote.deposit:,.2f} upon "
            f"execution of this Agreement. The remaining balance of ${balance:,.2f} "
            f"shall be due and payable upon substantial completion of the project.")
    if quote.notes:
        schedule_bits.append(_pdf_text(quote.notes, preserve_newlines=True))

    if schedule_bits:
        elems.append(Paragraph('Payment &amp; Project Schedule:', section))
        elems.append(Spacer(1, 4))
        elems.append(Paragraph('<br/><br/>'.join(schedule_bits), small))
        elems.append(Spacer(1, 18))

    # ── Signatures ──
    sig_left = []
    if quote.signed_at and quote.signature_data:
        try:
            b64 = quote.signature_data.split(',', 1)[1]
            sig_img = Image(BytesIO(base64.b64decode(b64)))
            sratio = sig_img.imageHeight / float(sig_img.imageWidth)
            sig_img.drawWidth = 2.2 * inch
            sig_img.drawHeight = min(0.8 * inch, 2.2 * inch * sratio)
            sig_img.hAlign = 'LEFT'
            sig_left.append(sig_img)
        except Exception:
            sig_left.append(Spacer(1, 26))
        sig_left.append(Paragraph(
            f"Client Signature — {_pdf_text(quote.signature_name or c.name, 150)} "
            f"({quote.signed_at.strftime('%m/%d/%y')})", small))
    else:
        sig_left.append(Spacer(1, 26))
        sig_left.append(Paragraph(
            'Client Signature _____________________________', small))

    sig_right = [Spacer(1, 26),
                 Paragraph('Representative _____________________________', small)]
    sigtable = Table([[sig_left, sig_right]], colWidths=[3.6 * inch, 3.4 * inch])
    sigtable.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elems.append(sigtable)
    elems.append(Spacer(1, 20))

    elems.append(Paragraph(COMPANY['footer'], center))

    doc.build(elems)
    buf.seek(0)
    return buf


def send_quote_email(quote):
    """Email the quote (approval link + PDF attachment) to the customer via
    the app's existing Gmail integration. Returns (ok, message)."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials

    customer = quote.customer
    if not customer.email:
        return False, 'This customer has no email address on file. Add one on the Customers page.'

    if not _public_link_is_active(quote):
        _refresh_public_link(quote)

    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    link = url_for('quotes.public_view', token=quote.public_token, _external=True)
    html = render_template('quotes/email.html', quote=quote, link=link, company=COMPANY)

    msg = MIMEMultipart('mixed')
    msg['To'] = customer.email
    msg['From'] = 'me'
    msg['Subject'] = f"{COMPANY['doc_title'].title()} from {COMPANY['name']}: {quote.title}"

    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)

    pdf_bytes = build_quote_pdf(quote).read()
    attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
    safe_name = (quote.title or 'quote').replace('/', '-')
    attachment.add_header('Content-Disposition', 'attachment',
                          filename=f'{safe_name}.pdf')
    msg.attach(attachment)

    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
    return True, f'Emailed to {customer.email}.'


# ── customer directory ───────────────────────────────────────────────────

def _norm(s):
    return ' '.join((s or '').strip().lower().split())


def _digits(s):
    return ''.join(ch for ch in (s or '') if ch.isdigit())


def _find_duplicate_customer(name, email, phone, exclude_id=None):
    """Return (customer, reason) for an existing match. Email/phone are strong
    identity signals (same person); a name-only match is a soft heads-up."""
    custs = [c for c in Customer.query.filter_by(user_id=current_user.id).all()
             if c.id != exclude_id]
    e, p, n = _norm(email), _digits(phone), _norm(name)
    for c in custs:
        if e and _norm(c.email) == e:
            return c, 'email'
        if p and len(p) >= 7 and _digits(c.phone) == p:
            return c, 'phone'
    for c in custs:
        if n and _norm(c.name) == n:
            return c, 'name'
    return None, None


@quote_bp.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    form = CustomerForm()
    if form.validate_on_submit():
        dup, reason = _find_duplicate_customer(
            form.name.data, form.email.data, form.phone.data)
        if dup and reason in ('email', 'phone'):
            flash(f'A customer with that {reason} already exists: {dup.name}. '
                  f'Open them instead of creating a duplicate.', 'error')
        else:
            customer = Customer(user_id=current_user.id)
            form.populate_obj(customer)
            db.session.add(customer)
            db.session.commit()
            if dup and reason == 'name':
                flash(f'Customer added. Note: "{dup.name}" already existed — '
                      f'merge them below if this is the same person.', 'success')
            else:
                flash('Customer added.', 'success')
            return redirect(url_for('quotes.customers'))

    all_customers = (Customer.query.filter_by(user_id=current_user.id)
                     .order_by(Customer.name.asc()).all())
    return render_template('quotes/customers.html', form=form,
                           customers=all_customers, delete_form=DeleteForm())


@quote_bp.route('/customers/<int:customer_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete_customer(customer_id):
    customer = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted.', 'success')
    return redirect(url_for('quotes.customers'))


@quote_bp.route('/customers/<int:customer_id>/merge', methods=['POST'])
@login_required
def merge_customer(customer_id):
    """Merge a duplicate customer into a survivor: move every related record
    (proposals, invoices, contracts, change orders, documents, locations, jobs)
    to the survivor, then delete the empty duplicate."""
    dup = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()
    survivor = Customer.query.filter_by(
        id=request.form.get('survivor_id', type=int),
        user_id=current_user.id).first()
    if not survivor or survivor.id == dup.id:
        flash('Pick a different customer to merge into.', 'error')
        return redirect(url_for('quotes.customers'))

    for model in (Quote, Invoice, Contract, ChangeOrder, GcDocument, Location, Project):
        (model.query.filter_by(customer_id=dup.id)
         .update({'customer_id': survivor.id}, synchronize_session=False))
    db.session.delete(dup)
    db.session.commit()
    flash(f'Merged "{dup.name}" into "{survivor.name}" — all their jobs and '
          f'records moved over.', 'success')
    return redirect(url_for('quotes.customers'))


def _job_money(project):
    contract_total = sum(c.contract_total or 0 for c in project.contracts)
    paid = sum(i.total or 0 for i in project.invoices if i.status == 'paid')
    return contract_total, paid


@quote_bp.route('/customers/<int:customer_id>')
@login_required
def customer_detail(customer_id):
    customer = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()

    location_groups = []
    for loc in sorted(customer.locations, key=lambda x: x.id):
        jobs = []
        for p in sorted(loc.projects, key=lambda x: x.id, reverse=True):
            ct, paid = _job_money(p)
            jobs.append({'project': p, 'contract': ct, 'paid': paid})
        location_groups.append({'location': loc, 'jobs': jobs})

    unlocated = []
    for p in sorted(customer.projects, key=lambda x: x.id, reverse=True):
        if p.location_id is None:
            ct, paid = _job_money(p)
            unlocated.append({'project': p, 'contract': ct, 'paid': paid})

    total_contract = sum(c.contract_total or 0 for c in customer.contracts)
    total_paid = sum(i.total or 0 for i in customer.invoices if i.status == 'paid')

    return render_template(
        'quotes/customer_detail.html', customer=customer,
        location_groups=location_groups, unlocated=unlocated,
        proposals=sorted(customer.quotes, key=lambda q: q.id, reverse=True),
        invoices=sorted(customer.invoices, key=lambda i: i.id, reverse=True),
        total_contract=total_contract, total_paid=total_paid)


@quote_bp.route('/customers/<int:customer_id>/locations/add', methods=['POST'])
@login_required
def add_location(customer_id):
    customer = Customer.query.filter_by(
        id=customer_id, user_id=current_user.id).first_or_404()
    address = (request.form.get('address') or '').strip()
    if not address:
        flash('Enter the property address.', 'error')
        return redirect(url_for('quotes.customer_detail', customer_id=customer.id))
    loc = find_or_create_location(current_user.id, customer.id, address)
    label = (request.form.get('label') or '').strip()
    if loc and label:
        loc.label = label
    db.session.commit()
    flash('Property added.', 'success')
    return redirect(url_for('quotes.customer_detail', customer_id=customer.id))


# ── quotes list ──────────────────────────────────────────────────────────

@quote_bp.route('/')
@login_required
def index():
    quotes = (Quote.query.filter_by(user_id=current_user.id)
              .order_by(Quote.created_at.desc()).all())
    return render_template('quotes/list.html', quotes=quotes,
                           delete_form=DeleteForm())


# ── quote builder (create / edit) ────────────────────────────────────────

@quote_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    return _save_quote(None)


@quote_bp.route('/<int:quote_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(quote_id):
    quote = _owned_quote_or_404(quote_id)
    return _save_quote(quote)


def _save_quote(quote):
    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        title = (request.form.get('title') or '').strip()
        notes = (request.form.get('notes') or '').strip()
        project_id = request.form.get('project_id', type=int)
        deposit = request.form.get('deposit', type=float)
        po_number = (request.form.get('po_number') or '').strip()

        customer = (Customer.query.filter_by(
            id=customer_id, user_id=current_user.id).first()
            if customer_id else None)
        if not customer:
            flash('Please choose a customer.', 'error')
        elif not title:
            flash('Please give the proposal a title.', 'error')
        else:
            if quote is None:
                quote = Quote(user_id=current_user.id)
                _refresh_public_link(quote)
                db.session.add(quote)
            quote.customer_id = customer_id
            quote.title = title
            quote.notes = notes
            quote.project_id = project_id if project_id else None
            quote.deposit = deposit if deposit else None
            quote.po_number = po_number or None
            _apply_items(quote, _parse_items(request.form))
            db.session.commit()
            flash('Proposal saved.', 'success')
            return redirect(url_for('quotes.edit', quote_id=quote.id))

    customers = (Customer.query.filter_by(user_id=current_user.id)
                 .order_by(Customer.name.asc()).all())
    projects = Project.query.order_by(Project.name.asc()).all()
    return render_template(
        'quotes/form.html', quote=quote, customers=customers, projects=projects,
        public_link_active=(_public_link_is_active(quote) if quote else False))


@quote_bp.route('/<int:quote_id>/delete', methods=['POST'])
@login_required
@owner_required
def delete(quote_id):
    quote = _owned_quote_or_404(quote_id)
    db.session.delete(quote)
    db.session.commit()
    flash('Proposal deleted.', 'success')
    return redirect(url_for('quotes.index'))


@quote_bp.route('/<int:quote_id>/send', methods=['POST'])
@login_required
def send(quote_id):
    quote = _owned_quote_or_404(quote_id)
    if not _public_link_is_active(quote):
        _refresh_public_link(quote)
    if quote.status == 'draft':
        quote.status = 'sent'
    if not quote.sent_at:
        quote.sent_at = datetime.utcnow()
    db.session.commit()
    link = url_for('quotes.public_view', token=quote.public_token, _external=True)
    flash(f'Proposal marked as sent. Share this approval link with the customer: {link}',
          'success')
    return redirect(url_for('quotes.edit', quote_id=quote.id))


@quote_bp.route('/<int:quote_id>/public-link/revoke', methods=['POST'])
@login_required
def revoke_public_link(quote_id):
    quote = _owned_quote_or_404(quote_id)
    quote.public_token_revoked_at = datetime.utcnow()
    db.session.commit()
    flash('Public approval link revoked.', 'success')
    return redirect(url_for('quotes.edit', quote_id=quote.id))


@quote_bp.route('/<int:quote_id>/public-link/regenerate', methods=['POST'])
@login_required
def regenerate_public_link(quote_id):
    quote = _owned_quote_or_404(quote_id)
    _refresh_public_link(quote)
    db.session.commit()
    flash('A new public approval link was created and will expire in 30 days.',
          'success')
    return redirect(url_for('quotes.edit', quote_id=quote.id))


@quote_bp.route('/<int:quote_id>/email', methods=['POST'])
@login_required
def email(quote_id):
    quote = _owned_quote_or_404(quote_id)
    try:
        ok, message = send_quote_email(quote)
    except Exception:  # noqa: BLE001 — provider failures are logged below
        current_app.logger.exception('Failed to email quote %s', quote.id)
        ok, message = False, 'Email failed. Please try again or use the share link.'

    if ok:
        if quote.status == 'draft':
            quote.status = 'sent'
        if not quote.sent_at:
            quote.sent_at = datetime.utcnow()
        db.session.commit()
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('quotes.edit', quote_id=quote.id))


@quote_bp.route('/<int:quote_id>/pdf')
@login_required
def pdf(quote_id):
    quote = _owned_quote_or_404(quote_id)
    buf = build_quote_pdf(quote)
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f'quote-{quote.id}.pdf')


# ── AI suggestion (plain language → professional line item + price) ───────

@quote_bp.route('/suggest', methods=['POST'])
@login_required
def suggest():
    payload = request.get_json(silent=True) or {}
    raw = (payload.get('text') or '').strip()
    if not raw:
        return jsonify({'error': 'Describe the work first.'}), 400
    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'error': 'AI is not configured (OPENAI_API_KEY missing).'}), 503

    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        completion = client.chat.completions.create(
            model='gpt-4o',
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content':
                    'You write line items for a service business quote. '
                    'Given a plain-language description of work, return JSON with '
                    '"description" (one professional, customer-ready sentence) and '
                    '"price" (a numeric USD estimate as a number, no symbols). '
                    'If you cannot estimate a price, use 0.'},
                {'role': 'user', 'content': raw},
            ],
        )
        data = json.loads(completion.choices[0].message.content)
        return jsonify({
            'description': str(data.get('description', raw)).strip(),
            'price': float(data.get('price', 0) or 0),
        })
    except Exception:  # noqa: BLE001 — provider failures are logged below
        current_app.logger.exception('AI quote suggestion failed')
        return jsonify({'error': 'AI request failed. Please try again.'}), 502


# ── public approval page (no login) ──────────────────────────────────────

@quote_bp.route('/q/<token>')
@limiter.limit("60 per minute")
def public_view(token):
    quote = _get_public_quote(token)
    return render_template('quotes/public.html', quote=quote)


@quote_bp.route('/q/<token>/approve', methods=['POST'])
@limiter.limit("5 per minute")
def public_approve(token):
    quote = _get_public_quote(token)
    if quote.status in ('approved', 'converted'):
        flash('This proposal has already been approved.', 'success')
        return redirect(url_for('quotes.public_view', token=token))

    name = (request.form.get('signature_name') or '').strip()
    signature = _validated_signature_data(
        (request.form.get('signature_data') or '').strip())
    if not name or len(name) > 150 or not signature:
        flash('Please type your name and sign before approving.', 'error')
        return redirect(url_for('quotes.public_view', token=token))

    quote.signature_name = name
    quote.signature_data = signature
    quote.signed_at = datetime.utcnow()
    quote.status = 'approved'
    db.session.commit()
    flash('Thank you — your approval has been recorded.', 'success')
    return redirect(url_for('quotes.public_view', token=token))


@quote_bp.route('/q/<token>/pdf')
@limiter.limit("10 per minute")
def public_pdf(token):
    quote = _get_public_quote(token)
    buf = build_quote_pdf(quote)
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f'quote-{quote.id}.pdf')
