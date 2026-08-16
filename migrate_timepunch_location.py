# migrate_timepunch_location.py
# Adds GPS columns to time_punch so crew clock-in / clock-out can record where
# the punch happened (attendance proof). Idempotent — safe to run more than once.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE time_punch ADD COLUMN IF NOT EXISTS clock_in_lat  double precision",
    "ALTER TABLE time_punch ADD COLUMN IF NOT EXISTS clock_in_lng  double precision",
    "ALTER TABLE time_punch ADD COLUMN IF NOT EXISTS clock_out_lat double precision",
    "ALTER TABLE time_punch ADD COLUMN IF NOT EXISTS clock_out_lng double precision",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: time_punch GPS columns ensured.")
