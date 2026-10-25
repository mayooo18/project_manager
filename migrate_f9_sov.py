# migrate_f9_sov.py
# F9 — Schedule of Values & Unit Rates.
# Idempotent: creates the unit_rate table and adds
# contract.unit_rate_markup_percent. Safe to run repeatedly on Postgres (prod)
# and SQLite (local dev).
#
#   python migrate_f9_sov.py
from sqlalchemy import text, inspect
from app import app
from extensions import db


def ensure_markup_column():
    cols = {c["name"] for c in inspect(db.engine).get_columns("contract")}
    if "unit_rate_markup_percent" in cols:
        return
    if db.engine.dialect.name == "sqlite":
        db.session.execute(text(
            "ALTER TABLE contract ADD COLUMN unit_rate_markup_percent float"))
    else:
        db.session.execute(text(
            "ALTER TABLE contract ADD COLUMN IF NOT EXISTS "
            "unit_rate_markup_percent double precision"))


with app.app_context():
    db.create_all()          # creates the unit_rate table if missing
    ensure_markup_column()
    db.session.commit()
    print("Migration complete: unit_rate table + contract.unit_rate_markup_percent ensured.")
