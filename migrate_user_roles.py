# migrate_user_roles.py
# Phase 8 §4: adds role + active to the existing `user` table. Existing
# accounts become owners and stay active.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS role varchar(20) NOT NULL DEFAULT 'owner'",
    "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: user.role + user.active ensured (existing users = owner).")
