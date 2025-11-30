from app import app
from extensions import db
from sqlalchemy import text

def migrate():
    """Add receipt fields to Payment table"""
    with app.app_context():
        try:
            # Check if columns already exist
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('payment')]
            
            if 'receipt_filename' in columns and 'receipt_filepath' in columns:
                print("✓ Receipt columns already exist in Payment table. No migration needed.")
                return
            
            print("Adding receipt columns to Payment table...")
            
            # Add the new columns
            with db.engine.connect() as conn:
                if 'receipt_filename' not in columns:
                    conn.execute(text(
                        "ALTER TABLE payment ADD COLUMN receipt_filename VARCHAR(200)"
                    ))
                    conn.commit()
                    print("✓ Added receipt_filename column")
                
                if 'receipt_filepath' not in columns:
                    conn.execute(text(
                        "ALTER TABLE payment ADD COLUMN receipt_filepath VARCHAR(300)"
                    ))
                    conn.commit()
                    print("✓ Added receipt_filepath column")
            
            print("\n✓ Migration completed successfully!")
            print("You can now deploy the updated application code.")
            
        except Exception as e:
            print(f"✗ Migration failed: {e}")
            raise

if __name__ == '__main__':
    migrate()