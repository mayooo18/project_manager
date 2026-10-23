"""Milestone evidence attachments (F5).

Upload photos, concrete tickets, inspection reports and test results to a
contract draw. Files are saved under UPLOAD_FOLDER (a Render Disk in
production) and served back through a login-protected download route.
"""
import os
import uuid

from flask import (
    Blueprint, request, redirect, url_for, flash, abort, send_file,
    current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from extensions import db
from models import ContractDraw, MilestoneEvidence

evidence_bp = Blueprint('evidence', __name__, url_prefix='/evidence')

# Same allow-list the rest of the app uses for uploads.
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'heic',
                      'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt'}
EVIDENCE_KINDS = [
    ('photo', 'Photo'),
    ('concrete_ticket', 'Concrete ticket'),
    ('inspection_report', 'Inspection report'),
    ('test_result', 'Test result'),
    ('other', 'Other'),
]
_VALID_KINDS = {k for k, _ in EVIDENCE_KINDS}


def _owned_draw_or_404(draw_id):
    draw = ContractDraw.query.get_or_404(draw_id)
    if draw.contract is None or draw.contract.user_id != current_user.id:
        abort(404)
    return draw


def _save(file_storage):
    """Validate the extension and save with a random name. Returns (stored,
    original) or (None, None) if the type isn't allowed."""
    original = secure_filename(file_storage.filename or '')
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if ext not in ALLOWED_EXTENSIONS:
        return None, None
    folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    stored = f"evidence_{uuid.uuid4().hex}_{original}"
    file_storage.save(os.path.join(folder, stored))
    return stored, original


@evidence_bp.route('/draw/<int:draw_id>/upload', methods=['POST'])
@login_required
def upload(draw_id):
    draw = _owned_draw_or_404(draw_id)
    file_storage = request.files.get('file')
    if not file_storage or not file_storage.filename:
        flash('Choose a file to attach.', 'error')
        return redirect(url_for('contracts.edit', contract_id=draw.contract_id))

    stored, original = _save(file_storage)
    if stored is None:
        flash('That file type is not allowed. Use a PDF, image, or document.', 'error')
        return redirect(url_for('contracts.edit', contract_id=draw.contract_id))

    kind = request.form.get('kind', 'photo')
    if kind not in _VALID_KINDS:
        kind = 'other'
    db.session.add(MilestoneEvidence(
        user_id=current_user.id, draw_id=draw.id, kind=kind,
        filename=stored, original_name=original,
        note=(request.form.get('note') or '').strip() or None))
    db.session.commit()
    flash('Evidence attached.', 'success')
    return redirect(url_for('contracts.edit', contract_id=draw.contract_id))


@evidence_bp.route('/<int:evidence_id>/download')
@login_required
def download(evidence_id):
    ev = MilestoneEvidence.query.filter_by(
        id=evidence_id, user_id=current_user.id).first_or_404()
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], ev.filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=False,
                     download_name=ev.original_name or ev.filename)


@evidence_bp.route('/<int:evidence_id>/delete', methods=['POST'])
@login_required
def delete(evidence_id):
    ev = MilestoneEvidence.query.filter_by(
        id=evidence_id, user_id=current_user.id).first_or_404()
    contract_id = ev.draw.contract_id if ev.draw else None
    # Best-effort file removal; the row goes regardless.
    try:
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], ev.filename)
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    db.session.delete(ev)
    db.session.commit()
    flash('Evidence removed.', 'success')
    if contract_id:
        return redirect(url_for('contracts.edit', contract_id=contract_id))
    return redirect(url_for('contracts.index'))
