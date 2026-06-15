from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db
from models import Vehicle, Reminder
from forms import VehicleForm, DeleteForm
from datetime import timedelta, date

vehicle_bp = Blueprint('vehicles', __name__, url_prefix='/vehicles')

REMINDER_OFFSETS = [
    (30, '1 month'),
    (14, '2 weeks'),
    (7, '1 week'),
    (1, '1 day'),
]

EXPIRATION_FIELDS = [
    ('plate_expiration', 'Plate'),
    ('registration_expiration', 'Registration (tags)'),
    ('insurance_expiration', 'Insurance'),
]


def sync_reminders_for_vehicle(vehicle):
    for field_name, label in EXPIRATION_FIELDS:
        expiration = getattr(vehicle, field_name)
        for days_before, offset_label in REMINDER_OFFSETS:
            existing = Reminder.query.filter_by(
                vehicle_id=vehicle.id,
                vehicle_field=field_name,
                vehicle_offset_days=days_before,
            ).first()

            if not expiration:
                if existing:
                    db.session.delete(existing)
                continue

            due_date = expiration - timedelta(days=days_before)
            text = f"{label} expires for {vehicle.name} in {offset_label}"
            if existing:
                existing.due_date = due_date
                existing.text = text
            else:
                db.session.add(Reminder(
                    user_id=current_user.id,
                    text=text,
                    due_date=due_date,
                    vehicle_id=vehicle.id,
                    vehicle_field=field_name,
                    vehicle_offset_days=days_before,
                ))


@vehicle_bp.route('/')
@login_required
def index():
    vehicles = Vehicle.query.filter_by(user_id=current_user.id).order_by(Vehicle.name.asc()).all()
    delete_form = DeleteForm()
    return render_template('vehicles.html', vehicles=vehicles, delete_form=delete_form,
                            today=date.today(), timedelta=timedelta)


@vehicle_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    form = VehicleForm()
    if form.validate_on_submit():
        vehicle = Vehicle(user_id=current_user.id)
        form.populate_obj(vehicle)
        db.session.add(vehicle)
        db.session.flush()
        sync_reminders_for_vehicle(vehicle)
        db.session.commit()
        flash('Vehicle added.', 'success')
        return redirect(url_for('vehicles.index'))
    return render_template('vehicle_form.html', form=form, title='Add Vehicle')


@vehicle_bp.route('/<int:vehicle_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if vehicle.user_id != current_user.id:
        flash('Unauthorized.', 'error')
        return redirect(url_for('vehicles.index'))

    form = VehicleForm(obj=vehicle)
    if form.validate_on_submit():
        form.populate_obj(vehicle)
        sync_reminders_for_vehicle(vehicle)
        db.session.commit()
        flash('Vehicle updated.', 'success')
        return redirect(url_for('vehicles.index'))

    return render_template('vehicle_form.html', form=form, title='Edit Vehicle')


@vehicle_bp.route('/<int:vehicle_id>/delete', methods=['POST'])
@login_required
def delete(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if vehicle.user_id != current_user.id:
        flash('Unauthorized.', 'error')
        return redirect(url_for('vehicles.index'))

    db.session.delete(vehicle)
    db.session.commit()
    flash('Vehicle deleted.', 'success')
    return redirect(url_for('vehicles.index'))
