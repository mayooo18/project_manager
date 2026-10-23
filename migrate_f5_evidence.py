# migrate_f5_evidence.py
# F5 — Milestone Evidence Attachments.
# Idempotent: creates the milestone_evidence table. Safe to run repeatedly on
# both Postgres (prod) and SQLite (local dev). db.create_all() only adds missing
# tables, so this never touches existing data.
#
#   python migrate_f5_evidence.py
from app import app
from extensions import db

with app.app_context():
    db.create_all()
    print("Migration complete: milestone_evidence table ensured.")
