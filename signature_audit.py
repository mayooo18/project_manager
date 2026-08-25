"""E-signature audit trail (Feature 8).

One immutable log across quotes and change orders, plus the intent-to-sign
consent wording shown to signers. Kept dependency-light so any blueprint can
import it without a circular import back to app.py.

NOTE: the consent wording below is a reasonable UETA/ESIGN default, not legal
advice. Swap CONSENT_TEXT for your counsel's exact language if needed.
"""

from flask import request

from extensions import db
from models import SignatureEvent

CONSENT_TEXT = (
    "By typing my name and signing below, I agree that this constitutes my "
    "legal electronic signature and that I intend to be bound by this document."
)


def _client_ip():
    """Best-effort client IP. On Render (and most proxies) the real client is
    the first hop in X-Forwarded-For; fall back to remote_addr."""
    fwd = request.headers.get('X-Forwarded-For', '')
    return (fwd.split(',')[0].strip() if fwd else request.remote_addr) or ''


def record_signature_event(doc_type, doc_id, action, signer_name=None,
                           decline_reason=None):
    """Append an immutable audit row. Adds to the session but does not commit —
    the calling route commits alongside the document status change."""
    event = SignatureEvent(
        doc_type=doc_type,
        doc_id=doc_id,
        action=action,
        signer_name=signer_name,
        signer_ip=_client_ip(),
        consent_text=CONSENT_TEXT if action == 'approved' else None,
        decline_reason=decline_reason,
    )
    db.session.add(event)
    return event


def latest_event(doc_type, doc_id, action='approved'):
    """Most recent audit event for a document (default: the approval), or None."""
    return (SignatureEvent.query
            .filter_by(doc_type=doc_type, doc_id=doc_id, action=action)
            .order_by(SignatureEvent.created_at.desc())
            .first())


def events_for(doc_type, doc_id):
    """All audit events for one document, newest first."""
    return (SignatureEvent.query
            .filter_by(doc_type=doc_type, doc_id=doc_id)
            .order_by(SignatureEvent.created_at.desc())
            .all())
