# migrate_f10_change_orders.py
# F10 — Stronger Change Orders.
# Idempotent: adds change_order.location + schedule_impact_days and creates the
# change_order_photo and customer_approver tables. Postgres (prod) + SQLite.
#
#   python migrate_f10_change_orders.py
from sqlalchemy import text, inspect
from app import app
from extensions import db

COLUMNS = [
    ("location", "varchar(250)"),
    ("schedule_impact_days", "integer"),
]


def ensure_columns():
    existing = {c["name"] for c in inspect(db.engine).get_columns("change_order")}
    is_sqlite = db.engine.dialect.name == "sqlite"
    for col, sqltype in COLUMNS:
        if col in existing:
            continue
        if is_sqlite:
            db.session.execute(text(
                f"ALTER TABLE change_order ADD COLUMN {col} {sqltype}"))
        else:
            db.session.execute(text(
                f"ALTER TABLE change_order ADD COLUMN IF NOT EXISTS {col} {sqltype}"))


with app.app_context():
    db.create_all()          # change_order_photo + customer_approver tables
    ensure_columns()
    db.session.commit()
    print("Migration complete: change_order.location/schedule_impact_days + "
          "change_order_photo + customer_approver ensured.")
