# activity_routes.py
# Owner + Admin view of the office activity log (see activity_log.py for how
# entries are recorded). Read-only: this blueprint never writes to the table.
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from activity_log import ActivityLog
from models import User

activity_bp = Blueprint('activity', __name__)

PAGE_SIZE = 100


@activity_bp.route('/activity')
@login_required
def index():
    # Both office roles may view (owner + admin/foreman). Crew/workers never
    # reach here — they authenticate through a different login.
    if getattr(current_user, 'role', None) not in ('owner', 'admin'):
        from flask import redirect, url_for, flash
        flash('That page is for office staff only.', 'error')
        return redirect(url_for('home'))

    query = ActivityLog.query

    # Filter: by user
    user_id = request.args.get('user_id', type=int)
    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)

    # Filter: by date range (inclusive). Dates are parsed leniently.
    start_raw = request.args.get('start')
    end_raw = request.args.get('end')
    start_date = end_date = None
    if start_raw:
        try:
            start_date = datetime.strptime(start_raw, '%Y-%m-%d')
            query = query.filter(ActivityLog.created_at >= start_date)
        except ValueError:
            pass
    if end_raw:
        try:
            end_date = datetime.strptime(end_raw, '%Y-%m-%d')
            # inclusive end-of-day
            query = query.filter(ActivityLog.created_at < end_date + timedelta(days=1))
        except ValueError:
            pass

    page = max(request.args.get('page', 1, type=int) or 1, 1)
    entries = (query.order_by(ActivityLog.created_at.desc())
               .paginate(page=page, per_page=PAGE_SIZE, error_out=False))

    users = User.query.order_by(User.username.asc()).all()

    return render_template(
        'activity_log.html',
        entries=entries.items,
        pagination=entries,
        users=users,
        sel_user_id=user_id,
        start=start_raw or '',
        end=end_raw or '',
    )
