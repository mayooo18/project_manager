# migrate_location_fields.py
# Phase 7 (section 1): adds the `location` table (created by quick_init.py /
# create_all) plus customer_id + location_id on the existing `project` table.
# Run order on Render: quick_init.py THEN this script.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE project ADD COLUMN IF NOT EXISTS customer_id integer",
    "ALTER TABLE project ADD COLUMN IF NOT EXISTS location_id integer",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_project_customer_id') THEN "
    "ALTER TABLE project ADD CONSTRAINT fk_project_customer_id "
    "FOREIGN KEY (customer_id) REFERENCES customer (id); END IF; END $$",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_project_location_id') THEN "
    "ALTER TABLE project ADD CONSTRAINT fk_project_location_id "
    "FOREIGN KEY (location_id) REFERENCES location (id); END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: location table + project.customer_id/location_id ensured.")
