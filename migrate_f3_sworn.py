# migrate_f3_sworn.py
# F3 — Contractor's Sworn Statement generator.
# Idempotent: adds `kind` to subcontractor and creates the sworn_statement +
# sworn_statement_line tables. Safe to run repeatedly on prod. Works on both
# Postgres (prod) and SQLite (local dev) — db.create_all() makes any missing
# tables; this script only needs to add the new column to an existing table.
#
#   python migrate_f3_sworn.py
from sqlalchemy import text, inspect
from app import app
from extensions import db


def ensure_kind_column():
    insp = inspect(db.engine)
    cols = {c["name"] for c in insp.get_columns("subcontractor")}
    if "kind" in cols:
        return
    if db.engine.dialect.name == "sqlite":
        db.session.execute(text(
            "ALTER TABLE subcontractor ADD COLUMN kind varchar(20) "
            "DEFAULT 'subcontractor'"))
    else:
        db.session.execute(text(
            "ALTER TABLE subcontractor ADD COLUMN IF NOT EXISTS kind "
            "varchar(20) DEFAULT 'subcontractor'"))


with app.app_context():
    # create_all makes the two new sworn-statement tables if they're missing.
    db.create_all()
    ensure_kind_column()
    db.session.commit()
    print("Migration complete: subcontractor.kind + sworn_statement tables ensured.")
