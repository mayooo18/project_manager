import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required to run performance index migration.")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)


INDEXES = [
    ("worker", "active"),
    ("worker", "phone"),
    ("project", "status"),
    ("expense", "project_id"),
    ("expense", "category"),
    ("expense", "date"),
    ("income", "project_id"),
    ("income", "date"),
    ("payment", "worker_id"),
    ("payment", "project_id"),
    ("payment", "payment_date"),
    ("payment", "work_log_id"),
    ("work_log", "worker_id"),
    ("work_log", "project_id"),
    ("work_log", "start_date"),
    ("reminder", "user_id"),
    ("reminder", "due_date"),
    ("reminder", "is_done"),
    ("task", "project_id"),
    ("task", "worker_id"),
    ("task", "status"),
    ("time_punch", "worker_id"),
    ("time_punch", "project_id"),
    ("time_punch", "clock_in"),
    ("time_punch", "clock_out"),
    ("time_punch", "approved"),
    ("time_punch", "payment_id"),
    ("quote", "user_id"),
    ("quote", "customer_id"),
    ("quote", "project_id"),
    ("quote", "status"),
    ("quote", "created_at"),
    ("invoice", "user_id"),
    ("invoice", "customer_id"),
    ("invoice", "project_id"),
    ("invoice", "quote_id"),
    ("invoice", "contract_id"),
    ("invoice", "status"),
    ("invoice", "income_id"),
    ("invoice", "created_at"),
    ("contract", "user_id"),
    ("contract", "customer_id"),
    ("contract", "project_id"),
    ("contract", "quote_id"),
    ("contract", "status"),
    ("contract", "created_at"),
    ("contract_draw", "contract_id"),
    ("contract_draw", "status"),
    ("contract_draw", "invoice_id"),
]


def index_name(table, column):
    return f"ix_{table}_{column}"


def create_index_sql(table, column):
    name = index_name(table, column)
    return f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ("{column}")'


if __name__ == "__main__":
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        for table, column in INDEXES:
            conn.execute(text(create_index_sql(table, column)))
    print(f"Migration complete: ensured {len(INDEXES)} performance indexes.")
