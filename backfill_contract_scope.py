# backfill_contract_scope.py
# One-time, idempotent backfill: fill scope_of_work for contracts that were
# created from a proposal but don't have a scope yet (created before this
# feature existed).
#
#   - Only touches contracts with a linked quote (quote_id set).
#   - Skips contracts whose scope_of_work is already set, so re-running is safe
#     and never overwrites a scope someone edited by hand.
#   - Skips contracts whose proposal has no line items.
#
# Run the schema migration first:  python migrate_contract_scope.py
# Then:                            python backfill_contract_scope.py
from app import app
from extensions import db
from models import Contract
from contract_routes import _scope_from_quote

with app.app_context():
    filled = skipped = 0
    contracts = Contract.query.filter(Contract.quote_id.isnot(None)).all()
    for c in contracts:
        if (c.scope_of_work or '').strip():
            skipped += 1
            continue
        scope = _scope_from_quote(c.quote) if c.quote else ''
        if scope:
            c.scope_of_work = scope
            filled += 1
        else:
            skipped += 1
    db.session.commit()
    print(f"Backfill complete: {filled} contract(s) filled, {skipped} skipped.")
