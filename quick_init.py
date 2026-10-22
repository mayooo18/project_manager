# quick_init.py
# Idempotent DB init + create a default admin user

import secrets

from sqlalchemy import inspect, text

from app import app                      # your Flask app
from extensions import db                # your SQLAlchemy instance
from models import User                  # your User model (and others if you want)

with app.app_context():
    # Create all tables defined in models.py
    db.create_all()

    # ── Lightweight column migrations (idempotent) ──
    # db.create_all() adds missing TABLES but never alters existing ones, so
    # new columns on already-existing tables are added here by hand. Each check
    # is safe to run repeatedly (it no-ops once the column exists).
    insp = inspect(db.engine)
    quote_cols = {c['name'] for c in insp.get_columns('quote')}
    if 'revision_of_id' not in quote_cols:
        db.session.execute(text('ALTER TABLE quote ADD COLUMN revision_of_id INTEGER'))
        db.session.commit()
        print(" Added column quote.revision_of_id")
    else:
        print(" Column quote.revision_of_id already present")

    # Seed an admin user if missing
    username = "admin"

    existing = User.query.filter_by(username=username).first()
    if existing is None:
        password = secrets.token_urlsafe(16)
        u = User(username=username)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        print(f" Created user '{username}' with password '{password}' — store this securely and change it after first login")
    else:
        print(f" User '{username}' already exists")

    print(" Database initialized successfully")
