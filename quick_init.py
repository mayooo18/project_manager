# quick_init.py
# Idempotent DB init + create a default admin user

from app import app                      # your Flask app
from extensions import db                # your SQLAlchemy instance
from models import User                  # your User model (and others if you want)

with app.app_context():
    # Create all tables defined in models.py
    db.create_all()

    # Seed an admin user if missing
    username = "admin"
    password = "1234"  # change after first login

    existing = User.query.filter_by(username=username).first()
    if existing is None:
        u = User(username=username)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        print(f" Created user '{username}' with password '{password}'")
    else:
        print(f" User '{username}' already exists")

    print(" Database initialized successfully")
