"""
Lien waivers & certificates of completion (Phase 6d — GC admin).

Generates professional PDFs off the company letterhead for the four standard
lien-waiver types (conditional/unconditional × progress/final) plus a
certificate of completion. Records are stored so there is an audit trail of
what was issued.

NOTE: lien-waiver wording is often set by state statute. These are clean,
general-purpose forms with a footer reminding the user to confirm they meet
their state's requirements — they are not a substitute for legal advice.
"""

from io import BytesIO

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, send_file,
)
from flask_login import login_required, current_user

from extensions import db
from models import GcDocument, Project, Customer
from forms import GcDocumentForm, DeleteForm
from quote_routes import COMPANY, LOGO_PATH, _pdf_text

waiver_bp = Blueprint('waivers', __name__, url_prefix='/waivers')

DOC_LABELS = {
    'conditional_progress': 'Conditional Waiver and Release on Progress Payment',
    'unconditional_progress': 'Unconditional Waiver and Release on Progress Payment',
    'conditional_final': 'Conditional Waiver and Release on Final Payment',
    'unconditional_final': 'Unconditional Waiver and Release on Final Payment',
    'completion': 'Certificate of Completion',
}


def _owned_doc_or_404(doc_id):
    return GcDocument.query.filter_by(id=doc_id, user_id=current_user.id).first_or_404()


def _project_choices():
    projects = Project.query.order_by(Project.name.asc()).all()
    return [(0, '— None —')] + [(p.id, p.name) for p in projects]


def _customer_choices():
    customers = (Customer.query.filter_by(user_id=current_user.id)
                 .order_by(Customer.name.asc()).all())
    return [(0, '— None —')] + [(c.id, c.name) for c in customers]


# ── document body text ─────────────────────────────────────────────────────

def _waiver_body(doc):
    claimant = COMPANY['name']
    owner = _pdf_text(doc.owner_name or 'the Owner', 150)
    prop = _pdf_text(doc.property_address or '________________________', 250)
    amount = f"${doc.amount:,.2f}" if doc.amount else "$________"
    through = doc.through_date.strftime('%B %d, %Y') if doc.through_date else '____________'
    check = _pdf_text(doc.check_number or '________', 60)
    exceptions = _pdf_text(doc.exceptions, 2000, preserve_newlines=True) if doc.exceptions else 'None'

    if doc.doc_kind == 'conditional_progress':
        return (
            f"Upon receipt by the undersigned, <b>{claimant}</b> (\"Claimant\"), of a check from "
            f"{owner} in the sum of <b>{amount}</b> (check no. {check}), and when the check has "
            f"been properly endorsed and has been paid by the bank upon which it is drawn, this "
            f"document becomes effective to release and the Claimant releases any mechanic's lien, "
            f"stop payment notice, or payment bond right the Claimant has for labor and materials "
            f"furnished through <b>{through}</b> to the property located at <b>{prop}</b>. "
            f"<br/><br/>This release covers a progress payment only and does not cover any retention, "
            f"pending modifications and changes, or items furnished after the through date. "
            f"Exceptions: {exceptions}.")
    if doc.doc_kind == 'unconditional_progress':
        return (
            f"The undersigned, <b>{claimant}</b> (\"Claimant\"), has been paid and has received a "
            f"progress payment in the sum of <b>{amount}</b> for labor and materials furnished "
            f"through <b>{through}</b> to the property located at <b>{prop}</b>, and does hereby "
            f"waive and release any mechanic's lien, stop payment notice, or payment bond right the "
            f"Claimant has to that extent. "
            f"<br/><br/><b>This document waives and releases lien, stop payment notice, and payment "
            f"bond rights unconditionally and states that the Claimant has been paid for giving up "
            f"those rights.</b> This release covers a progress payment only. Exceptions: {exceptions}.")
    if doc.doc_kind == 'conditional_final':
        return (
            f"Upon receipt by the undersigned, <b>{claimant}</b> (\"Claimant\"), of a check from "
            f"{owner} in the sum of <b>{amount}</b> (check no. {check}), and when the check has "
            f"been properly endorsed and has been paid by the bank upon which it is drawn, this "
            f"document becomes effective to release and the Claimant releases any mechanic's lien, "
            f"stop payment notice, or payment bond right the Claimant has on the property located at "
            f"<b>{prop}</b> for all labor and materials furnished. "
            f"<br/><br/>This release covers the final payment to the Claimant for all labor, services, "
            f"equipment, or material furnished to the property. Exceptions: {exceptions}.")
    if doc.doc_kind == 'unconditional_final':
        return (
            f"The undersigned, <b>{claimant}</b> (\"Claimant\"), has been paid in full for all labor, "
            f"services, equipment, or material furnished to the property located at <b>{prop}</b>, "
            f"and does hereby waive and release any mechanic's lien, stop payment notice, or payment "
            f"bond right the Claimant has on that property. "
            f"<br/><br/><b>This document waives and releases lien, stop payment notice, and payment "
            f"bond rights unconditionally and states that the Claimant has been paid in full.</b> "
            f"Exceptions: {exceptions}.")
    # completion certificate
    scope = _pdf_text(doc.notes, 3000, preserve_newlines=True) if doc.notes else \
        'the work of improvement contracted for at the property described below'
    return (
        f"<b>{claimant}</b> hereby certifies that the work of improvement described below was "
        f"substantially completed on <b>{through}</b> at the property located at <b>{prop}</b> "
        f"for {owner}, in accordance with the contract documents. "
        f"<br/><br/><b>Scope of work:</b><br/>{scope}")


def build_gc_document_pdf(doc):
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
    pdf = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
    )
    styles = getSampleStyleSheet()
    normal = styles['Normal']
    small = ParagraphStyle('small', parent=normal, fontSize=9, leading=13)
    body = ParagraphStyle('body', parent=normal, fontSize=10.5, leading=16)
    company_name = ParagraphStyle('coname', parent=normal, fontSize=13, fontName='Helvetica-Bold')
    title = ParagraphStyle('title', parent=styles['Title'], fontSize=15,
                           alignment=TA_CENTER, spaceAfter=0)
    foot = ParagraphStyle('foot', parent=normal, fontSize=7.5, textColor=colors.grey,
                          alignment=TA_CENTER, leading=10)

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
    elems.append(Table([[header_left]], colWidths=[6.8 * inch],
                       style=TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0)])))
    elems.append(Spacer(1, 14))

    elems.append(Paragraph(DOC_LABELS.get(doc.doc_kind, 'Document'), title))
    elems.append(Spacer(1, 16))
    elems.append(Paragraph(_waiver_body(doc), body))
    elems.append(Spacer(1, 30))

    # Signature block
    date_line = 'Date: _____________________'
    sig = Table(
        [[Paragraph(f"<b>{COMPANY['name']}</b>", small), ''],
         [Paragraph('By: _____________________________', small),
          Paragraph(date_line, small)],
         [Paragraph('Name / Title: ____________________', small), '']],
        colWidths=[3.6 * inch, 3.0 * inch])
    sig.setStyle(TableStyle([
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elems.append(sig)
    elems.append(Spacer(1, 24))

    if doc.doc_kind != 'completion':
        elems.append(Paragraph(
            'This form is provided for convenience. Lien-waiver requirements vary by '
            'state and some states prescribe an exact statutory form — confirm this '
            'document satisfies the requirements of the state where the property is '
            'located before relying on it. It is not legal advice.', foot))

    pdf.build(elems)
    buf.seek(0)
    return buf


# ── list / CRUD ─────────────────────────────────────────────────────────────

@waiver_bp.route('/')
@login_required
def index():
    docs = (GcDocument.query.filter_by(user_id=current_user.id)
            .order_by(GcDocument.created_at.desc()).all())
    return render_template('waivers.html', documents=docs,
                           doc_labels=DOC_LABELS, delete_form=DeleteForm())


@waiver_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new():
    return _save_document(None)


@waiver_bp.route('/<int:doc_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(doc_id):
    doc = _owned_doc_or_404(doc_id)
    return _save_document(doc)


def _save_document(doc):
    form = GcDocumentForm(obj=doc)
    form.project_id.choices = _project_choices()
    form.customer_id.choices = _customer_choices()
    if request.method == 'GET' and doc:
        form.project_id.data = doc.project_id or 0
        form.customer_id.data = doc.customer_id or 0

    if form.validate_on_submit():
        if doc is None:
            doc = GcDocument(user_id=current_user.id)
            db.session.add(doc)
        form.populate_obj(doc)
        doc.project_id = form.project_id.data or None
        doc.customer_id = form.customer_id.data or None
        db.session.commit()
        flash('Document saved.', 'success')
        return redirect(url_for('waivers.edit', doc_id=doc.id))

    return render_template('waiver_form.html', form=form, doc=doc)


@waiver_bp.route('/<int:doc_id>/delete', methods=['POST'])
@login_required
def delete(doc_id):
    doc = _owned_doc_or_404(doc_id)
    db.session.delete(doc)
    db.session.commit()
    flash('Document deleted.', 'success')
    return redirect(url_for('waivers.index'))


@waiver_bp.route('/<int:doc_id>/pdf')
@login_required
def pdf(doc_id):
    doc = _owned_doc_or_404(doc_id)
    buf = build_gc_document_pdf(doc)
    kind = doc.doc_kind
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=f'{kind}-{doc.id}.pdf')
