"""Signature Audit Log (Feature 8, Step 5b).

Account-wide, read-only view of every e-signature event (approvals and
declines) on this account's quotes and change orders. Open to both office
roles — owner and admin (foreman) — via @login_required; deliberately NOT
owner-only, so foremen can see the approval trail too.

Scoping: events are matched back to their source document and filtered to the
current user's own quotes / change orders, consistent with every other list
page in the app.
"""

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user

from models import SignatureEvent, Quote, ChangeOrder

audit_bp = Blueprint('audit', __name__, url_prefix='/audit')

PAGE_SIZE = 100


@audit_bp.route('/signatures')
@login_required
def signatures():
    # Ids of the current account's own documents.
    quote_ids = {q.id for q in Quote.query
                 .filter_by(user_id=current_user.id).with_entities(Quote.id)}
    co_ids = {c.id for c in ChangeOrder.query
              .filter_by(user_id=current_user.id).with_entities(ChangeOrder.id)}

    # Optional filters.
    f_type = request.args.get('doc_type') or ''
    f_action = request.args.get('action') or ''

    q = SignatureEvent.query
    if f_type in ('quote', 'change_order'):
        q = q.filter(SignatureEvent.doc_type == f_type)
    if f_action in ('approved', 'declined'):
        q = q.filter(SignatureEvent.action == f_action)
    q = q.order_by(SignatureEvent.created_at.desc())

    page = max(request.args.get('page', 1, type=int) or 1, 1)
    pagination = q.paginate(page=page, per_page=PAGE_SIZE, error_out=False)

    # Keep only events whose source document belongs to this account, and
    # attach a title + link for display. (Cheap: page is capped at PAGE_SIZE.)
    quote_by_id = {q.id: q for q in Quote.query
                   .filter(Quote.id.in_(quote_ids)).all()} if quote_ids else {}
    co_by_id = {c.id: c for c in ChangeOrder.query
                .filter(ChangeOrder.id.in_(co_ids)).all()} if co_ids else {}

    rows = []
    for e in pagination.items:
        if e.doc_type == 'quote' and e.doc_id in quote_by_id:
            doc = quote_by_id[e.doc_id]
            rows.append(dict(event=e, kind='Proposal',
                             label=doc.title,
                             endpoint='quotes.edit', arg={'quote_id': doc.id}))
        elif e.doc_type == 'change_order' and e.doc_id in co_by_id:
            doc = co_by_id[e.doc_id]
            rows.append(dict(event=e, kind='Change order',
                             label=f'{doc.number or ""} · {doc.title}'.strip(' ·'),
                             endpoint='change_orders.edit',
                             arg={'change_order_id': doc.id}))
        # events for docs not owned by this account are skipped

    return render_template('signature_audit.html', rows=rows,
                           pagination=pagination,
                           f_type=f_type, f_action=f_action)
