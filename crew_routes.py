"""
Crew portal (Phase 8 §1) — workers sign in with phone + PIN, no account.

Deliberately separate from the office login (Flask-Login / User): a worker is a
Worker record, authenticated by phone + PIN into its own session key. Nothing
sensitive lives here — only the worker's own tasks and time (added in §2/§3).
"""

from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, session, g,
)

from extensions import db, limiter
from models import Worker

crew_bp = Blueprint('crew', __name__, url_prefix='/crew')

SESSION_KEY = 'crew_worker_id'


def current_crew_worker():
    wid = session.get(SESSION_KEY)
    if not wid:
        return None
    return Worker.query.get(wid)


def crew_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        worker = current_crew_worker()
        if worker is None or not worker.active:
            session.pop(SESSION_KEY, None)
            return redirect(url_for('crew.login'))
        g.crew_worker = worker
        return view(*args, **kwargs)
    return wrapped


@crew_bp.route('/', methods=['GET'])
def index():
    if current_crew_worker():
        return redirect(url_for('crew.home'))
    return redirect(url_for('crew.login'))


@crew_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def login():
    if request.method == 'POST':
        phone = Worker.normalize_phone(request.form.get('phone'))
        pin = (request.form.get('pin') or '').strip()
        worker = None
        if phone:
            # Match on normalized digits so formatting doesn't matter.
            for w in Worker.query.filter_by(active=True).all():
                if Worker.normalize_phone(w.phone) == phone:
                    worker = w
                    break
        if worker and worker.check_pin(pin):
            session[SESSION_KEY] = worker.id
            return redirect(url_for('crew.home'))
        flash('Phone number or PIN is incorrect.', 'error')
    return render_template('crew_login.html')


@crew_bp.route('/home')
@crew_login_required
def home():
    return render_template('crew_home.html', worker=g.crew_worker)


@crew_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    session.pop(SESSION_KEY, None)
    return redirect(url_for('crew.login'))
