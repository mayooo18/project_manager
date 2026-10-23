# migrate_f1_retainage.py
# F1 — Real Retainage.
# Idempotent: adds retainage columns to the `invoice` table and the retainage-
# release columns to the `contract` table. Safe to run repeatedly on prod data.
#
# All new columns are nullable (or default false), so existing invoices and
# contracts are untouched — null retainage means "no retainage", i.e. exactly
# today's behaviour. Works on both Postgres (prod) and SQLite (local dev).
#
#   python migrate_f1_retainage.py
from sqlalchemy import text, inspect
from app import app
from extensions import db

# (table, column, SQL type, default-or-None)
COLUMNS = [
    ("invoice", "retainage_amount", "double precision", None),
    ("invoice", "retainage_percent", "double precision", None),
    ("invoice", "is_retainage_release", "boolean", "false"),
    ("contract", "retainage_released_at", "timestamp", None),
    ("contract", "retainage_release_invoice_id", "integer", None),
]

# Postgres-only foreign key for the release-invoice link.
PG_CONSTRAINTS = [
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_contract_retainage_release_invoice_id') THEN "
    "ALTER TABLE contract ADD CONSTRAINT fk_contract_retainage_release_invoice_id "
    "FOREIGN KEY (retainage_release_invoice_id) REFERENCES invoice (id); END IF; END $$",
]

# SQLite spells double precision / boolean differently and has no boolean type.
SQLITE_TYPE = {"double precision": "float", "boolean": "boolean",
               "timestamp": "datetime", "integer": "integer"}


def migrate_postgres():
    for table, col, sqltype, default in COLUMNS:
        ddl = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {sqltype}"
        if default is not None:
            ddl += f" NOT NULL DEFAULT {default}"
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
            lit = "0" if default == "false" else default
            ddl += f" NOT NULL DEFAULT {lit}"
        db.session.execute(text(ddl))
    # SQLite can't add a FK constraint to an existing table; the column alone is
    # enough for local dev (FK enforcement isn't needed to exercise the feature).


with app.app_context():
    if db.engine.dialect.name == "sqlite":
        migrate_sqlite()
    else:
        migrate_postgres()
    db.session.commit()
    print("Migration complete: F1 retainage columns ensured "
          "(invoice.retainage_*, contract.retainage_release*).")
