# migrate_signature_audit.py
# Feature 8: create the signature_event audit table.
# Idempotent — db.create_all() only creates tables that don't exist yet and
# never alters existing ones. Safe to run locally or on deploy (also covered
# by quick_init.py's create_all()).

from app import app
from extensions import db
from models import SignatureEvent  # noqa: F401 — ensures the table is registered

with app.app_context():
    db.create_all()
    print("Migration complete: ensured signature_event table exists.")
