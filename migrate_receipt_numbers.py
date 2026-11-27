"""Add paid-receipt fields to the Invoice table and create the ReceiptSend table.

Idempotent: safe to run repeatedly. Mirrors the other migrate_*.py scripts so
it can be run once on Render after deploy (`python migrate_receipt_numbers.py`)
or wired into quick_init / migrate_all.
"""
from app import app
from extensions import db
from sqlalchemy import text


def migrate():
    with app.app_context():
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('invoice')]
        new_cols = {
            'receipt_number': 'VARCHAR(50)',
            'receipt_first_sent_at': 'TIMESTAMP',
            'receipt_last_sent_at': 'TIMESTAMP',
            'receipt_last_recipient': 'VARCHAR(200)',
        }
        with db.engine.connect() as conn:
            for name, coltype in new_cols.items():
                if name not in columns:
                    conn.execute(text(
                        f"ALTER TABLE invoice ADD COLUMN {name} {coltype}"))
                    conn.commit()
                    print(f"✓ Added invoice.{name}")
                else:
                    print(f"✓ invoice.{name} already exists")

        # create_all only creates missing tables, so this adds receipt_send
        # without touching existing tables.
        db.create_all()
        print("✓ Ensured receipt_send table exists")
        print("\n✓ Migration completed successfully!")


if __name__ == '__main__':
    migrate()
