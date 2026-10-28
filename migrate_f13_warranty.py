# migrate_f13_warranty.py
# F13 — Warranty Tracker.
# Idempotent: adds project.warranty_start/warranty_end and creates the
# warranty_call + warranty_call_photo tables. Postgres (prod) + SQLite.
#   python migrate_f13_warranty.py
from sqlalchemy import text, inspect
from app import app
from extensions import db

COLUMNS = [("warranty_start", "date"), ("warranty_end", "date")]


def ensure_columns():
    existing = {c["name"] for c in inspect(db.engine).get_columns("project")}
    is_sqlite = db.engine.dialect.name == "sqlite"
    for col, sqltype in COLUMNS:
        if col in existing:
            continue
        if is_sqlite:
            db.session.execute(text(f"ALTER TABLE project ADD COLUMN {col} {sqltype}"))
        else:
            db.session.execute(text(
                f"ALTER TABLE project ADD COLUMN IF NOT EXISTS {col} {sqltype}"))


with app.app_context():
    db.create_all()
    ensure_columns()
    db.session.commit()
    print("Migration complete: project.warranty_start/end + warranty_call + "
          "warranty_call_photo ensured.")
