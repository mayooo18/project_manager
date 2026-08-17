# prune_activity_log.py
# Housekeeping: delete activity-log entries older than the retention window
# (default 12 months) so the table doesn't grow without bound.
#
# Run manually, or on a schedule (e.g. Render Cron Job):
#   python prune_activity_log.py            # keep last 12 months
#   RETENTION_MONTHS=6 python prune_activity_log.py   # keep last 6 months
import os
from datetime import datetime, timedelta

from app import app
from extensions import db
from activity_log import ActivityLog

# Months of history to keep. 12 months ~= 365 days (calendar-month math isn't
# needed for a retention cutoff — days are close enough and dependency-free).
RETENTION_MONTHS = int(os.environ.get('RETENTION_MONTHS', '12'))
cutoff = datetime.utcnow() - timedelta(days=RETENTION_MONTHS * 30)

with app.app_context():
    deleted = (ActivityLog.query
               .filter(ActivityLog.created_at < cutoff)
               .delete(synchronize_session=False))
    db.session.commit()
    print(f"Pruned {deleted} activity-log ent"
          f"{'ry' if deleted == 1 else 'ries'} older than "
          f"{RETENTION_MONTHS} months (before {cutoff:%Y-%m-%d}).")
