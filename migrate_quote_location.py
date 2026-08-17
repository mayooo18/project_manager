# migrate_quote_location.py
# Adds quote.location_id so a proposal can carry its own property/site address
# (used to set the Job's address on conversion). Existing quotes stay NULL and
# fall back to the customer's address, as before.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE quote ADD COLUMN IF NOT EXISTS location_id integer REFERENCES location(id)",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: quote.location_id ensured.")
