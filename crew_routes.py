"""
Crew portal (Phase 8 §1) — workers sign in with phone + PIN, no account.

Deliberately separate from the office login (Flask-Login / User): a worker is a
Worker record, authenticated by phone + PIN into its own session key. Nothing
sensitive lives here — only the worker's own tasks and time (added in §2/§3).
"""

from functools import wraps

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, session, g, abort,
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


def _open_punch(worker):
    from models import TimePunch
    return TimePunch.query.filter_by(worker_id=worker.id, clock_out=None).first()


def _my_jobs(worker):
    seen, jobs = set(), []
    for t in worker.tasks:
        p = t.project
        if p and p.id not in seen and p.status != 'Completed':
            seen.add(p.id)
            jobs.append(p)
    return jobs


@crew_bp.route('/home')
@crew_login_required
def home():
    from datetime import date
    worker = g.crew_worker
    tasks = sorted(worker.tasks,
                   key=lambda t: (t.status == 'done', t.due_date or date.max, -t.id))
    return render_template('crew_home.html', worker=worker, tasks=tasks,
                           open_punch=_open_punch(worker), my_jobs=_my_jobs(worker))


@crew_bp.route('/clock-in', methods=['POST'])
@crew_login_required
def clock_in():
    from models import TimePunch
    worker = g.crew_worker
    if _open_punch(worker):
        flash('You are already clocked in. Clock out first.', 'error')
        return redirect(url_for('crew.home'))
    project_id = request.form.get('project_id', type=int)
    allowed = {p.id for p in _my_jobs(worker)}
    if not project_id or project_id not in allowed:
        flash('Pick one of your jobs to clock into.', 'error')
        return redirect(url_for('crew.home'))
    db.session.add(TimePunch(worker_id=worker.id, project_id=project_id))
    db.session.commit()
    flash('Clocked in.')
    return redirect(url_for('crew.home'))


@crew_bp.route('/clock-out', methods=['POST'])
@crew_login_required
def clock_out():
    from datetime import datetime
    punch = _open_punch(g.crew_worker)
    if not punch:
        flash('You are not clocked in.', 'error')
        return redirect(url_for('crew.home'))
    punch.clock_out = datetime.utcnow()
    db.session.commit()
    flash(f'Clocked out — {punch.hours} h.')
    return redirect(url_for('crew.home'))


@crew_bp.route('/tasks/<int:task_id>/status', methods=['POST'])
@crew_login_required
def task_status(task_id):
    from datetime import datetime
    from models import Task
    task = Task.query.get_or_404(task_id)
    if task.worker_id != g.crew_worker.id:   # a worker can only touch their own tasks
        abort(403)
    new_status = request.form.get('status')
    if new_status in ('assigned', 'in_progress', 'done'):
        task.status = new_status
        task.completed_at = datetime.utcnow() if new_status == 'done' else None
    db.session.commit()
    return redirect(url_for('crew.home'))


@crew_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    session.pop(SESSION_KEY, None)
    return redirect(url_for('crew.login'))
