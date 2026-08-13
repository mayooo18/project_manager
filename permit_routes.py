"""
Permits & Inspections (Phase 6c — GC admin).

Per-project permit tracking (type, number, authority, dates, status) with the
inspections under each permit. Reuses the auto-reminder mechanism:
  - permit expiration reminders at 30 / 14 / 7 days (while the permit is open),
  - inspection reminders at 3 / 1 days before a scheduled inspection.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from datetime import timedelta, date

from extensions import db
from models import Permit, Inspection, Project, Reminder
from forms import PermitForm, InspectionForm, DeleteForm

permit_bp = Blueprint('permits', __name__, url_prefix='/permits')

PERMIT_OFFSETS = [(30, '1 month'), (14, '2 weeks'), (7, '1 week')]
INSPECTION_OFFSETS = [(3, '3 days'), (1, '1 day')]
PERMIT_DONE = {'Closed', 'Finaled', 'Expired'}


# ── reminder sync ──────────────────────────────────────────────────────────

def sync_reminders_for_permit(permit):
    # Only nag about expiration while the permit is still open.
    active = permit.expiration_date and permit.status not in PERMIT_DONE
    for days_before, offset_label in PERMIT_OFFSETS:
        existing = Reminder.query.filter_by(
            permit_id=permit.id, permit_field='expiration_date',
            permit_offset_days=days_before).first()
        if not active:
            if existing:
                db.session.delete(existing)
            continue
        due_date = permit.expiration_date - timedelta(days=days_before)
        label = f"{permit.permit_type or 'Permit'} {permit.permit_number or ''}".strip()
        text = f"Permit expires ({label}) in {offset_label}"
        if existing:
            existing.due_date = due_date
            existing.text = text
        else:
            db.session.add(Reminder(
                user_id=current_user.id, text=text, due_date=due_date,
                permit_id=permit.id, permit_field='expiration_date',
                permit_offset_days=days_before))


def sync_reminders_for_inspection(inspection):
    # Only remind for inspections that are still scheduled.
    active = inspection.scheduled_date and inspection.status == 'Scheduled'
    for days_before, offset_label in INSPECTION_OFFSETS:
        existing = Reminder.query.filter_by(
            inspection_id=inspection.id, inspection_field='scheduled_date',
            inspection_offset_days=days_before).first()
        if not active:
            if existing:
                db.session.delete(existing)
            continue
        due_date = inspection.scheduled_date - timedelta(days=days_before)
        text = f"{inspection.inspection_type} inspection in {offset_label}"
        if existing:
            existing.due_date = due_date
            existing.text = text
        else:
            db.session.add(Reminder(
                user_id=current_user.id, text=text, due_date=due_date,
                inspection_id=inspection.id, inspection_field='scheduled_date',
                inspection_offset_days=days_before))


# ── helpers ────────────────────────────────────────────────────────────────

def _owned_permit_or_404(permit_id):
    return Permit.query.filter_by(id=permit_id, user_id=current_user.id).first_or_404()


def _project_choices():
    projects = Project.query.order_by(Project.name.asc()).all()
    return [(0, '— None —')] + [(p.id, p.name) for p in projects]


# ── permit list / CRUD ─────────────────────────────────────────────────────

@permit_bp.route('/')
@login_required
def index():
    permits = (Permit.query.filter_by(user_id=current_user.id)
               .order_by(Permit.created_at.desc()).all())
    return render_template('permits.html', permits=permits,
                           delete_form=DeleteForm(),
                           today=date.today(), timedelta=timedelta)


@permit_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    form = PermitForm()
    form.project_id.choices = _project_choices()
    if form.validate_on_submit():
        permit = Permit(user_id=current_user.id)
        form.populate_obj(permit)
        permit.project_id = form.project_id.data or None
        db.session.add(permit)
        db.session.flush()
        sync_reminders_for_permit(permit)
        db.session.commit()
        flash('Permit added.', 'success')
        return redirect(url_for('permits.edit', permit_id=permit.id))
    return render_template('permit_form.html', form=form, permit=None,
                           inspection_form=InspectionForm())


@permit_bp.route('/<int:permit_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(permit_id):
    permit = _owned_permit_or_404(permit_id)
    form = PermitForm(obj=permit)
    form.project_id.choices = _project_choices()
    if request.method == 'GET':
        form.project_id.data = permit.project_id or 0
    if form.validate_on_submit():
        form.populate_obj(permit)
        permit.project_id = form.project_id.data or None
        sync_reminders_for_permit(permit)
        db.session.commit()
        flash('Permit updated.', 'success')
        return redirect(url_for('permits.edit', permit_id=permit.id))
    return render_template('permit_form.html', form=form, permit=permit,
                           inspection_form=InspectionForm())


@permit_bp.route('/<int:permit_id>/delete', methods=['POST'])
@login_required
def delete(permit_id):
    permit = _owned_permit_or_404(permit_id)
    db.session.delete(permit)
    db.session.commit()
    flash('Permit deleted.', 'success')
    return redirect(url_for('permits.index'))


# ── inspections (nested under a permit) ─────────────────────────────────────

@permit_bp.route('/<int:permit_id>/inspections/add', methods=['POST'])
@login_required
def add_inspection(permit_id):
    permit = _owned_permit_or_404(permit_id)
    form = InspectionForm()
    if form.validate_on_submit():
        inspection = Inspection(permit_id=permit.id)
        form.populate_obj(inspection)
        db.session.add(inspection)
        db.session.flush()
        sync_reminders_for_inspection(inspection)
        db.session.commit()
        flash('Inspection added.', 'success')
    else:
        flash('Inspection needs at least a type.', 'error')
    return redirect(url_for('permits.edit', permit_id=permit.id))


@permit_bp.route('/inspections/<int:inspection_id>/update', methods=['POST'])
@login_required
def update_inspection(inspection_id):
    inspection = Inspection.query.get_or_404(inspection_id)
    if inspection.permit.user_id != current_user.id:
        flash('Unauthorized.', 'error')
        return redirect(url_for('permits.index'))
    status = (request.form.get('status') or '').strip()
    if status in ('Scheduled', 'Passed', 'Failed', 'Cancelled'):
        inspection.status = status
    inspection.result_notes = (request.form.get('result_notes') or '').strip() or None
    sync_reminders_for_inspection(inspection)
    db.session.commit()
    flash('Inspection updated.', 'success')
    return redirect(url_for('permits.edit', permit_id=inspection.permit_id))


@permit_bp.route('/inspections/<int:inspection_id>/delete', methods=['POST'])
@login_required
def delete_inspection(inspection_id):
    inspection = Inspection.query.get_or_404(inspection_id)
    if inspection.permit.user_id != current_user.id:
        flash('Unauthorized.', 'error')
        return redirect(url_for('permits.index'))
    permit_id = inspection.permit_id
    db.session.delete(inspection)
    db.session.commit()
    flash('Inspection deleted.', 'success')
    return redirect(url_for('permits.edit', permit_id=permit_id))
