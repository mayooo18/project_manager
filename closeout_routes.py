"""Closeout package (F12).

A one-click per-property closeout PDF plus a punch list and a closeout
acceptance date. The acceptance date starts the F2 retainage-release clock (a
reminder) and, later, the F13 warranty clock. The package reuses the F4 pypdf
merge and the F5 evidence-to-PDF helper to assemble sworn statements, lien
waivers, evidence, hold-point photos and project files.
"""
import os
from io import BytesIO
from datetime import datetime, timedelta

from flask import (
    Blueprint, request, redirect, url_for, flash, abort, send_file, current_app,
)
from flask_login import login_required, current_user

from extensions import db
from models import (
    Project, PunchItem, Invoice, SwornStatement, Reminder, ChangeOrder,
)
from quote_routes import COMPANY, LOGO_PATH, _pdf_text, safe_filename

closeout_bp = Blueprint('closeout', __name__, url_prefix='/closeout')

FINAL_WAIVER_KINDS = {'conditional_final', 'unconditional_final', 'completion'}


def _owned_project_or_404(project_id):
    project = Project.query.get_or_404(project_id)
    ok = (project.customer and project.customer.user_id == current_user.id) or \
         any(c.user_id == current_user.id for c in project.contracts)
    if not ok:
        abort(404)
    return project


def _owned_punch_or_404(item_id):
    item = PunchItem.query.get_or_404(item_id)
    _owned_project_or_404(item.project_id)
    return item


# ── punch list ────────────────────────────────────────────────────────────────

@closeout_bp.route('/job/<int:project_id>/punch/add', methods=['POST'])
@login_required
def add_punch(project_id):
    project = _owned_project_or_404(project_id)
    desc = (request.form.get('description') or '').strip()
    if not desc:
        flash('Enter a punch-list item.', 'error')
    else:
        db.session.add(PunchItem(project_id=project.id, description=desc, status='open'))
        db.session.commit()
        flash('Punch item added.', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


@closeout_bp.route('/punch/<int:item_id>/toggle', methods=['POST'])
@login_required
def toggle_punch(item_id):
    item = _owned_punch_or_404(item_id)
    if item.status == 'closed':
        item.status = 'open'
        item.closed_at = None
    else:
        item.status = 'closed'
        item.closed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('project_detail', project_id=item.project_id))


@closeout_bp.route('/punch/<int:item_id>/delete', methods=['POST'])
@login_required
def delete_punch(item_id):
    item = _owned_punch_or_404(item_id)
    pid = item.project_id
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('project_detail', project_id=pid))


# ── accept / reopen closeout ─────────────────────────────────────────────────

@closeout_bp.route('/job/<int:project_id>/accept', methods=['POST'])
@login_required
def accept(project_id):
    project = _owned_project_or_404(project_id)
    if project.is_closed_out:
        flash('This job is already closed out.', 'error')
        return redirect(url_for('project_detail', project_id=project.id))
    project.closeout_accepted_at = datetime.utcnow()
    # Start the retainage-release clock (F2): a reminder per retainage contract.
    for con in project.contracts:
        if getattr(con, 'retainage_enabled', False):
            days = con.retainage_release_days or 30
            db.session.add(Reminder(
                user_id=current_user.id,
                text=f"Retainage release due — contract {con.number or con.id}",
                due_date=(project.closeout_accepted_at + timedelta(days=days)).date()))
    db.session.commit()
    msg = 'Job marked closed out.'
    if project.open_punch_count:
        msg += f' Note: {project.open_punch_count} punch item(s) still open.'
    flash(msg, 'success')
    return redirect(url_for('project_detail', project_id=project.id))


@closeout_bp.route('/job/<int:project_id>/reopen', methods=['POST'])
@login_required
def reopen(project_id):
    from permissions import owner_required  # local import keeps decorator order simple
    project = _owned_project_or_404(project_id)
    if not current_user.is_owner:
        abort(403)
    project.closeout_accepted_at = None
    db.session.commit()
    flash('Closeout reopened.', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


# ── package PDF ────────────────────────────────────────────────────────────────

def _attachment_as_pdf(stored_filename, caption):
    """A stored file under UPLOAD_FOLDER as a PDF buffer: PDFs pass through,
    images become one captioned page, other types are skipped."""
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_filename or '')
    if not stored_filename or not os.path.exists(path):
        return None
    ext = (stored_filename.rsplit('.', 1)[-1].lower() if '.' in stored_filename else '')
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
            doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6 * inch,
                                    bottomMargin=0.6 * inch, leftMargin=0.6 * inch,
                                    rightMargin=0.6 * inch)
            iw, ih = ImageReader(path).getSize()
            scale = min(7.0 * inch / iw, 8.2 * inch / ih, 1.0)
            img = Image(path, width=iw * scale, height=ih * scale)
            styles = getSampleStyleSheet()
            doc.build([Paragraph(caption or '', styles['Normal']), Spacer(1, 8), img])
            buf.seek(0)
            return buf
        except Exception:
            return None
    return None


def _closeout_cover(project):
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
    section = ParagraphStyle('section', parent=normal, fontName='Helvetica-Bold',
                             fontSize=11, spaceBefore=10, spaceAfter=3)
    title = ParagraphStyle('title', parent=styles['Title'], fontSize=16,
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
    elems.append(Table([[header]], colWidths=[7.1 * inch],
                       style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0)])))
    elems.append(Spacer(1, 10))
    elems.append(Paragraph('Closeout Package', title))
    elems.append(Spacer(1, 3))
    cust = project.customer.name if project.customer else ''
    elems.append(Paragraph(f"{_pdf_text(project.name, 150)}"
                           + (f" · {_pdf_text(cust, 120)}" if cust else ''),
                           ParagraphStyle('s', parent=small, alignment=TA_CENTER)))
    if project.closeout_accepted_at:
        elems.append(Paragraph(f"Closeout accepted {project.closeout_accepted_at.strftime('%B %d, %Y')}",
                               ParagraphStyle('s2', parent=small, alignment=TA_CENTER)))
    elems.append(Spacer(1, 10))

    # Change-order reconciliation
    elems.append(Paragraph('Change-order reconciliation', section))
    for con in project.contracts:
        applied = [co for co in con.change_orders if co.applied_at is not None]
        orig = (con.contract_total or 0) - sum((co.total or 0) for co in applied)
        elems.append(Paragraph(
            f"Contract {con.number or con.id}: original ${orig:,.2f}"
            + (f" + {len(applied)} change order(s) ${sum((co.total or 0) for co in applied):,.2f}" if applied else "")
            + f" = ${(con.contract_total or 0):,.2f}", small))
        for co in applied:
            elems.append(Paragraph(f"  · {co.number or ''} {_pdf_text(co.title, 100)} — ${(co.total or 0):,.2f}", small))

    # Inspections (acceptance)
    insps = [i for perm in project.permits for i in perm.inspections if i.status == 'Passed']
    elems.append(Paragraph('Inspection / utility acceptance', section))
    if insps:
        for i in insps:
            elems.append(Paragraph(f"· {i.inspection_type} — Passed"
                                   + (f" {i.scheduled_date.strftime('%m/%d/%y')}" if i.scheduled_date else ''), small))
    else:
        elems.append(Paragraph('No passed inspections on record.', small))

    # Punch list
    elems.append(Paragraph('Punch list', section))
    if project.punch_items:
        for p in project.punch_items:
            mark = '☑' if p.status == 'closed' else '☐'
            elems.append(Paragraph(f"{mark} {_pdf_text(p.description, 300)}", small))
    else:
        elems.append(Paragraph('No punch items.', small))

    pdf.build(elems)
    buf.seek(0)
    return buf


def build_closeout_pdf(project):
    from invoice_routes import _merge_pdfs, _evidence_as_pdf
    parts = [_closeout_cover(project)]

    # Final sworn statement (latest per contract)
    try:
        from sworn_routes import build_sworn_pdf
        for con in project.contracts:
            st = (SwornStatement.query.join(Invoice, SwornStatement.invoice_id == Invoice.id)
                  .filter(Invoice.contract_id == con.id)
                  .order_by(SwornStatement.created_at.desc()).first())
            if st is not None:
                parts.append(build_sworn_pdf(st))
    except Exception:
        pass

    # Final lien waivers
    try:
        from waiver_routes import build_gc_document_pdf
        for doc in getattr(project, 'gc_documents', []):
            if doc.doc_kind in FINAL_WAIVER_KINDS:
                parts.append(build_gc_document_pdf(doc))
    except Exception:
        pass

    # Evidence across draws (concrete tickets, test results, photos, disposal)
    for con in project.contracts:
        for draw in con.draws:
            for ev in draw.evidence:
                buf = _evidence_as_pdf(ev)
                if buf is not None:
                    parts.append(buf)

    # Hold-point photos
    for hp in getattr(project, 'hold_points', []):
        for ph in hp.photos:
            buf = _attachment_as_pdf(ph.filename, f"Hold point: {hp.name}")
            if buf is not None:
                parts.append(buf)

    # Project files (product data / warranties / misc uploads)
    for f in getattr(project, 'files', []):
        buf = _attachment_as_pdf(f.filename, f.note or f.category or f.filename)
        if buf is not None:
            parts.append(buf)

    return _merge_pdfs(parts)


@closeout_bp.route('/job/<int:project_id>/package.pdf')
@login_required
def package(project_id):
    project = _owned_project_or_404(project_id)
    buf = build_closeout_pdf(project)
    name = safe_filename(project.customer.name if project.customer else None,
                         project.name or f'Job-{project.id}', 'Closeout')
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{name}-closeout.pdf')
