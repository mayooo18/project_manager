# migrate_contract_scope.py
# Idempotent: add the frozen Scope of Work snapshot column to contracts.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE contract ADD COLUMN IF NOT EXISTS scope_of_work text",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: contract.scope_of_work column ensured.")
