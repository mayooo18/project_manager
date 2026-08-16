# payroll_routes.py
# End-of-week payroll: what each worker is owed for a Mon–Sun pay week.
# Pulls from two labor sources that don't overlap:
#   1. Crew time punches (clock-in/out) — hours x (daily_rate / 8)
#   2. Manual work logs — days_worked x daily_rate  (fallback for non-clocking crew)
# Shows an approved-vs-pending split so the owner sees what's firm.
from datetime import datetime, date, time, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required

from models import Worker, WorkLog, TimePunch

payroll_bp = Blueprint('payroll', __name__)


def _week_bounds(anchor):
    """Monday..Sunday of the week containing `anchor` (a date)."""
    monday = anchor - timedelta(days=anchor.weekday())  # weekday(): Mon=0
    sunday = monday + timedelta(days=6)
    return monday, sunday


@payroll_bp.route('/payroll')
@login_required
def index():
    # Which week? ?start=YYYY-MM-DD snaps to that date's Monday; default = this week.
    anchor = date.today()
    raw = request.args.get('start')
    if raw:
        try:
            anchor = datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            pass
    monday, sunday = _week_bounds(anchor)

    # Time punches are datetimes; bucket by clock_out within [Mon 00:00, next-Mon 00:00).
    start_dt = datetime.combine(monday, time.min)
    end_dt = datetime.combine(sunday + timedelta(days=1), time.min)
    punches = (TimePunch.query
               .filter(TimePunch.clock_out.isnot(None),
                       TimePunch.clock_out >= start_dt,
                       TimePunch.clock_out < end_dt)
               .all())

    # Work logs are dates; bucket by start_date within the week.
    logs = (WorkLog.query
            .filter(WorkLog.start_date >= monday,
                    WorkLog.start_date <= sunday)
            .all())

    rows = {}   # worker_id -> aggregate dict

    def bucket(w):
        if w.id not in rows:
            rows[w.id] = {
                'worker': w,
                'appr_hours': 0.0, 'pend_hours': 0.0,
                'appr_pay': 0.0, 'pend_pay': 0.0,
                'log_days': 0.0, 'log_pay': 0.0,
            }
        return rows[w.id]

    for p in punches:
        if not p.worker:
            continue
        r = bucket(p.worker)
        # Pay is by the day: each clocked day = one daily rate (not hours-based).
        # Hours are still summed as an attendance figure.
        day = round(p.worker.daily_rate or 0, 2)
        h = p.hours or 0
        if p.approved:
            r['appr_hours'] += h
            r['appr_pay'] += day
        else:
            r['pend_hours'] += h
            r['pend_pay'] += day

    for lg in logs:
        if not lg.worker:
            continue
        r = bucket(lg.worker)
        d = lg.days_worked or 0
        r['log_days'] += d
        r['log_pay'] += round(d * (lg.worker.daily_rate or 0), 2)

    # Firm = approved clock pay + manual work-log pay; Pending = unapproved clock pay.
    payroll = []
    for r in rows.values():
        firm = round(r['appr_pay'] + r['log_pay'], 2)
        pending = round(r['pend_pay'], 2)
        r['firm_pay'] = firm
        r['pending_pay'] = pending
        r['gross'] = round(firm + pending, 2)
        payroll.append(r)
    payroll.sort(key=lambda r: (r['worker'].name or '').lower())

    totals = {
        'firm': round(sum(r['firm_pay'] for r in payroll), 2),
        'pending': round(sum(r['pending_pay'] for r in payroll), 2),
        'gross': round(sum(r['gross'] for r in payroll), 2),
        'hours': round(sum(r['appr_hours'] + r['pend_hours'] for r in payroll), 2),
        'days': round(sum(r['log_days'] for r in payroll), 2),
    }

    return render_template(
        'payroll.html',
        payroll=payroll, totals=totals,
        monday=monday, sunday=sunday,
        prev_start=(monday - timedelta(days=7)).isoformat(),
        next_start=(monday + timedelta(days=7)).isoformat(),
        this_week_start=_week_bounds(date.today())[0].isoformat(),
        is_current_week=(monday == _week_bounds(date.today())[0]),
    )
