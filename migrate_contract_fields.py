# migrate_contract_fields.py
# Idempotent: Phase 3 adds the `contract` and `contract_draw` tables (created by
# quick_init.py / create_all) plus one new column on the existing `invoice` table.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE invoice ADD COLUMN IF NOT EXISTS contract_id integer",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_invoice_contract_id') THEN "
    "ALTER TABLE invoice ADD CONSTRAINT fk_invoice_contract_id "
    "FOREIGN KEY (contract_id) REFERENCES contract (id); END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: invoice.contract_id ensured (run after quick_init.py).")
