"""Sent-document archive.

When a customer-facing document (invoice, contract, change order) is sent, a
copy of the exact PDF is saved to UPLOAD_FOLDER (a Render Disk in production)
as an immutable record of what was delivered. The three send routes call
`archive_document`; `archived_copies` lists the snapshots for a document (also
exposed to templates as `sent_copies`), and the blueprint serves the files.
"""
import os
import uuid

from flask import Blueprint, send_file, abort, current_app
from flask_login import login_required, current_user

from extensions import db
from models import SentDocumentArchive

archive_bp = Blueprint('archive', __name__, url_prefix='/archive')

DOC_TYPES = ('invoice', 'contract', 'change_order')


def archive_document(user_id, doc_type, doc_id, number, label, pdf_buf):
    """Save a PDF snapshot of a sent document. Caller commits. Never raises on
    a storage hiccup in a way that would block the send — failures are swallowed
    so archiving can't stop a document going out."""
    try:
        folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(folder, exist_ok=True)
        stored = f"sent_{doc_type}_{doc_id}_{uuid.uuid4().hex}.pdf"
        pdf_buf.seek(0)
        with open(os.path.join(folder, stored), 'wb') as fh:
            fh.write(pdf_buf.read())
        db.session.add(SentDocumentArchive(
            user_id=user_id, doc_type=doc_type, doc_id=doc_id,
            number=number, label=label, filename=stored))
    except Exception:
        # Archiving is best-effort; a failure must not break the send.
        pass


def archived_copies(doc_type, doc_id):
    """Snapshots for one document, newest first. Safe to call from templates."""
    try:
        return (SentDocumentArchive.query
                .filter_by(doc_type=doc_type, doc_id=doc_id)
                .order_by(SentDocumentArchive.archived_at.desc()).all())
    except Exception:
        return []


@archive_bp.route('/<int:archive_id>/download')
@login_required
def download(archive_id):
    rec = SentDocumentArchive.query.filter_by(
        id=archive_id, user_id=current_user.id).first_or_404()
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], rec.filename)
    if not os.path.exists(path):
        abort(404)
    stamp = rec.archived_at.strftime('%Y%m%d') if rec.archived_at else rec.id
    nice = f"{rec.number or rec.doc_type}-sent-{stamp}.pdf".replace(' ', '_')
    return send_file(path, mimetype='application/pdf', as_attachment=False,
                     download_name=nice)
