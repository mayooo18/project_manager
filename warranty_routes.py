"""Warranty tracker (F13).

A warranty window per property (default 1 year from closeout acceptance),
warranty-call logging with photos, and a reminder before expiration.
"""
import os
import uuid
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta
from flask import (
    Blueprint, request, redirect, url_for, flash, abort, send_file, current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from extensions import db
from models import Project, WarrantyCall, WarrantyCallPhoto, Reminder

warranty_bp = Blueprint('warranty', __name__, url_prefix='/warranty')

REMINDER_LEAD_DAYS = 30
_PHOTO_EXTS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'heic'}


def _owned_project_or_404(project_id):
    project = Project.query.get_or_404(project_id)
    ok = (project.customer and project.customer.user_id == current_user.id) or \
         any(c.user_id == current_user.id for c in project.contracts)
    if not ok:
        abort(404)
    return project


def _owned_call_or_404(call_id):
    call = WarrantyCall.query.get_or_404(call_id)
    _owned_project_or_404(call.project_id)
    return call


def _parse_date(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return None


def _sync_warranty_reminder(project):
    """Create/refresh the 'warranty expiring' reminder for this project."""
    text = f"Warranty expiring — {project.name}"
    Reminder.query.filter_by(user_id=current_user.id, text=text).delete()
    if project.warranty_end:
        due = project.warranty_end - timedelta(days=REMINDER_LEAD_DAYS)
        db.session.add(Reminder(user_id=current_user.id, text=text, due_date=due))


# ── set the warranty window ──────────────────────────────────────────────────

@warranty_bp.route('/job/<int:project_id>/start', methods=['POST'])
@login_required
def start(project_id):
    project = _owned_project_or_404(project_id)
    start_date = (project.closeout_accepted_at.date()
                  if project.closeout_accepted_at else date.today())
    project.warranty_start = start_date
    project.warranty_end = start_date + relativedelta(years=1)
    _sync_warranty_reminder(project)
    db.session.commit()
    flash('1-year warranty started.', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


@warranty_bp.route('/job/<int:project_id>/set', methods=['POST'])
@login_required
def set_period(project_id):
    project = _owned_project_or_404(project_id)
    project.warranty_start = _parse_date(request.form.get('warranty_start'))
    project.warranty_end = _parse_date(request.form.get('warranty_end'))
    _sync_warranty_reminder(project)
    db.session.commit()
    flash('Warranty period updated.', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


# ── warranty calls ───────────────────────────────────────────────────────────

@warranty_bp.route('/job/<int:project_id>/call/add', methods=['POST'])
@login_required
def add_call(project_id):
    project = _owned_project_or_404(project_id)
    issue = (request.form.get('issue') or '').strip()
    if not issue:
        flash('Describe the warranty issue.', 'error')
        return redirect(url_for('project_detail', project_id=project.id))
    db.session.add(WarrantyCall(
        project_id=project.id, issue=issue, status='open',
        call_date=_parse_date(request.form.get('call_date')) or date.today()))
    db.session.commit()
    flash('Warranty call logged.', 'success')
    return redirect(url_for('project_detail', project_id=project.id))


@warranty_bp.route('/call/<int:call_id>/resolve', methods=['POST'])
@login_required
def resolve_call(call_id):
    call = _owned_call_or_404(call_id)
    resolution = (request.form.get('resolution') or '').strip()
    if call.status == 'resolved':
        call.status = 'open'
    else:
        call.status = 'resolved'
        if resolution:
            call.resolution = resolution
    db.session.commit()
    return redirect(url_for('project_detail', project_id=call.project_id))


@warranty_bp.route('/call/<int:call_id>/delete', methods=['POST'])
@login_required
def delete_call(call_id):
    call = _owned_call_or_404(call_id)
    pid = call.project_id
    db.session.delete(call)
    db.session.commit()
    return redirect(url_for('project_detail', project_id=pid))


# ── call photos ──────────────────────────────────────────────────────────────

@warranty_bp.route('/call/<int:call_id>/photos/upload', methods=['POST'])
@login_required
def upload_photo(call_id):
    call = _owned_call_or_404(call_id)
    fs = request.files.get('file')
    if not fs or not fs.filename:
        flash('Choose a file to attach.', 'error')
        return redirect(url_for('project_detail', project_id=call.project_id))
    original = secure_filename(fs.filename)
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if ext not in _PHOTO_EXTS:
        flash('That file type is not allowed (use a PDF or image).', 'error')
        return redirect(url_for('project_detail', project_id=call.project_id))
    folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    stored = f"warranty_{uuid.uuid4().hex}_{original}"
    fs.save(os.path.join(folder, stored))
    db.session.add(WarrantyCallPhoto(
        warranty_call_id=call.id, filename=stored, original_name=original))
    db.session.commit()
    flash('Photo attached.', 'success')
    return redirect(url_for('project_detail', project_id=call.project_id))


@warranty_bp.route('/photos/<int:photo_id>/download')
@login_required
def download_photo(photo_id):
    photo = WarrantyCallPhoto.query.get_or_404(photo_id)
    call = photo.call
    if call is None:
        abort(404)
    _owned_project_or_404(call.project_id)
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], photo.filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=False,
                     download_name=photo.original_name or photo.filename)


@warranty_bp.route('/photos/<int:photo_id>/delete', methods=['POST'])
@login_required
def delete_photo(photo_id):
    photo = WarrantyCallPhoto.query.get_or_404(photo_id)
    call = photo.call
    if call is None:
        abort(404)
    project_id = _owned_project_or_404(call.project_id).id
    try:
        path = os.path.join(current_app.config['UPLOAD_FOLDER'], photo.filename)
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    db.session.delete(photo)
    db.session.commit()
    return redirect(url_for('project_detail', project_id=project_id))
