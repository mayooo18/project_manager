# migrate_license_fields.py
# Idempotent: Phase 6b adds the `license` table (created by quick_init.py /
# create_all) plus three columns on the existing `reminder` table so company
# license/credential renewals reuse the auto-reminder mechanism.
# Run order on Render: quick_init.py THEN this script.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS license_id integer",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS license_field varchar(50)",
    "ALTER TABLE reminder ADD COLUMN IF NOT EXISTS license_offset_days integer",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_reminder_license_id') THEN "
    "ALTER TABLE reminder ADD CONSTRAINT fk_reminder_license_id "
    "FOREIGN KEY (license_id) REFERENCES license (id); END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: reminder.license_* columns ensured "
          "(run after quick_init.py).")
