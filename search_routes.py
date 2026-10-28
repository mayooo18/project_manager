"""Global search — v1.

A single top-bar query searches Jobs, Customers, Proposals and Invoices and
renders a grouped results page. Kept in its own blueprint/file per project rules.

Scoping note: Project (Jobs) has no user_id in this app, so job results are
org-wide — consistent with the existing dashboard/jobs list. Customers, Quotes
and Invoices are scoped to the current user, matching their list pages.
"""
from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import or_

from models import Project, Customer, Quote, Invoice

search_bp = Blueprint('search', __name__, url_prefix='/search')

# Max rows returned per entity group.
PER_GROUP = 10
# Minimum query length before we run a search.
MIN_LEN = 2


def _pattern(q):
    """Build a safe LIKE pattern: escape the LIKE wildcards in the user's text
    so a literal % or _ can't turn into a wildcard match."""
    escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


@search_bp.route('/')
@login_required
def index():
    q = (request.args.get('q') or '').strip()

    if len(q) < MIN_LEN:
        return render_template(
            'search/results.html',
            q=q, too_short=(len(q) > 0), total=0,
            jobs=[], customers=[], proposals=[], invoices=[],
        )

    like = _pattern(q)

    jobs = (Project.query
            .filter(or_(Project.name.ilike(like, escape='\\'),
                        Project.address.ilike(like, escape='\\')))
            .order_by(Project.name.asc())
            .limit(PER_GROUP).all())

    customers = (Customer.query
                 .filter(Customer.user_id == current_user.id)
                 .filter(or_(Customer.name.ilike(like, escape='\\'),
                             Customer.email.ilike(like, escape='\\'),
                             Customer.phone.ilike(like, escape='\\')))
                 .order_by(Customer.name.asc())
                 .limit(PER_GROUP).all())

    proposals = (Quote.query
                 .filter(Quote.user_id == current_user.id)
                 .filter(or_(Quote.title.ilike(like, escape='\\'),
                             Quote.po_number.ilike(like, escape='\\')))
                 .order_by(Quote.created_at.desc())
                 .limit(PER_GROUP).all())

    invoices = (Invoice.query
                .filter(Invoice.user_id == current_user.id)
                .filter(or_(Invoice.number.ilike(like, escape='\\'),
                            Invoice.title.ilike(like, escape='\\'),
                            Invoice.po_number.ilike(like, escape='\\')))
                .order_by(Invoice.created_at.desc())
                .limit(PER_GROUP).all())

    total = len(jobs) + len(customers) + len(proposals) + len(invoices)

    return render_template(
        'search/results.html',
        q=q, too_short=False, total=total,
        jobs=jobs, customers=customers, proposals=proposals, invoices=invoices,
    )
