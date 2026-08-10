# migrate_quote_fields.py
# Idempotent: add optional quote fields and expiring public-link fields.
from sqlalchemy import text
from app import app
from extensions import db

STATEMENTS = [
    "ALTER TABLE quote ADD COLUMN IF NOT EXISTS deposit double precision",
    "ALTER TABLE quote ADD COLUMN IF NOT EXISTS po_number varchar(50)",
    "ALTER TABLE quote ADD COLUMN IF NOT EXISTS public_token_expires_at timestamp",
    "ALTER TABLE quote ADD COLUMN IF NOT EXISTS public_token_revoked_at timestamp",
    "ALTER TABLE customer ADD COLUMN IF NOT EXISTS user_id integer",
    "ALTER TABLE quote ADD COLUMN IF NOT EXISTS user_id integer",
    "UPDATE customer SET user_id = (SELECT id FROM \"user\" ORDER BY id LIMIT 1) "
    "WHERE user_id IS NULL",
    "UPDATE quote SET user_id = COALESCE("
    "(SELECT customer.user_id FROM customer WHERE customer.id = quote.customer_id), "
    "(SELECT id FROM \"user\" ORDER BY id LIMIT 1)) WHERE user_id IS NULL",
    "UPDATE quote SET public_token_expires_at = "
    "COALESCE(sent_at, created_at, CURRENT_TIMESTAMP) + INTERVAL '30 days' "
    "WHERE public_token_expires_at IS NULL",
    "ALTER TABLE quote ALTER COLUMN public_token_expires_at SET NOT NULL",
    "ALTER TABLE customer ALTER COLUMN user_id SET NOT NULL",
    "ALTER TABLE quote ALTER COLUMN user_id SET NOT NULL",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_customer_user_id') THEN "
    "ALTER TABLE customer ADD CONSTRAINT fk_customer_user_id "
    "FOREIGN KEY (user_id) REFERENCES \"user\" (id); END IF; END $$",
    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint "
    "WHERE conname = 'fk_quote_user_id') THEN "
    "ALTER TABLE quote ADD CONSTRAINT fk_quote_user_id "
    "FOREIGN KEY (user_id) REFERENCES \"user\" (id); END IF; END $$",
]

with app.app_context():
    for stmt in STATEMENTS:
        db.session.execute(text(stmt))
    db.session.commit()
    print("Migration complete: quote optional fields and public-link expiry ensured.")
