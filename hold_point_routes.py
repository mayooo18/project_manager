"""Hold-point checklist (F7).

Six sequential inspection gates per property (before excavation, footings,
walls, backfill, slab, framing release). A gate can be passed only once every
earlier gate has passed. Each gate can link to an existing Inspection for the
official result (the Permits & Inspections module stays the source of truth).
Opt-in: only jobs on a contract with hold points enabled use this.
"""
import os
import uuid

from flask import (
    Blueprint, request, redirect, url_for, flash, abort, send_file, current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from extensions import db
from models import (
    HoldPoint, HoldPointPhoto, Project, Inspection, HOLD_POINT_GATES,
)
from permissions import owner_required

hold_point_bp = Blueprint('hold_points', __name__, url_prefix='/hold-points')

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'heic'}


def _owned_hold_point_or_404(hold_point_id):
    return HoldPoint.query.filter_by(
        id=hold_point_id, user_id=current_user.id).first_or_404()


def _save_file(file_storage):
    original = secure_filename(file_storage.filename or '')
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if ext not in ALLOWED_EXTENSIONS:
        return None, None
    folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    stored = f"holdpoint_{uuid.uuid4().hex}_{original}"
    file_storage.save(os.path.join(folder, stored))
    return stored, original


# ── setup (seed the six gates) ───────────────────────────────────────────────

@hold_point_bp.route('/job/<int:project_id>/setup', methods=['POST'])
@login_required
def setup(project_id):
    project = Project.query.get_or_404(project_id)
    if project.hold_points:
        flash('Hold points are already set up for this job.', 'error')
        return redirect(url_for('project_detail', project_id=project.id))
    for i, name in enumerate(HOLD_POINT_GATES):
        db.session.add(HoldPoint(user_id=current_user.id, project_id=project.id,
                                 sequence=i, name=name, status='open'))
    db.session.commit()
    flash('Hold-point checklist created.', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


# ── edit a gate (required items / notes / linked inspection) ──────────────────

@hold_point_bp.route('/<int:hold_point_id>/update', methods=['POST'])
@login_required
def update(hold_point_id):
    hp = _owned_hold_point_or_404(hold_point_id)
    hp.required_items = (request.form.get('required_items') or '').strip() or None
    hp.notes = (request.form.get('notes') or '').strip() or None
    insp_id = request.form.get('inspection_id', type=int)
    # Only accept an inspection that belongs to this job.
    hp.inspection_id = None
    if insp_id:
        insp = Inspection.query.get(insp_id)
        if insp and insp.permit and insp.permit.project_id == hp.project_id:
            hp.inspection_id = insp_id
    db.session.commit()
    flash('Hold point updated.', 'success')
    return redirect(url_for('project_detail', project_id=hp.project_id))


# ── pass / reopen ────────────────────────────────────────────────────────────

@hold_point_bp.route('/<int:hold_point_id>/pass', methods=['POST'])
@login_required
def pass_gate(hold_point_id):
    hp = _owned_hold_point_or_404(hold_point_id)
    if not hp.is_unlocked:
        flash('An earlier hold point must pass before this one can.', 'error')
        return redirect(url_for('project_detail', project_id=hp.project_id))
    from datetime import datetime
    hp.status = 'passed'
    hp.approved_by = (request.form.get('approved_by') or '').strip() or current_user.username
    hp.approved_at = datetime.utcnow()
    db.session.commit()
    flash(f'{hp.name} marked passed.', 'success')
    return redirect(url_for('project_detail', project_id=hp.project_id))


@hold_point_bp.route('/<int:hold_point_id>/reopen', methods=['POST'])
@login_required
@owner_required
def reopen(hold_point_id):
    hp = _owned_hold_point_or_404(hold_point_id)
    # Reopening a gate also reopens every later gate, so the sequence stays valid.
    for g in hp.project.hold_points:
        if g.sequence >= hp.sequence:
            g.status = 'open'
            g.approved_by = None
            g.approved_at = None
    db.session.commit()
    flash(f'{hp.name} and later gates reopened.', 'success')
    return redirect(url_for('project_detail', project_id=hp.project_id))


# ── photos ───────────────────────────────────────────────────────────────────

@hold_point_bp.route('/<int:hold_point_id>/photos/upload', methods=['POST'])
@login_required
def upload_photo(hold_point_id):
    hp = _owned_hold_point_or_404(hold_point_id)
    file_storage = request.files.get('file')
    if not file_storage or not file_storage.filename:
        flash('Choose a file to attach.', 'error')
        return redirect(url_for('project_detail', project_id=hp.project_id))
    stored, original = _save_file(file_storage)
    if stored is None:
        flash('That file type is not allowed (use a PDF or image).', 'error')
        return redirect(url_for('project_detail', project_id=hp.project_id))
    db.session.add(HoldPointPhoto(
        hold_point_id=hp.id, filename=stored, original_name=original,
        caption=(request.form.get('caption') or '').strip() or None))
    db.session.commit()
    flash('Photo attached.', 'success')
    return redirect(url_for('project_detail', project_id=hp.project_id))


@hold_point_bp.route('/photos/<int:photo_id>/download')
@login_required
def download_photo(photo_id):
    photo = HoldPointPhoto.query.get_or_404(photo_id)
    hp = photo.hold_point
    if hp is None or hp.user_id != current_user.id:
        abort(404)
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], photo.filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=False,
                     download_name=photo.original_name or photo.filename)


@hold_point_bp.route('/photos/<int:photo_id>/delete', methods=['POST'])
@login_required
def delete_photo(photo_id):
    photo = HoldPointPhoto.query.get_or_404(photo_id)
    hp = photo.hold_point
    if hp is None or hp.user_id != current_user.id:
        abort(404)
    project_id = hp.project_id
    try:
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], photo.filename)
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    db.session.delete(photo)
    db.session.commit()
    flash('Photo removed.', 'success')
    return redirect(url_for('project_detail', project_id=project_id))
