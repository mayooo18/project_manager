# migrate_sent_archive.py
# Sent-document archive — immutable PDF snapshots taken on send.
# Idempotent: creates the sent_document_archive table. Safe to run repeatedly
# on Postgres (prod) and SQLite (local dev); db.create_all() only adds missing
# tables.
#
#   python migrate_sent_archive.py
from app import app
from extensions import db

with app.app_context():
    db.create_all()
    print("Migration complete: sent_document_archive table ensured.")
