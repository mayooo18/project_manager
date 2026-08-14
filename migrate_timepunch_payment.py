# migrate_timepunch_payment.py
# Phase 8: links an approved TimePunch to the labor Payment it generates, so
# crew clock time flows into per-job cost/profit.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE time_punch ADD COLUMN IF NOT EXISTS payment_id integer",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_time_punch_payment_id') THEN "
    "ALTER TABLE time_punch ADD CONSTRAINT fk_time_punch_payment_id "
    "FOREIGN KEY (payment_id) REFERENCES payment (id); END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: time_punch.payment_id ensured.")
