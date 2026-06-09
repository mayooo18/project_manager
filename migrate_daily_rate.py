from app import app
from extensions import db
from sqlalchemy import text

def migrate():
    """Rename Worker.hourly_rate -> daily_rate and WorkLog.hours_worked -> days_worked,
    converting existing values (hourly_rate * 8, hours_worked / 8)."""
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            worker_columns = [col['name'] for col in inspector.get_columns('worker')]
            work_log_columns = [col['name'] for col in inspector.get_columns('work_log')]

            with db.engine.connect() as conn:
                if 'hourly_rate' in worker_columns and 'daily_rate' not in worker_columns:
                    conn.execute(text("ALTER TABLE worker RENAME COLUMN hourly_rate TO daily_rate"))
                    conn.execute(text("UPDATE worker SET daily_rate = daily_rate * 8 WHERE daily_rate IS NOT NULL"))
                    conn.commit()
                    print("✓ Renamed worker.hourly_rate -> daily_rate and converted values (x8)")
                else:
                    print("✓ worker.daily_rate already up to date. Skipping.")

                if 'hours_worked' in work_log_columns and 'days_worked' not in work_log_columns:
                    conn.execute(text("ALTER TABLE work_log RENAME COLUMN hours_worked TO days_worked"))
                    conn.execute(text("UPDATE work_log SET days_worked = days_worked / 8 WHERE days_worked IS NOT NULL"))
                    conn.commit()
                    print("✓ Renamed work_log.hours_worked -> days_worked and converted values (/8)")
                else:
                    print("✓ work_log.days_worked already up to date. Skipping.")

            print("\n✓ Migration completed successfully!")

        except Exception as e:
            print(f"✗ Migration failed: {e}")
            raise

if __name__ == '__main__':
    migrate()
