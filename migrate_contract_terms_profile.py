# migrate_contract_terms_profile.py
# F0 — Contract Terms Profiles.
# Idempotent: adds the terms-profile column and six feature-toggle columns to
# the existing `contract` table. Safe to run repeatedly on production data.
#
# Each column is added with a default that reproduces today's behaviour:
#   terms_profile            -> 'simple'   (plain contract, nothing extra shown)
#   *_enabled / *_required   -> false      (every optional feature off)
# Because of these DEFAULTs, existing contracts are backfilled to the Simple /
# all-off state automatically, so nothing about current contracts changes.
#
# Works on both the production Postgres database and a local SQLite database:
#   - Postgres uses "ADD COLUMN IF NOT EXISTS" (like the other migrate_*.py).
#   - SQLite has no "IF NOT EXISTS" on ADD COLUMN, so we inspect the existing
#     columns first and only add the ones that are missing.
#
#   python migrate_contract_terms_profile.py
from sqlalchemy import text, inspect
from app import app
from extensions import db

# (column name, SQL type, default literal) — one per new column.
COLUMNS = [
    ("terms_profile", "varchar(20)", "'simple'"),
    ("retainage_enabled", "boolean", "false"),
    ("deadlines_enabled", "boolean", "false"),
    ("sworn_statements_enabled", "boolean", "false"),
    ("lot_releases_enabled", "boolean", "false"),
    ("hold_points_enabled", "boolean", "false"),
    ("evidence_required", "boolean", "false"),
]


def migrate_postgres():
    for name, sqltype, default in COLUMNS:
        db.session.execute(text(
            f"ALTER TABLE contract ADD COLUMN IF NOT EXISTS "
            f"{name} {sqltype} NOT NULL DEFAULT {default}"))
    db.session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_contract_terms_profile "
        "ON contract (terms_profile)"))


def migrate_sqlite():
    # SQLite can't ADD COLUMN IF NOT EXISTS, so skip columns that already exist.
    existing = {c["name"] for c in inspect(db.engine).get_columns("contract")}
    # SQLite has no boolean type and spells false as 0.
    type_map = {"boolean": "boolean", "varchar(20)": "varchar(20)"}
    for name, sqltype, default in COLUMNS:
        if name in existing:
            continue
        default_lit = "0" if default == "false" else default
        db.session.execute(text(
            f"ALTER TABLE contract ADD COLUMN "
            f"{name} {type_map[sqltype]} NOT NULL DEFAULT {default_lit}"))
    # CREATE INDEX IF NOT EXISTS is valid in SQLite.
    db.session.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_contract_terms_profile "
        "ON contract (terms_profile)"))


with app.app_context():
    if db.engine.dialect.name == "sqlite":
        migrate_sqlite()
    else:
        migrate_postgres()
    db.session.commit()
    print("Migration complete: contract terms_profile + feature toggles ensured.")
