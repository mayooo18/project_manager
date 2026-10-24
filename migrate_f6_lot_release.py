# migrate_f6_lot_release.py
# F6 — Lot Releases.
# Idempotent: creates the lot_release table. Safe to run repeatedly on Postgres
# (prod) and SQLite (local dev); db.create_all() only adds missing tables.
#
#   python migrate_f6_lot_release.py
from app import app
from extensions import db

with app.app_context():
    db.create_all()
    print("Migration complete: lot_release table ensured.")
