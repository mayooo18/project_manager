# migrate_crew_login.py
# Phase 8 §1: adds phone + pin_hash to the existing `worker` table for the
# phone+PIN crew portal login.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS phone varchar(30)",
    "ALTER TABLE worker ADD COLUMN IF NOT EXISTS pin_hash varchar(255)",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: worker.phone + worker.pin_hash ensured.")
