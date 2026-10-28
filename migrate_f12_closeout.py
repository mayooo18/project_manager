# migrate_f12_closeout.py
# F12 — Closeout Package.
# Idempotent: creates the punch_item table and adds project.closeout_accepted_at.
# Postgres (prod) + SQLite.
#   python migrate_f12_closeout.py
from sqlalchemy import text, inspect
from app import app
from extensions import db


def ensure_closeout_column():
    cols = {c["name"] for c in inspect(db.engine).get_columns("project")}
    if "closeout_accepted_at" in cols:
        return
    if db.engine.dialect.name == "sqlite":
        db.session.execute(text(
            "ALTER TABLE project ADD COLUMN closeout_accepted_at datetime"))
    else:
        db.session.execute(text(
            "ALTER TABLE project ADD COLUMN IF NOT EXISTS "
            "closeout_accepted_at timestamp"))


with app.app_context():
    db.create_all()
    ensure_closeout_column()
    db.session.commit()
    print("Migration complete: punch_item + project.closeout_accepted_at ensured.")
