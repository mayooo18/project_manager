# migrate_f8_insurance.py
# F8 — Insurance & Bond Compliance.
# Idempotent: creates the insurance_requirement and contract_subcontractor
# tables. Safe to run repeatedly on Postgres (prod) and SQLite (local dev);
# db.create_all() only adds missing tables.
#
#   python migrate_f8_insurance.py
from app import app
from extensions import db

with app.app_context():
    db.create_all()
    print("Migration complete: insurance_requirement + contract_subcontractor "
          "tables ensured.")
