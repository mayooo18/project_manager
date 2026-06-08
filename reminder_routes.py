from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import Reminder
from datetime import datetime

reminder_bp = Blueprint('reminders', __name__, url_prefix='/reminders')


@reminder_bp.route('/')
@login_required
def index():
    active = Reminder.query.filter_by(user_id=current_user.id, is_done=False)\
        .order_by(Reminder.due_date.asc().nullslast(), Reminder.created_at.desc()).all()
    done = Reminder.query.filter_by(user_id=current_user.id, is_done=True)\
        .order_by(Reminder.created_at.desc()).limit(20).all()
    return render_template('reminders.html', active=active, done=done, now=datetime.utcnow())


@reminder_bp.route('/<int:reminder_id>/done', methods=['POST'])
@login_required
def mark_done(reminder_id):
    r = Reminder.query.get_or_404(reminder_id)
    if r.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    r.is_done = True
    db.session.commit()
    return jsonify({'success': True})


@reminder_bp.route('/<int:reminder_id>', methods=['DELETE'])
@login_required
def delete(reminder_id):
    r = Reminder.query.get_or_404(reminder_id)
    if r.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(r)
    db.session.commit()
    return jsonify({'success': True})
