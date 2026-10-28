# migrate_f11_weekly_report.py
# F11 — Weekly Progress Report.
# Idempotent: creates the weekly_report table. Postgres (prod) + SQLite.
#   python migrate_f11_weekly_report.py
from app import app
from extensions import db

with app.app_context():
    db.create_all()
    print("Migration complete: weekly_report table ensured.")
