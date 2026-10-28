"""Job activity feed (v1).

Assembles a single, time-sorted timeline of what has happened on one job from
records already loaded on the Project (invoices, proposals, payments, expenses,
work logs, files, notes). Read-only: no new model, migration, or queries — the
project_detail route already eager-loads every relationship used here.
"""
from datetime import datetime, date, time

from flask import url_for


def _dt(value):
    """Normalize a date/datetime to a datetime for sorting; None stays None.
    datetime is a subclass of date, so check it first."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return None


def _money(amount):
    return "${:,.0f}".format(amount or 0)


def build_job_activity(project, limit=15):
    """Return up to `limit` activity events for a job, newest first.

    Each event is a dict: {when, kind, icon, label, detail, url}.
    Events without a usable date are skipped so sorting stays well-defined.
    """
    events = []

    def add(when, kind, icon, label, detail=None, url=None):
        dt = _dt(when)
        if dt is None:
            return
        events.append({
            'when': dt, 'kind': kind, 'icon': icon,
            'label': label, 'detail': detail, 'url': url,
        })

    # Invoices
    for inv in getattr(project, 'invoices', []):
        label = "Invoice {}".format(inv.number or inv.title or '').strip()
        detail = "{} · {}".format(_money(inv.total), inv.status or 'draft')
        add(inv.created_at, 'invoice', 'receipt_long', label, detail,
            url=url_for('invoices.edit', invoice_id=inv.id))

    # Proposals (quotes)
    for q in getattr(project, 'quotes', []):
        add(q.created_at, 'proposal', 'description',
            "Proposal: {}".format(q.title or 'Untitled'), _money(q.total),
            url=url_for('quotes.edit', quote_id=q.id))

    # Payments (labor)
    for p in getattr(project, 'payments', []):
        who = p.worker.name if getattr(p, 'worker', None) else None
        detail = _money(p.amount) + (" · {}".format(who) if who else "")
        add(p.payment_date, 'payment', 'paid', "Payment recorded", detail)

    # Expenses
    for e in getattr(project, 'expenses', []):
        desc = e.description or e.category or "Expense"
        add(e.date, 'expense', 'trending_down', "Expense logged",
            "{} · {}".format(_money(e.amount), desc))

    # Work logs
    for w in getattr(project, 'work_logs', []):
        who = w.worker.name if getattr(w, 'worker', None) else "crew"
        bits = who
        if w.days_worked:
            bits += " · {:g} day{}".format(w.days_worked, "" if w.days_worked == 1 else "s")
        add(w.start_date, 'work', 'assignment', "Work logged", bits)

    # Documents / files
    for f in getattr(project, 'files', []):
        add(f.upload_date, 'file', 'folder', "Document uploaded", f.filename)

    # Notes
    for n in getattr(project, 'notes', []):
        snippet = (n.content or '').strip()
        if len(snippet) > 80:
            snippet = snippet[:77] + "…"
        add(n.created_at, 'note', 'sticky_note_2', "Note added", snippet)

    events.sort(key=lambda ev: ev['when'], reverse=True)
    return events[:limit]
