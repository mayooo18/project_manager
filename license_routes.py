"""
Company Licenses & Renewals (Phase 6b — GC admin).

Tracks the company's OWN credentials — electrical/HVAC/GC contractor licenses,
bonds, and insurance policies — and auto-generates renewal Reminders ahead of
each expiration (2 months / 1 month / 2 weeks / 1 week), reusing the same
mechanism as Vehicles and Subcontractors.
"""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import timedelta, date

from extensions import db
from models import License, Reminder
from forms import LicenseForm, DeleteForm

license_bp = Blueprint('licenses', __name__, url_prefix='/licenses')

# Longer lead times than vehicles — license/insurance renewals take paperwork.
REMINDER_OFFSETS = [
    (60, '2 months'),
    (30, '1 month'),
    (14, '2 weeks'),
    (7, '1 week'),
]

EXPIRATION_FIELDS = [
    ('expiration_date', 'Renewal'),
]


def sync_reminders_for_license(lic):
    for field_name, label in EXPIRATION_FIELDS:
        expiration = getattr(lic, field_name)
        for days_before, offset_label in REMINDER_OFFSETS:
            existing = Reminder.query.filter_by(
                license_id=lic.id,
                license_field=field_name,
                license_offset_days=days_before,
            ).first()

            if not expiration:
                if existing:
                    db.session.delete(existing)
                continue

            due_date = expiration - timedelta(days=days_before)
            text = f"{lic.name} ({label}) is due in {offset_label}"
            if existing:
                existing.due_date = due_date
                existing.text = text
            else:
                db.session.add(Reminder(
                    user_id=current_user.id,
                    text=text,
                    due_date=due_date,
                    license_id=lic.id,
                    license_field=field_name,
                    license_offset_days=days_before,
                ))


@license_bp.route('/')
@login_required
def index():
    # Postgres sorts NULLs last on ASC by default, so undated licenses fall to the bottom.
    licenses = (License.query.filter_by(user_id=current_user.id)
                .order_by(License.expiration_date.asc()).all())
    return render_template('licenses.html', licenses=licenses,
                           delete_form=DeleteForm(),
                           today=date.today(), timedelta=timedelta)


@license_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    form = LicenseForm()
    if form.validate_on_submit():
        lic = License(user_id=current_user.id)
        form.populate_obj(lic)
        db.session.add(lic)
        db.session.flush()
        sync_reminders_for_license(lic)
        db.session.commit()
        flash('License added.', 'success')
        return redirect(url_for('licenses.index'))
    return render_template('license_form.html', form=form, title='Add License')


@license_bp.route('/<int:license_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(license_id):
    lic = License.query.get_or_404(license_id)
    if lic.user_id != current_user.id:
        flash('Unauthorized.', 'error')
        return redirect(url_for('licenses.index'))

    form = LicenseForm(obj=lic)
    if form.validate_on_submit():
        form.populate_obj(lic)
        sync_reminders_for_license(lic)
        db.session.commit()
        flash('License updated.', 'success')
        return redirect(url_for('licenses.index'))

    return render_template('license_form.html', form=form, title='Edit License')


@license_bp.route('/<int:license_id>/delete', methods=['POST'])
@login_required
def delete(license_id):
    lic = License.query.get_or_404(license_id)
    if lic.user_id != current_user.id:
        flash('Unauthorized.', 'error')
        return redirect(url_for('licenses.index'))

    db.session.delete(lic)
    db.session.commit()
    flash('License deleted.', 'success')
    return redirect(url_for('licenses.index'))
