"""Program dashboard (F14).

A read-only, per-customer view of every property's pipeline and rolled-up
totals. Pure aggregation of existing contract/project data — no new models.
"""
from flask import Blueprint, render_template
from flask_login import login_required, current_user

from models import Customer, Invoice
from report_routes import project_stage

program_bp = Blueprint('program', __name__, url_prefix='/program')

PIPELINE_STAGES = [
    'Awarded', 'Released', 'In progress', 'Invoiced',
    'Paid', 'Closed out', 'Retainage released',
]


def _contract_pipeline(contract):
    """Boolean per pipeline stage for one contract/property."""
    project = contract.project
    billed = contract.billed_to_date
    paid = contract.paid_to_date
    return {
        'Awarded': True,
        'Released': project.lot_release_ok if project else (not contract.lot_releases_enabled),
        'In progress': contract.status in ('active', 'completed') or billed > 0,
        'Invoiced': billed > 0,
        'Paid': paid > 0,
        'Closed out': bool(project and project.is_closed_out),
        'Retainage released': contract.retainage_is_released
                              or (not contract.retainage_enabled and bool(project and project.is_closed_out)),
    }


def program_data():
    """Per-customer cards + grand totals."""
    customers = (Customer.query.filter_by(user_id=current_user.id)
                 .order_by(Customer.name.asc()).all())
    cards = []
    grand = {'contract': 0.0, 'billed': 0.0, 'paid': 0.0, 'retainage': 0.0, 'overdue': 0.0}
    for cu in customers:
        contracts = list(cu.contracts)
        if not contracts:
            continue
        rows = []
        totals = {'contract': 0.0, 'billed': 0.0, 'paid': 0.0, 'retainage': 0.0}
        for con in contracts:
            totals['contract'] += con.contract_total or 0
            totals['billed'] += con.billed_to_date
            totals['paid'] += con.paid_to_date
            totals['retainage'] += con.retainage_held_to_date
            rows.append({
                'contract': con,
                'property': (con.project.name if con.project else con.title),
                'stage_text': project_stage(con.project) if con.project else '—',
                'pipeline': _contract_pipeline(con),
            })
        # overdue = balance due on this customer's overdue invoices
        overdue = 0.0
        invs = (Invoice.query
                .filter_by(user_id=current_user.id, customer_id=cu.id).all())
        for inv in invs:
            if inv.deadline_status == 'overdue':
                overdue += inv.balance_due
        totals['overdue'] = overdue
        for k in grand:
            grand[k] += totals.get(k, 0.0)
        cards.append({'customer': cu, 'rows': rows, 'totals': totals})
    return {'cards': cards, 'grand': grand, 'stages': PIPELINE_STAGES}


@program_bp.route('/')
@login_required
def index():
    return render_template('program/index.html', data=program_data())
