"""
Subcontractor directory (Phase 6a — GC admin).

Self-contained Blueprint mirroring the Vehicles feature: a per-user directory
of subcontractors with license & insurance expirations that auto-generate
Reminders (1 month / 2 weeks / 1 week / 1 day before), so a lapsed sub license
or COI never slips past you.
"""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import timedelta, date

from extensions import db
from models import Subcontractor, Reminder
from forms import SubcontractorForm, DeleteForm

subcontractor_bp = Blueprint('subcontractors', __name__, url_prefix='/subcontractors')

REMINDER_OFFSETS = [
    (30, '1 month'),
    (14, '2 weeks'),
    (7, '1 week'),
    (1, '1 day'),
]

EXPIRATION_FIELDS = [
    ('license_expiration', 'License'),
    ('insurance_expiration', 'Insurance (COI)'),
]


def sync_reminders_for_subcontractor(sub):
    for field_name, label in EXPIRATION_FIELDS:
        expiration = getattr(sub, field_name)
        for days_before, offset_label in REMINDER_OFFSETS:
            existing = Reminder.query.filter_by(
                subcontractor_id=sub.id,
                subcontractor_field=field_name,
                subcontractor_offset_days=days_before,
            ).first()

            if not expiration:
                if existing:
                    db.session.delete(existing)
                continue

            due_date = expiration - timedelta(days=days_before)
            text = f"{label} expires for {sub.name} in {offset_label}"
            if existing:
                existing.due_date = due_date
                existing.text = text
            else:
                db.session.add(Reminder(
                    user_id=current_user.id,
                    text=text,
                    due_date=due_date,
                    subcontractor_id=sub.id,
                    subcontractor_field=field_name,
                    subcontractor_offset_days=days_before,
                ))


@subcontractor_bp.route('/')
@login_required
def index():
    subs = (Subcontractor.query.filter_by(user_id=current_user.id)
            .order_by(Subcontractor.name.asc()).all())
    return render_template('subcontractors.html', subcontractors=subs,
                           delete_form=DeleteForm(),
                           today=date.today(), timedelta=timedelta)


@subcontractor_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    form = SubcontractorForm()
    if form.validate_on_submit():
        sub = Subcontractor(user_id=current_user.id)
        form.populate_obj(sub)
        db.session.add(sub)
        db.session.flush()
        sync_reminders_for_subcontractor(sub)
        db.session.commit()
        flash('Subcontractor added.', 'success')
        return redirect(url_for('subcontractors.index'))
    return render_template('subcontractor_form.html', form=form, title='Add Subcontractor')


@subcontractor_bp.route('/<int:sub_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(sub_id):
    sub = Subcontractor.query.get_or_404(sub_id)
    if sub.user_id != current_user.id:
        flash('Unauthorized.', 'error')
        return redirect(url_for('subcontractors.index'))

    form = SubcontractorForm(obj=sub)
    if form.validate_on_submit():
        form.populate_obj(sub)
        sync_reminders_for_subcontractor(sub)
        db.session.commit()
        flash('Subcontractor updated.', 'success')
        return redirect(url_for('subcontractors.index'))

    return render_template('subcontractor_form.html', form=form, title='Edit Subcontractor')


@subcontractor_bp.route('/<int:sub_id>/delete', methods=['POST'])
@login_required
def delete(sub_id):
    sub = Subcontractor.query.get_or_404(sub_id)
    if sub.user_id != current_user.id:
        flash('Unauthorized.', 'error')
        return redirect(url_for('subcontractors.index'))

    db.session.delete(sub)
    db.session.commit()
    flash('Subcontractor deleted.', 'success')
    return redirect(url_for('subcontractors.index'))
