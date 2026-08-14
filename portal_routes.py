"""
Client portal (Phase 5) — a private magic-link per job, no accounts.

The owner enables a per-job link from the Job hub and shares it. The client
opens /portal/<token> and sees status, money summary, pending change orders to
e-sign, invoices, and documents — all read-only and served scoped to that job,
reusing the PDF builders already in the app. No login, no photos.
"""

import secrets
from datetime import datetime
from io import BytesIO

from flask import (
    Blueprint, render_template, redirect, url_for, flash, send_file, abort,
)
from flask_login import login_required

from extensions import db, limiter
from models import Project
from quote_routes import COMPANY, build_quote_pdf
from invoice_routes import build_invoice_pdf
from contract_routes import build_contract_pdf
from waiver_routes import build_gc_document_pdf

portal_bp = Blueprint('portal', __name__)


# ── helpers ────────────────────────────────────────────────────────────────

def _new_portal_token():
    while True:
        token = secrets.token_urlsafe(24)
        if not Project.query.filter_by(portal_token=token).first():
            return token


def _project_by_token(token):
    project = Project.query.filter_by(portal_token=token).first()
    if project is None or project.portal_token_revoked_at is not None:
        abort(404)
    return project


def _portal_data(project):
    contracts = list(project.contracts)
    invoices = sorted(project.invoices, key=lambda i: i.id, reverse=True)
    proposals = sorted(project.quotes, key=lambda q: q.id, reverse=True)
    change_orders = [co for c in contracts for co in c.change_orders]
    pending_cos = [co for co in change_orders if co.status == 'sent']
    signed_cos = [co for co in change_orders if co.status == 'approved']
    documents = sorted(project.gc_documents, key=lambda d: d.id, reverse=True)

    contract_total = sum(c.contract_total or 0 for c in contracts)
    billed_total = sum(c.billed_to_date for c in contracts)
    paid_total = sum(inv.total or 0 for inv in invoices if inv.status == 'paid')
    due_total = max(contract_total - paid_total, 0)

    return dict(
        contracts=contracts, invoices=invoices, proposals=proposals,
        pending_cos=pending_cos, signed_cos=signed_cos, documents=documents,
        contract_total=contract_total, billed_total=billed_total,
        paid_total=paid_total, due_total=due_total, company=COMPANY,
    )


# ── owner: enable / regenerate / revoke (from the Job hub) ──────────────────

@portal_bp.route('/projects/<int:project_id>/portal/enable', methods=['POST'])
@login_required
def enable(project_id):
    project = Project.query.get_or_404(project_id)
    if not project.portal_token:
        project.portal_token = _new_portal_token()
    project.portal_token_revoked_at = None
    db.session.commit()
    link = url_for('portal.view', token=project.portal_token, _external=True)
    flash(f'Client portal link is live: {link}', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


@portal_bp.route('/projects/<int:project_id>/portal/regenerate', methods=['POST'])
@login_required
def regenerate(project_id):
    project = Project.query.get_or_404(project_id)
    project.portal_token = _new_portal_token()
    project.portal_token_revoked_at = None
    db.session.commit()
    flash('A new client portal link was created; the old one no longer works.', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


@portal_bp.route('/projects/<int:project_id>/portal/revoke', methods=['POST'])
@login_required
def revoke(project_id):
    project = Project.query.get_or_404(project_id)
    project.portal_token_revoked_at = datetime.utcnow()
    db.session.commit()
    flash('Client portal link revoked.', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


def send_portal_email(project):
    """Email the client the portal link via the existing Gmail integration.
    Returns (ok, message). Needs the job's customer (Phase 7) + their email."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from googleapiclient.discovery import build as gbuild
    from google_routes import get_credentials

    customer = project.customer
    if not customer or not customer.email:
        return False, ('This job has no customer email. Set the customer on the job '
                       'and add their email on the Customers page.')
    if not project.portal_token or project.portal_token_revoked_at:
        return False, 'Enable the client portal first.'

    creds = get_credentials()
    if not creds:
        return False, 'Google account not connected (GOOGLE_REFRESH_TOKEN missing).'

    link = url_for('portal.view', token=project.portal_token, _external=True)
    html = render_template('portal_email.html', project=project, link=link, company=COMPANY)

    msg = MIMEMultipart('alternative')
    msg['To'] = customer.email
    msg['From'] = 'me'
    msg['Subject'] = f"Your project with {COMPANY['name']}: {project.name}"
    msg.attach(MIMEText(html, 'html'))

    gmail = gbuild('gmail', 'v1', credentials=creds)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
    return True, f'Portal link emailed to {customer.email}.'


@portal_bp.route('/projects/<int:project_id>/portal/email', methods=['POST'])
@login_required
def email(project_id):
    project = Project.query.get_or_404(project_id)
    try:
        ok, message = send_portal_email(project)
    except Exception as exc:  # noqa: BLE001
        ok, message = False, f'Email failed: {exc}'
    flash(message, 'success' if ok else 'error')
    return redirect(url_for('project_detail', project_id=project.id))


# ── public: the portal page + job-scoped document PDFs ─────────────────────

@portal_bp.route('/portal/<token>')
@limiter.limit("60 per minute")
def view(token):
    project = _project_by_token(token)
    return render_template('portal.html', project=project, token=token,
                           **_portal_data(project))


def _serve(buf, name):
    return send_file(buf, mimetype='application/pdf', as_attachment=False,
                     download_name=name)


@portal_bp.route('/portal/<token>/proposal/<int:doc_id>')
@limiter.limit("30 per minute")
def proposal_pdf(token, doc_id):
    project = _project_by_token(token)
    q = next((x for x in project.quotes if x.id == doc_id), None) or abort(404)
    return _serve(build_quote_pdf(q), f'proposal-{q.id}.pdf')


@portal_bp.route('/portal/<token>/invoice/<int:doc_id>')
@limiter.limit("30 per minute")
def invoice_pdf(token, doc_id):
    project = _project_by_token(token)
    inv = next((x for x in project.invoices if x.id == doc_id), None) or abort(404)
    return _serve(build_invoice_pdf(inv), f'{inv.number or inv.id}.pdf')


@portal_bp.route('/portal/<token>/contract/<int:doc_id>')
@limiter.limit("30 per minute")
def contract_pdf(token, doc_id):
    project = _project_by_token(token)
    c = next((x for x in project.contracts if x.id == doc_id), None) or abort(404)
    return _serve(build_contract_pdf(c), f'{c.number or c.id}.pdf')


@portal_bp.route('/portal/<token>/document/<int:doc_id>')
@limiter.limit("30 per minute")
def document_pdf(token, doc_id):
    project = _project_by_token(token)
    d = next((x for x in project.gc_documents if x.id == doc_id), None) or abort(404)
    return _serve(build_gc_document_pdf(d), f'{d.doc_kind}-{d.id}.pdf')
