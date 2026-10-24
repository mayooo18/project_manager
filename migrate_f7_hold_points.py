# migrate_f7_hold_points.py
# F7 — Hold-Point Checklist.
# Idempotent: creates the hold_point and hold_point_photo tables. Safe to run
# repeatedly on Postgres (prod) and SQLite (local dev); db.create_all() only
# adds missing tables.
#
#   python migrate_f7_hold_points.py
from app import app
from extensions import db

with app.app_context():
    db.create_all()
    print("Migration complete: hold_point + hold_point_photo tables ensured.")
