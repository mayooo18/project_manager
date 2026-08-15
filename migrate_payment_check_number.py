# migrate_payment_check_number.py
# Adds payment.check_number so check payments can store the check number in its
# own field (and be filtered by method). Idempotent — safe to run more than once.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE payment ADD COLUMN IF NOT EXISTS check_number varchar(60)",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: payment.check_number ensured.")
