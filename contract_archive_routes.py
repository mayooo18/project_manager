"""Contract archive.

Lets the owner archive a contract that should no longer be used (for example a
draft replaced by newer property-specific contracts). Archiving:

- moves the contract to the Archived tab (status 'archived'),
- blocks billing, emailing, share links and customer e-signing,
- leaves it out of Program dashboard totals,
- keeps every field, draw and PDF (nothing is deleted).

Only contracts with nothing billed can be archived, so invoice and payment
history is never hidden. Restoring puts a contract back to 'accepted' if it was
signed, otherwise 'draft'.
"""
from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required

from extensions import db
from permissions import owner_required
from contract_routes import _owned_contract_or_404

contract_archive_bp = Blueprint('contract_archive', __name__,
                                url_prefix='/contracts')


def _back(contract):
    if request.form.get('next') == 'list':
        return redirect(url_for('contracts.index'))
    return redirect(url_for('contracts.edit', contract_id=contract.id))


@contract_archive_bp.route('/<int:contract_id>/archive', methods=['POST'])
@login_required
@owner_required
def archive(contract_id):
    contract = _owned_contract_or_404(contract_id)
    if contract.status == 'archived':
        flash('This contract is already archived.', 'error')
        return _back(contract)
    if contract.billed_to_date > 0 or any(d.is_billed for d in contract.draws):
        flash('This contract has billed draws, so it cannot be archived. '
              'Void its invoices first or mark it completed.', 'error')
        return _back(contract)
    contract.status = 'archived'
    # Kill any live customer link so it can't be signed after archiving.
    if hasattr(contract, 'public_token_revoked_at') and contract.public_token:
        from datetime import datetime
        contract.public_token_revoked_at = datetime.utcnow()
    db.session.commit()
    flash(f'{contract.number or "Contract"} archived. Billing and sending are '
          'turned off; nothing was deleted.', 'success')
    return _back(contract)


@contract_archive_bp.route('/<int:contract_id>/unarchive', methods=['POST'])
@login_required
@owner_required
def unarchive(contract_id):
    contract = _owned_contract_or_404(contract_id)
    if contract.status != 'archived':
        flash('This contract is not archived.', 'error')
        return _back(contract)
    contract.status = 'accepted' if contract.signed_at else 'draft'
    db.session.commit()
    flash(f'{contract.number or "Contract"} restored as {contract.status}.',
          'success')
    return _back(contract)
