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
import base64
import secrets
from datetime import datetime, timedelta
from io import BytesIO

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, send_file,
    abort, current_app,
)
from flask_login import login_required, current_user
from permissions import owner_required
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from extensions import db, limiter
from models import (
    Contract, ContractDraw, ContractProposal, Customer, Quote, Project,
    Invoice, InvoiceItem, find_or_create_location,
)
from forms import DeleteForm
from quote_routes import (
    COMPANY, LOGO_PATH, _pdf_text, safe_filename, _validated_signature_data,
)
from signature_audit import record_signature_event, CONSENT_TEXT
from invoice_routes import _new_invoice_token, _next_number

contract_bp = Blueprint('contracts', __name__, url_prefix='/contracts')

PAGE_SIZE = 100
# Status groups for the list filter tabs (Active / All / Archived).
# 'sent' (awaiting signature) and 'accepted' (signed, not yet started) are
# in-progress work, so they belong in Active — not hidden until 'all'.
CONTRACT_ACTIVE_STATUSES = ('draft', 'sent', 'accepted', 'active')
CONTRACT_ARCHIVED_STATUSES = ('completed',)

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


PUBLIC_LINK_LIFETIME = timedelta(days=30)


def _new_contract_token():
    """A URL-safe token unique among existing contracts."""
    while True:
        token = secrets.token_urlsafe(16)
        if not Contract.query.filter_by(public_token=token).first():
            return token


def _contract_link_is_active(contract, now=None):
    now = now or datetime.utcnow()
    return bool(contract.public_token
                and contract.public_token_revoked_at is None
                and contract.public_token_expires_at is not None
                and contract.public_token_expires_at > now)


def _refresh_contract_link(contract):
    contract.public_token = _new_contract_token()
    contract.public_token_expires_at = datetime.utcnow() + PUBLIC_LINK_LIFETIME
    contract.public_token_revoked_at = None


def send_contract_email(contract):
    """Email the contract (acceptance link + PDF) to the customer via the app's
    Gmail integration. Returns (ok, message)."""
    import base64 as _b64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials

    customer = contract.customer
    if not customer or not customer.email:
        return False, ('This customer has no email address on file. '
                       'Add one on the Customers page.')
    if not _contract_link_is_active(contract):
        _refresh_contract_link(contract)
    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    link = url_for('contracts.public_view', token=contract.public_token,
                   _external=True)
    html = render_template('contracts/email.html', contract=contract,
                           link=link, company=COMPANY)

    msg = MIMEMultipart('mixed')
    msg['To'] = customer.email
    msg['From'] = 'me'
    msg['Subject'] = f"Contract from {COMPANY['name']}: {contract.title}"
    alt = MIMEMultipart('alternative')
    alt.attach(MIMEText(html, 'html'))
    msg.attach(alt)

    pdf_bytes = build_contract_pdf(contract).read()
    attachment = MIMEApplication(pdf_bytes, _subtype='pdf')
    safe_name = safe_filename(customer.name,
                              contract.number or ('Contract ' + str(contract.id)),
                              'Contract')
    attachment.add_header('Content-Disposition', 'attachment',
                          filename=f'{safe_name}.pdf')
    msg.attach(attachment)

    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = _b64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
    return True, f'Emailed to {customer.email}.'


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


# ── Terms profile + feature toggles (F0) ──

# The three allowed profiles. An unknown value falls back to 'simple' so the
# contract can never land in a state that turns features on unexpectedly.
VALID_TERMS_PROFILES = {'simple', 'progress', 'developer_gc'}

# The six per-contract feature toggles, in the order they appear on the form.
CONTRACT_TOGGLE_FIELDS = (
    'retainage_enabled', 'deadlines_enabled', 'sworn_statements_enabled',
    'lot_releases_enabled', 'hold_points_enabled', 'evidence_required',
)


def _checkbox(form, name):
    """An HTML checkbox submits its value only when ticked; absent means off."""
    return form.get(name) is not None


def _apply_terms_profile(contract, form):
    """Save the chosen profile and the six toggles from the submitted form.

    The <select> pre-fills the checkboxes in the browser (step 4), but we always
    trust whatever checkboxes actually arrive, so the user can override any one
    of them. Each toggle defaults to off when its checkbox is absent, which
    keeps a Simple contract completely off by default.
    """
    profile = (form.get('terms_profile') or 'simple').strip()
    contract.terms_profile = profile if profile in VALID_TERMS_PROFILES else 'simple'
    for field in CONTRACT_TOGGLE_FIELDS:
        setattr(contract, field, _checkbox(form, field))


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


def _scope_from_quote(quote):
    """Build a frozen Scope-of-Work snapshot from a proposal's line items.

    Each item's description is kept verbatim (line breaks / bullets intact) and
    items are separated by a blank line. Returns '' when the quote has no items.
    """
    parts = [(item.description or '').strip() for item in quote.items]
    return '\n\n'.join(p for p in parts if p)


def _scope_from_quotes(quotes):
    """Combined Scope-of-Work snapshot across several merged proposals.

    Each proposal's items are grouped under a heading naming that proposal, so
    the contract's scope shows which work came from which quote.
    """
    blocks = []
    for q in quotes:
        header = (q.title or f'Proposal #{q.id}').strip()
        body = _scope_from_quote(q)
        blocks.append(f'=== {header} ===\n\n{body}' if body else f'=== {header} ===')
    return '\n\n'.join(blocks)


def _ensure_project_for_quote(quote):
    """Return a Job id for a signed proposal, creating one if needed.

    Mirrors the job-creation used when converting a single proposal, so a
    combined contract still ends up tied to one Job. (from_quote keeps its own
    copy untouched.)
    """
    if quote.project_id:
        return quote.project_id
    customer = quote.customer
    job_address = None
    job_location_id = None
    if quote.location_id and quote.location:
        job_address = quote.location.address
        job_location_id = quote.location_id
    elif customer:
        job_address = customer.address
    project = Project(
        name=quote.title or (f"Job for {customer.name}" if customer else 'New job'),
        address=job_address,
        status='Active',
        customer_id=quote.customer_id,
    )
    db.session.add(project)
    db.session.flush()
    if job_location_id:
        project.location_id = job_location_id
    else:
        loc = find_or_create_location(current_user.id, quote.customer_id, job_address)
        if loc:
            project.location_id = loc.id
    return project.id


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
                                  leading=16, spaceAfter=3,
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

    # Property address (from the linked job), shown above the scope. Hidden when
    # there's no linked job or the job has no address.
    prop_address = contract.project.address if contract.project else None
    if prop_address:
        elems.append(Paragraph('<b>PROPERTY ADDRESS</b>', small))
        elems.append(Paragraph(_pdf_text(prop_address, 250), small))
        elems.append(Spacer(1, 12))

    # Scope of Work — frozen snapshot carried from the source proposal. Rendered
    # as a numbered table (one row per item); blank lines in the stored text
    # separate items, matching how the snapshot joins the proposal's line items.
    # Line breaks / bullets inside an item are preserved. Hidden when empty.
    scope_items = [blk.strip() for blk
                   in re.split(r'\n\s*\n', contract.scope_of_work or '')
                   if blk.strip()]
    if scope_items:
        elems.append(Paragraph('Scope of Work', section))
        elems.append(Spacer(1, 6))
        scope_data = [[Paragraph('<b>#</b>', small),
                       Paragraph('<b>Description</b>', small)]]
        for i, item in enumerate(scope_items, 1):
            scope_data.append([
                Paragraph(str(i), small),
                Paragraph(_pdf_text(item, preserve_newlines=True), small)])
        scope_table = Table(scope_data, colWidths=[0.4 * inch, 6.6 * inch])
        scope_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8e8e8')),
            ('LINEBELOW', (0, 0), (-1, 0), 0.5, ink),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#dddddd')),
        ]))
        elems.append(scope_table)
        elems.append(Spacer(1, 12))

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
        elems.append(Paragraph('Notes &amp; Exclusions:', section))
        elems.append(Spacer(1, 4))
        elems.append(Paragraph(_pdf_text(contract.notes, preserve_newlines=True), small))
        elems.append(Spacer(1, 12))

    elems.append(Spacer(1, 18))
    owner_cell = []
    if contract.signed_at and contract.signature_data:
        # Customer e-signed: render the drawn signature image + name + date.
        try:
            b64 = contract.signature_data.split(',', 1)[1]
            sig_img = Image(BytesIO(base64.b64decode(b64)))
            sratio = sig_img.imageHeight / float(sig_img.imageWidth)
            sig_img.drawWidth = 2.2 * inch
            sig_img.drawHeight = min(0.8 * inch, 2.2 * inch * sratio)
            sig_img.hAlign = 'LEFT'
            owner_cell.append(sig_img)
        except Exception:  # noqa: BLE001 — a bad image must not break the PDF
            owner_cell.append(Spacer(1, 26))
        owner_cell.append(Paragraph(
            f"Accepted by {_pdf_text(contract.signature_name or '', 150)} "
            f"({contract.signed_at.strftime('%m/%d/%y')})", small))
    else:
        owner_cell.append(Paragraph('Owner _____________________________', small))
    sig = Table([[owner_cell,
                  Paragraph('Contractor _____________________________', small)]],
                colWidths=[3.5 * inch, 3.5 * inch])
    sig.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0),
                             ('VALIGN', (0, 0), (-1, -1), 'BOTTOM')]))
    elems.append(sig)

    doc.build(elems)
    buf.seek(0)
    return buf


# ── list ──────────────────────────────────────────────────────────────────

@contract_bp.route('/')
@login_required
def index():
    view = request.args.get('view', 'active')
    search = (request.args.get('q') or '').strip()

    base = Contract.query.filter_by(user_id=current_user.id)
    if search:
        like = f'%{search}%'
        base = base.join(Customer).filter(
            or_(Contract.title.ilike(like), Customer.name.ilike(like)))

    # Tab counts reflect the current search so the numbers stay consistent.
    status_counts = dict(
        base.with_entities(Contract.status, db.func.count(Contract.id))
        .group_by(Contract.status).all())
    counts = {
        'active': sum(status_counts.get(s, 0) for s in CONTRACT_ACTIVE_STATUSES),
        'archived': sum(status_counts.get(s, 0) for s in CONTRACT_ARCHIVED_STATUSES),
        'all': sum(status_counts.values()),
    }

    listing = base
    if view == 'active':
        listing = listing.filter(Contract.status.in_(CONTRACT_ACTIVE_STATUSES))
    elif view == 'archived':
        listing = listing.filter(Contract.status.in_(CONTRACT_ARCHIVED_STATUSES))

    # Terms-profile filter (F0). Counts reflect the CURRENT status view + search,
    # so a chip's number matches what you'd see after clicking it. An unknown
    # value is ignored, so a bad query string just shows everything.
    profile = request.args.get('profile')
    if profile not in VALID_TERMS_PROFILES:
        profile = None
    profile_rows = dict(
        listing.with_entities(Contract.terms_profile, db.func.count(Contract.id))
        .group_by(Contract.terms_profile).all())
    profile_counts = {
        'all': sum(profile_rows.values()),
        'simple': profile_rows.get('simple', 0),
        'progress': profile_rows.get('progress', 0),
        'developer_gc': profile_rows.get('developer_gc', 0),
    }
    if profile:
        listing = listing.filter(Contract.terms_profile == profile)

    contracts = (listing
                 .options(
                     selectinload(Contract.customer),
                     selectinload(Contract.project),
                     selectinload(Contract.draws).selectinload(ContractDraw.invoice),
                 )
                 .order_by(Contract.created_at.desc())
                 .paginate(page=max(request.args.get('page', 1, type=int) or 1, 1),
                           per_page=PAGE_SIZE, error_out=False))
    return render_template('contracts/list.html', contracts=contracts.items,
                           pagination=contracts, view=view, counts=counts,
                           q=search, profile=profile, profile_counts=profile_counts,
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
            contract.scope_of_work = (request.form.get('scope_of_work') or '').strip()
            _apply_terms_profile(contract, request.form)
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
    existing = Contract.query.filter_by(
        quote_id=quote.id, user_id=current_user.id).first()
    if existing:
        flash('This proposal already has a contract.', 'error')
        return redirect(url_for('contracts.edit', contract_id=existing.id))
    if quote.status != 'approved':
        flash('Only an approved proposal can be converted to a contract.', 'error')
        return redirect(url_for('quotes.edit', quote_id=quote.id))

    # A signed proposal becomes active work — make sure it has a Job. If the
    # proposal wasn't already linked to one, create it now (carrying the
    # customer + address → Location), so "convert" produces contract + Job.
    project_id = quote.project_id
    if not project_id:
        customer = quote.customer
        # Prefer the proposal's own property address (if the salesperson picked
        # or typed one); otherwise fall back to the customer's default address.
        job_address = None
        job_location_id = None
        if quote.location_id and quote.location:
            job_address = quote.location.address
            job_location_id = quote.location_id
        elif customer:
            job_address = customer.address
        project = Project(
            name=quote.title or (f"Job for {customer.name}" if customer else 'New job'),
            address=job_address,
            status='Active',
            customer_id=quote.customer_id,
        )
        db.session.add(project)
        db.session.flush()
        if job_location_id:
            project.location_id = job_location_id
        else:
            loc = find_or_create_location(current_user.id, quote.customer_id, job_address)
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
        scope_of_work=_scope_from_quote(quote),
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


# ── combine several approved proposals into one contract ────────────────────

@contract_bp.route('/combine', methods=['GET', 'POST'])
@login_required
def combine():
    if request.method == 'POST':
        ids = request.form.getlist('quote_ids', type=int)
        if not ids:
            flash('Select at least one approved proposal.', 'error')
            return redirect(url_for('contracts.combine'))

        quotes = (Quote.query
                  .filter(Quote.id.in_(ids), Quote.user_id == current_user.id)
                  .options(selectinload(Quote.items), selectinload(Quote.customer))
                  .all())
        if len(quotes) != len(set(ids)):
            flash('One or more proposals could not be found.', 'error')
            return redirect(url_for('contracts.combine'))
        if any(q.status != 'approved' for q in quotes):
            flash('Only approved proposals can be combined.', 'error')
            return redirect(url_for('contracts.combine'))
        if len({q.customer_id for q in quotes}) != 1:
            flash('All proposals must belong to the same customer.', 'error')
            return redirect(url_for('contracts.combine'))

        # Stable order (by id) so the "primary" proposal and the scope read
        # predictably.
        quotes.sort(key=lambda q: q.id)
        primary = quotes[0]
        project_id = _ensure_project_for_quote(primary)

        contract = Contract(
            user_id=current_user.id,
            customer_id=primary.customer_id,
            project_id=project_id,
            quote_id=primary.id,
            number=_next_contract_number(),
            title=(primary.title if len(quotes) == 1
                   else f'Contract for {primary.customer.name}'),
            contract_total=sum(q.total or 0 for q in quotes),
            notes=primary.notes,
            scope_of_work=_scope_from_quotes(quotes),
            status='draft',
        )
        db.session.add(contract)
        db.session.flush()

        # Record every proposal rolled in (primary included) for traceability,
        # snapshotting each total at merge time.
        for q in quotes:
            contract.proposals.append(
                ContractProposal(quote_id=q.id, amount=q.total or 0))

        # Seed a draw schedule: summed deposits up front, then the balance.
        deposit = sum(q.deposit or 0 for q in quotes)
        seq = 0
        if deposit:
            contract.draws.append(ContractDraw(
                sequence=seq, description='Deposit', amount=deposit,
                status='pending'))
            seq += 1
            balance = (contract.contract_total or 0) - deposit
            if balance > 0:
                contract.draws.append(ContractDraw(
                    sequence=seq, description='Balance on completion',
                    amount=balance, status='pending'))

        for q in quotes:
            q.status = 'converted'
        db.session.commit()
        flash(f'Contract created from {len(quotes)} proposal(s). '
              'Review the draw schedule below.', 'success')
        return redirect(url_for('contracts.edit', contract_id=contract.id))

    # GET — approved, not-yet-converted proposals, grouped by customer.
    quotes = (Quote.query
              .filter_by(user_id=current_user.id, status='approved')
              .options(selectinload(Quote.customer))
              .order_by(Quote.customer_id.asc(), Quote.created_at.asc())
              .all())
    return render_template('contracts/combine.html', quotes=quotes)


# ── send for signature + public acceptance view ─────────────────────────────

@contract_bp.route('/<int:contract_id>/send', methods=['POST'])
@login_required
def send(contract_id):
    contract = _owned_contract_or_404(contract_id)
    if contract.status in ('active', 'completed'):
        flash('This contract is already under way.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))
    if not _contract_link_is_active(contract):
        _refresh_contract_link(contract)
    if contract.status == 'draft':
        contract.status = 'sent'
    if not contract.sent_at:
        contract.sent_at = datetime.utcnow()
    db.session.commit()
    link = url_for('contracts.public_view', token=contract.public_token,
                   _external=True)
    flash(f'Contract marked as sent. Share this acceptance link with the '
          f'customer: {link}', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


@contract_bp.route('/<int:contract_id>/email', methods=['POST'])
@login_required
def email(contract_id):
    contract = _owned_contract_or_404(contract_id)
    if contract.status in ('active', 'completed'):
        flash('This contract is already under way.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))
    try:
        ok, message = send_contract_email(contract)
    except Exception:  # noqa: BLE001 — provider failures are logged below
        current_app.logger.exception('Failed to email contract %s', contract.id)
        ok, message = False, 'Email failed. Please try again or use the share link.'
    if ok:
        if contract.status == 'draft':
            contract.status = 'sent'
        if not contract.sent_at:
            contract.sent_at = datetime.utcnow()
        db.session.commit()
        flash(message, 'success')
    else:
        flash(message, 'error')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


@contract_bp.route('/c/<token>')
@limiter.limit("60 per minute")
def public_view(token):
    contract = Contract.query.filter_by(public_token=token).first_or_404()
    if not _contract_link_is_active(contract):
        abort(404)
    return render_template('contracts/public.html', contract=contract,
                           company=COMPANY, consent_text=CONSENT_TEXT)


@contract_bp.route('/c/<token>/accept', methods=['POST'])
@limiter.limit("5 per minute")
def public_accept(token):
    contract = Contract.query.filter_by(public_token=token).first_or_404()
    if not _contract_link_is_active(contract):
        abort(404)
    if contract.signed_at:
        flash('This contract has already been accepted.', 'success')
        return redirect(url_for('contracts.public_view', token=token))

    name = (request.form.get('signature_name') or '').strip()
    signature = _validated_signature_data(
        (request.form.get('signature_data') or '').strip())
    if not name or len(name) > 150 or not signature:
        flash('Please type your name and sign before accepting.', 'error')
        return redirect(url_for('contracts.public_view', token=token))
    if not request.form.get('consent'):
        flash('Please check the box to confirm your electronic signature.', 'error')
        return redirect(url_for('contracts.public_view', token=token))

    contract.signature_name = name
    contract.signature_data = signature
    contract.signed_at = datetime.utcnow()
    if contract.status in ('draft', 'sent'):
        contract.status = 'accepted'
    record_signature_event('contract', contract.id, 'approved', signer_name=name)
    db.session.commit()
    flash('Thank you — your acceptance has been recorded.', 'success')
    return redirect(url_for('contracts.public_view', token=token))


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

    # Gate billing on acceptance: a contract that was sent for signature
    # shouldn't be billed until the customer accepts. A never-sent 'draft'
    # contract stays billable (handshake deals).
    if contract.status == 'sent':
        flash('This contract is awaiting customer acceptance — bill it once the '
              'customer has signed.', 'error')
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
    # Withhold retainage when the contract has it turned on. We snapshot both the
    # % and the resulting amount (rounded to cents) onto the invoice, so the net
    # due is fixed and a later change to the contract's % never alters this
    # invoice. When retainage is off, nothing is set and the invoice is identical
    # to a normal progress invoice.
    if contract.retainage_active:
        inv.retainage_percent = contract.retainage_percent
        inv.retainage_amount = round((inv.total or 0) * contract.retainage_percent / 100.0, 2)
    db.session.flush()

    draw.invoice_id = inv.id
    draw.status = 'invoiced'
    if contract.status in ('draft', 'accepted'):
        contract.status = 'active'
    db.session.commit()
    flash(f'Draw billed as invoice {inv.number}. Send it to the customer below.', 'success')
    return redirect(url_for('invoices.edit', invoice_id=inv.id))


@contract_bp.route('/<int:contract_id>/release-retainage', methods=['POST'])
@login_required
def release_retainage(contract_id):
    """Bill the accumulated retainage back to the customer — one invoice, once.

    Enabled only when retainage is on, every draw has been paid, and there is
    held retainage to release. The release amount is the exact sum of what was
    withheld across the draw invoices (not re-derived from the %)."""
    # Lock the contract row so two concurrent clicks can't both release.
    contract = db.session.execute(
        select(Contract)
        .where(Contract.id == contract_id, Contract.user_id == current_user.id)
        .with_for_update()
    ).scalar_one_or_none()
    if contract is None:
        abort(404)

    if not contract.can_release_retainage:
        if contract.retainage_is_released:
            msg = 'Retainage has already been released.'
        elif not contract.retainage_active:
            msg = 'Retainage is not enabled on this contract.'
        elif not contract.all_draws_paid:
            msg = 'Release retainage once every draw has been paid.'
        else:
            msg = 'There is no held retainage to release.'
        flash(msg, 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))

    held = round(contract.retainage_held_to_date, 2)
    n = len(contract.draws)
    inv = Invoice(
        user_id=current_user.id,
        customer_id=contract.customer_id,
        project_id=contract.project_id,
        contract_id=contract.id,
        number=_next_number(),
        title=f"{contract.title} — Retainage release",
        public_token=_new_invoice_token(),
        is_retainage_release=True,
    )
    db.session.add(inv)
    inv.items.append(InvoiceItem(
        description=f"Release of retainage — {contract.retainage_percent:g}% held "
                    f"across {n} draw{'s' if n != 1 else ''} on contract {contract.number}",
        quantity=1, unit_price=held))
    inv.recalculate_total()
    db.session.flush()

    contract.retainage_released_at = datetime.utcnow()
    contract.retainage_release_invoice_id = inv.id
    db.session.commit()
    flash(f'Retainage of ${held:,.2f} released as invoice {inv.number}.', 'success')
    return redirect(url_for('invoices.edit', invoice_id=inv.id))


@contract_bp.route('/<int:contract_id>/pdf')
@login_required
def pdf(contract_id):
    contract = _owned_contract_or_404(contract_id)
    buf = build_contract_pdf(contract)
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=False,
                     download_name=f"{safe_filename(contract.customer.name if contract.customer else None, contract.number or ('Contract ' + str(contract.id)), 'Contract')}.pdf")
