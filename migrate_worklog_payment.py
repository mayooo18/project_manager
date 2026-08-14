# migrate_worklog_payment.py
# Phase 7 §5a: links an auto-generated labor Payment to its WorkLog.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE payment ADD COLUMN IF NOT EXISTS work_log_id integer",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_payment_work_log_id') THEN "
    "ALTER TABLE payment ADD CONSTRAINT fk_payment_work_log_id "
    "FOREIGN KEY (work_log_id) REFERENCES work_log (id); END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: payment.work_log_id ensured.")
