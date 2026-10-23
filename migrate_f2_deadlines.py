# migrate_f2_deadlines.py
# F2 — Payment Deadline Tracker.
# Idempotent: adds the per-contract deadline windows, the invoice received-at
# timestamp, and the reminder→invoice link. Safe to run repeatedly on prod.
#
# All new columns are nullable (the contract windows carry their default day
# counts), so existing contracts, invoices and reminders are untouched — an
# invoice only gets deadline behaviour when its contract has deadlines on.
# Works on Postgres (prod) and SQLite (local dev).
#
#   python migrate_f2_deadlines.py
from sqlalchemy import text, inspect
from app import app
from extensions import db

# (table, column, SQL type, default-or-None)
COLUMNS = [
    ("contract", "review_days", "integer", "5"),
    ("contract", "payment_days", "integer", "10"),
    ("contract", "retainage_release_days", "integer", "30"),
    ("invoice", "received_at", "timestamp", None),
    ("reminder", "invoice_id", "integer", None),
]

PG_CONSTRAINTS = [
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_reminder_invoice_id') THEN "
    "ALTER TABLE reminder ADD CONSTRAINT fk_reminder_invoice_id "
    "FOREIGN KEY (invoice_id) REFERENCES invoice (id); END IF; END $$",
]

SQLITE_TYPE = {"integer": "integer", "timestamp": "datetime"}


def migrate_postgres():
    for table, col, sqltype, default in COLUMNS:
        ddl = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {sqltype}"
        if default is not None:
            ddl += f" DEFAULT {default}"
        db.session.execute(text(ddl))
    for stmt in PG_CONSTRAINTS:
        db.session.execute(text(stmt))


def migrate_sqlite():
    for table, col, sqltype, default in COLUMNS:
        existing = {c["name"] for c in inspect(db.engine).get_columns(table)}
        if col in existing:
            continue
        ddl = f"ALTER TABLE {table} ADD COLUMN {col} {SQLITE_TYPE[sqltype]}"
        if default is not None:
            ddl += f" DEFAULT {default}"
        db.session.execute(text(ddl))


with app.app_context():
    if db.engine.dialect.name == "sqlite":
        migrate_sqlite()
    else:
        migrate_postgres()
    db.session.commit()
    print("Migration complete: F2 deadline columns ensured "
          "(contract.*_days, invoice.received_at, reminder.invoice_id).")
