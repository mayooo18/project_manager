# migrate_subcontractor_fields.py
# Idempotent: Phase 6a adds the `subcontractor` table (created by quick_init.py /
# create_all) plus three columns on the existing `reminder` table so subcontractor
# license/insurance expirations reuse the auto-reminder mechanism.
# Run order on Render: quick_init.py THEN this script.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS subcontractor_id integer",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS subcontractor_field varchar(50)",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS subcontractor_offset_days integer",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_reminder_subcontractor_id') THEN "
    "ALTER TABLE reminder ADD CONSTRAINT fk_reminder_subcontractor_id "
    "FOREIGN KEY (subcontractor_id) REFERENCES subcontractor (id); END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: reminder.subcontractor_* columns ensured "
          "(run after quick_init.py).")
