# migrate_f15_estimate.py
# F15 — Cost Estimate per Lot.
# Idempotent: creates the cost_estimate + cost_estimate_line tables.
# Postgres (prod) + SQLite.
#   python migrate_f15_estimate.py
from app import app
from extensions import db

with app.app_context():
    db.create_all()
    print("Migration complete: cost_estimate + cost_estimate_line tables ensured.")
