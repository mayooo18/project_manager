# migrate_portal_fields.py
# Idempotent: Phase 5 adds a client-portal magic-link token to the existing
# `project` table. Run on Render after deploy (no new tables).
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE project ADD COLUMN IF NOT EXISTS portal_token varchar(64)",
    "ALTER TABLE project ADD COLUMN IF NOT EXISTS portal_token_revoked_at timestamp",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'uq_project_portal_token') THEN "
    "ALTER TABLE project ADD CONSTRAINT uq_project_portal_token UNIQUE (portal_token); "
    "END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: project.portal_token ensured.")
