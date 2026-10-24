"""Insurance & bond compliance (F8).

Record required coverage per contract, assign subcontractors to a contract, and
auto-check expirations — your own insurance/bond Licenses and each assigned
sub's COI/license: Valid / Expiring (<=30 days) / Expired / Missing. The
lot-release sign flow (F6) uses `contract_blocks_release` to warn/block when an
assigned sub is expired or missing. Dollar amounts are recorded for reference,
not auto-verified.
"""
from datetime import date

from flask import Blueprint, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from extensions import db
from models import (
    Contract, Subcontractor, License, InsuranceRequirement,
    ContractSubcontractor, INSURANCE_COVERAGE_TYPES,
)

insurance_bp = Blueprint('insurance', __name__, url_prefix='/insurance')

WARN_DAYS = 30
# License credential types that count as insurance/bond coverage.
COVERAGE_CREDENTIAL_TYPES = {'Insurance', 'Bond'}


def _owned_contract_or_404(contract_id):
    return Contract.query.filter_by(
        id=contract_id, user_id=current_user.id).first_or_404()


# ── compliance helpers (also exposed to templates) ───────────────────────────

def coverage_status(expiration_date):
    """valid / expiring / expired / missing from an expiration date."""
    if not expiration_date:
        return 'missing'
    today = date.today()
    if expiration_date < today:
        return 'expired'
    if (expiration_date - today).days <= WARN_DAYS:
        return 'expiring'
    return 'valid'


def company_credentials(user_id):
    """The company's insurance/bond Licenses with expiration status."""
    lics = (License.query.filter_by(user_id=user_id)
            .filter(License.credential_type.in_(COVERAGE_CREDENTIAL_TYPES))
            .order_by(License.expiration_date.asc().nullslast()).all())
    return [{'license': l, 'status': coverage_status(l.expiration_date)} for l in lics]


def assigned_subs_compliance(contract):
    """Each assigned sub with COI + license status."""
    rows = []
    for link in contract.sub_links:
        s = link.subcontractor
        if s is None:
            continue
        rows.append({
            'link': link, 'sub': s,
            'coi_status': coverage_status(s.insurance_expiration),
            'license_status': coverage_status(s.license_expiration),
        })
    return rows


def contract_blocks_release(contract):
    """True when an assigned sub's COI is expired or missing — the condition
    that blocks the contractor's lot-release sign. No assigned subs → never
    blocks (most jobs)."""
    for row in assigned_subs_compliance(contract):
        if row['coi_status'] in ('expired', 'missing'):
            return True
    return False


def insurance_summary(contract):
    """Everything the contract panel and the sign gate need."""
    subs = assigned_subs_compliance(contract)
    creds = company_credentials(contract.user_id)
    cred_issue = any(c['status'] in ('expired', 'missing') for c in creds)
    sub_issue = any(r['coi_status'] in ('expired', 'missing') for r in subs)
    return {
        'requirements': contract.insurance_requirements,
        'credentials': creds,
        'subs': subs,
        'blocks_release': sub_issue,
        'has_warning': cred_issue or sub_issue
                       or any(c['status'] == 'expiring' for c in creds)
                       or any(r['coi_status'] == 'expiring' for r in subs),
        'coverage_types': INSURANCE_COVERAGE_TYPES,
    }


# ── required-coverage lines ──────────────────────────────────────────────────

@insurance_bp.route('/contract/<int:contract_id>/requirement/add', methods=['POST'])
@login_required
def add_requirement(contract_id):
    contract = _owned_contract_or_404(contract_id)
    ctype = (request.form.get('coverage_type') or '').strip()
    if ctype not in INSURANCE_COVERAGE_TYPES:
        flash('Pick a valid coverage type.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))
    try:
        amount = float(request.form.get('required_amount'))
    except (TypeError, ValueError):
        amount = None
    db.session.add(InsuranceRequirement(
        contract_id=contract.id, coverage_type=ctype, required_amount=amount,
        notes=(request.form.get('notes') or '').strip() or None))
    db.session.commit()
    flash('Coverage requirement added.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


@insurance_bp.route('/requirement/<int:req_id>/delete', methods=['POST'])
@login_required
def delete_requirement(req_id):
    req = InsuranceRequirement.query.get_or_404(req_id)
    contract = _owned_contract_or_404(req.contract_id)
    db.session.delete(req)
    db.session.commit()
    flash('Requirement removed.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


# ── assign subcontractors ────────────────────────────────────────────────────

@insurance_bp.route('/contract/<int:contract_id>/assign-sub', methods=['POST'])
@login_required
def assign_sub(contract_id):
    contract = _owned_contract_or_404(contract_id)
    sub_id = request.form.get('subcontractor_id', type=int)
    sub = Subcontractor.query.filter_by(id=sub_id, user_id=current_user.id).first()
    if sub is None:
        flash('Pick a subcontractor to assign.', 'error')
        return redirect(url_for('contracts.edit', contract_id=contract.id))
    exists = ContractSubcontractor.query.filter_by(
        contract_id=contract.id, subcontractor_id=sub.id).first()
    if exists is None:
        db.session.add(ContractSubcontractor(
            contract_id=contract.id, subcontractor_id=sub.id))
        db.session.commit()
        flash(f'{sub.name} assigned to this contract.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))


@insurance_bp.route('/sub-link/<int:link_id>/delete', methods=['POST'])
@login_required
def unassign_sub(link_id):
    link = ContractSubcontractor.query.get_or_404(link_id)
    contract = _owned_contract_or_404(link.contract_id)
    db.session.delete(link)
    db.session.commit()
    flash('Subcontractor unassigned.', 'success')
    return redirect(url_for('contracts.edit', contract_id=contract.id))
