# migrate_permit_fields.py
# Idempotent: Phase 6c adds the `permit` and `inspection` tables (created by
# quick_init.py / create_all) plus six columns on the existing `reminder` table
# so permit-expiration and inspection reminders reuse the auto-reminder mechanism.
# Run order on Render: quick_init.py THEN this script.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS permit_id integer",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS permit_field varchar(50)",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS permit_offset_days integer",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS inspection_id integer",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS inspection_field varchar(50)",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS inspection_offset_days integer",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_reminder_permit_id') THEN "
    "ALTER TABLE reminder ADD CONSTRAINT fk_reminder_permit_id "
    "FOREIGN KEY (permit_id) REFERENCES permit (id); END IF; END $$",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_reminder_inspection_id') THEN "
    "ALTER TABLE reminder ADD CONSTRAINT fk_reminder_inspection_id "
    "FOREIGN KEY (inspection_id) REFERENCES inspection (id); END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: reminder.permit_*/inspection_* columns ensured "
          "(run after quick_init.py).")
