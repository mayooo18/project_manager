"""Lot releases (F6).

A per-job/property release form. Draft until signed by BOTH the owner (via a
public e-sign link, like quotes/change orders) and the contractor (in-app).
When a job's contract has lot releases enabled, work logging and invoicing on
that job are blocked until a release is fully signed (gate lives on
Project.lot_release_ok).
"""
import secrets
from io import BytesIO
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    send_file,
)
from flask_login import login_required, current_user

from extensions import db, limiter
from models import LotRelease, Project
from quote_routes import (
    COMPANY, LOGO_PATH, _pdf_text, safe_filename, _validated_signature_data,
)
from signature_audit import record_signature_event, CONSENT_TEXT

lot_release_bp = Blueprint('lot_releases', __name__, url_prefix='/lot-releases')

TEXT_FIELDS = [
    'address', 'pin', 'deed_survey_ref', 'plan_revision', 'permit_number',
    'permit_status', 'superintendent', 'water_connection', 'sanitary_connection',
    'stockpile', 'cut_fill_disposal', 'water_control_plan', 'testing_contact',
    'testing_plan', 'handoff_reviewer', 'deferred_operations', 'notes',
]
DATE_FIELDS = ['start_date', 'framing_handoff_date']


def _owned_lr_or_404(lot_release_id):
    return LotRelease.query.filter_by(
        id=lot_release_id, user_id=current_user.id).first_or_404()


def _float(raw, default=0.0):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _parse_date(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _new_token():
    return secrets.token_urlsafe(32)


def _link_active(lr, now=None):
    now = now or datetime.utcnow()
    return (lr.public_token and lr.public_token_revoked_at is None
            and (lr.public_token_expires_at is None or lr.public_token_expires_at > now))


def _apply_form(lr, form):
    for f in TEXT_FIELDS:
        setattr(lr, f, (form.get(f) or '').strip() or None)
    for f in DATE_FIELDS:
        setattr(lr, f, _parse_date(form.get(f)))
    lr.base_price = _float(form.get('base_price'))
    lr.signed_changes = _float(form.get('signed_changes'))


def _refresh_status(lr):
    lr.status = 'signed' if lr.is_fully_signed else 'draft'


# ── create / edit ────────────────────────────────────────────────────────────

@lot_release_bp.route('/job/<int:project_id>/new', methods=['POST'])
@login_required
def new(project_id):
    project = Project.query.get_or_404(project_id)
    lr = LotRelease(user_id=current_user.id, project_id=project.id,
                    address=project.address)
    db.session.add(lr)
    db.session.commit()
    flash('Lot release created — fill in the details below.', 'success')
    return redirect(url_for('lot_releases.edit', lot_release_id=lr.id))


@lot_release_bp.route('/<int:lot_release_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(lot_release_id):
    lr = _owned_lr_or_404(lot_release_id)
    if request.method == 'POST':
        if lr.is_fully_signed:
            flash('This release is signed and can no longer be edited.', 'error')
            return redirect(url_for('lot_releases.edit', lot_release_id=lr.id))
        _apply_form(lr, request.form)
        db.session.commit()
        flash('Lot release saved.', 'success')
        return redirect(url_for('lot_releases.edit', lot_release_id=lr.id))
    return render_template('lot_releases/form.html', lr=lr,
                           link_active=_link_active(lr))


@lot_release_bp.route('/<int:lot_release_id>/delete', methods=['POST'])
@login_required
def delete(lot_release_id):
    lr = _owned_lr_or_404(lot_release_id)
    project_id = lr.project_id
    db.session.delete(lr)
    db.session.commit()
    flash('Lot release deleted.', 'success')
    return redirect(url_for('project_detail', project_id=project_id))


# ── contractor signs (in-app) ────────────────────────────────────────────────

@lot_release_bp.route('/<int:lot_release_id>/contractor-sign', methods=['POST'])
@login_required
def contractor_sign(lot_release_id):
    lr = _owned_lr_or_404(lot_release_id)
    # Insurance gate (F8): block the contractor's sign when an assigned sub on
    # this job has an expired or missing COI. No assigned subs → never blocks.
    from insurance_routes import contract_blocks_release
    if lr.project is not None and any(
            contract_blocks_release(con) for con in lr.project.contracts):
        flash('An assigned subcontractor on this job has an expired or missing '
              'COI — resolve insurance compliance before signing the lot release.',
              'error')
        return redirect(url_for('lot_releases.edit', lot_release_id=lr.id))
    name = (request.form.get('signature_name') or '').strip()
    signature = _validated_signature_data(request.form.get('signature_data') or '')
    if not name or signature is None:
        flash('Enter a name and draw a signature to sign.', 'error')
        return redirect(url_for('lot_releases.edit', lot_release_id=lr.id))
    lr.contractor_signature_name = name
    lr.contractor_signature_data = signature
    lr.contractor_signed_at = datetime.utcnow()
    record_signature_event('lot_release', lr.id, 'approved', signer_name=name,
                           consent_text='Contractor sign-off on lot release.')
    _refresh_status(lr)
    db.session.commit()
    flash('Signed as contractor.' + (' Release is now fully signed.'
          if lr.is_fully_signed else ' Awaiting the owner signature.'), 'success')
    return redirect(url_for('lot_releases.edit', lot_release_id=lr.id))


# ── send for owner e-signature ───────────────────────────────────────────────

@lot_release_bp.route('/<int:lot_release_id>/send', methods=['POST'])
@login_required
def send(lot_release_id):
    lr = _owned_lr_or_404(lot_release_id)
    if not _link_active(lr):
        lr.public_token = _new_token()
        lr.public_token_expires_at = datetime.utcnow() + timedelta(days=30)
        lr.public_token_revoked_at = None
    if lr.sent_at is None:
        lr.sent_at = datetime.utcnow()
    db.session.commit()
    link = url_for('lot_releases.public_view', token=lr.public_token, _external=True)
    flash(f'Owner signing link ready: {link}', 'success')
    return redirect(url_for('lot_releases.edit', lot_release_id=lr.id))


# ── owner public view + sign (no login) ──────────────────────────────────────

def _get_public_lr(token):
    lr = LotRelease.query.filter_by(public_token=token).first_or_404()
    if not _link_active(lr):
        abort(404)
    return lr


@lot_release_bp.route('/lr/<token>')
@limiter.limit("60 per minute")
def public_view(token):
    lr = _get_public_lr(token)
    return render_template('lot_releases/public.html', lr=lr, company=COMPANY,
                           consent_text=CONSENT_TEXT)


@lot_release_bp.route('/lr/<token>/sign', methods=['POST'])
@limiter.limit("10 per minute")
def public_sign(token):
    lr = _get_public_lr(token)
    if lr.owner_signed_at:
        flash('This release has already been signed.', 'error')
        return redirect(url_for('lot_releases.public_view', token=token))
    name = (request.form.get('signature_name') or '').strip()
    signature = _validated_signature_data(request.form.get('signature_data') or '')
    if not name or signature is None:
        flash('Enter your name and draw a signature to sign.', 'error')
        return redirect(url_for('lot_releases.public_view', token=token))
    lr.owner_signature_name = name
    lr.owner_signature_data = signature
    lr.owner_signed_at = datetime.utcnow()
    record_signature_event('lot_release', lr.id, 'approved', signer_name=name)
    _refresh_status(lr)
    db.session.commit()
    return render_template('lot_releases/public.html', lr=lr, company=COMPANY,
                           signed=True, consent_text=CONSENT_TEXT)


# ── PDF ───────────────────────────────────────────────────────────────────────

def build_lot_release_pdf(lr):
    import os
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image)

    buf = BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.55 * inch,
                            bottomMargin=0.55 * inch, leftMargin=0.7 * inch,
                            rightMargin=0.7 * inch)
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small = ParagraphStyle('small', parent=normal, fontSize=9, leading=12)
    label = ParagraphStyle('label', parent=small, fontName='Helvetica-Bold')
    section = ParagraphStyle('section', parent=normal, fontName='Helvetica-Bold',
                             fontSize=10.5, spaceBefore=8, spaceAfter=3)
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
    elems.append(Paragraph('Lot Release', title))
    elems.append(Spacer(1, 10))

    def rows(pairs):
        data = [[Paragraph(k, label), Paragraph(_pdf_text(v or '—', 400,
                 preserve_newlines=True), small)] for k, v in pairs]
        t = Table(data, colWidths=[2.1 * inch, 5.0 * inch])
        t.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LINEBELOW', (0, 0), (-1, -1), 0.25, colors.HexColor('#eeeeee')),
        ]))
        elems.append(t)

    d = lambda x: x.strftime('%m/%d/%Y') if x else ''
    elems.append(Paragraph('Property', section))
    rows([('Address', lr.address), ('PIN', lr.pin),
          ('Deed / survey ref', lr.deed_survey_ref),
          ('Plan revision', lr.plan_revision)])
    elems.append(Paragraph('Permit', section))
    rows([('Permit number', lr.permit_number), ('Permit status', lr.permit_status)])
    elems.append(Paragraph('Schedule', section))
    rows([('Start date', d(lr.start_date)),
          ('Framing handoff', d(lr.framing_handoff_date)),
          ('Superintendent', lr.superintendent)])
    elems.append(Paragraph('Utilities', section))
    rows([('Water connection', lr.water_connection),
          ('Sanitary connection', lr.sanitary_connection)])
    elems.append(Paragraph('Site', section))
    rows([('Stockpile', lr.stockpile),
          ('Cut / fill / disposal', lr.cut_fill_disposal),
          ('Water-control plan', lr.water_control_plan)])
    elems.append(Paragraph('Testing & handoff', section))
    rows([('Testing contact', lr.testing_contact),
          ('Testing plan', lr.testing_plan),
          ('Handoff reviewer', lr.handoff_reviewer),
          ('Deferred operations', lr.deferred_operations)])
    elems.append(Paragraph('Pricing', section))
    rows([('Base price', f"${(lr.base_price or 0):,.2f}"),
          ('Signed changes', f"${(lr.signed_changes or 0):,.2f}"),
          ('Total', f"${lr.total:,.2f}")])
    if lr.notes:
        elems.append(Paragraph('Notes', section))
        rows([('', lr.notes)])

    # Signatures — owner + contractor
    elems.append(Spacer(1, 16))
    elems.append(Paragraph('Signatures', section))

    def sig_cell(heading, name, data_url, when):
        cell = [Paragraph(f'<b>{heading}</b>', small)]
        if data_url:
            try:
                b64 = data_url.split(',', 1)[1]
                import base64
                img = Image(BytesIO(base64.b64decode(b64)))
                ratio = img.imageHeight / float(img.imageWidth)
                img.drawWidth = 2.1 * inch
                img.drawHeight = min(0.7 * inch, 2.1 * inch * ratio)
                img.hAlign = 'LEFT'
                cell += [Spacer(1, 4), img]
            except Exception:
                pass
        cell.append(Paragraph('_______________________________', small))
        cell.append(Paragraph(_pdf_text(name or '', 120)
                              + (f" · {when.strftime('%m/%d/%Y')}" if when else ''), small))
        return cell

    sigs = Table([[sig_cell('Owner', lr.owner_signature_name,
                            lr.owner_signature_data, lr.owner_signed_at),
                   sig_cell('Contractor', lr.contractor_signature_name,
                            lr.contractor_signature_data, lr.contractor_signed_at)]],
                 colWidths=[3.55 * inch, 3.55 * inch])
    sigs.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                              ('LEFTPADDING', (0, 0), (-1, -1), 0),
                              ('TOPPADDING', (0, 0), (-1, -1), 8)]))
    elems.append(sigs)

    pdf.build(elems)
    buf.seek(0)
    return buf


@lot_release_bp.route('/<int:lot_release_id>/pdf')
@login_required
def pdf(lot_release_id):
    lr = _owned_lr_or_404(lot_release_id)
    buf = build_lot_release_pdf(lr)
    name = safe_filename(lr.address or None, f'LotRelease-{lr.id}', 'LotRelease')
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{name}.pdf')
