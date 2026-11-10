"""
Owner sign-alert notifications.

When a customer e-signs a proposal, contract, or change order, email the owner
so they find out immediately instead of having to open the app. Sends through
the same Gmail integration used elsewhere (google_routes.get_credentials).

Design notes:
- Fail soft. A notification must NEVER break the signing flow — the customer's
  signature is already committed by the time we try to email. Every public
  caller wraps notify_signed() so an email failure is logged, not raised.
- Recipient is Config.SIGN_NOTIFY_EMAIL, falling back to COMPANY['email'].
- Kept in its own file per the project's "new features in separate files" rule;
  nothing here imports back into the signing modules at import time.
"""

import base64
from email.mime.text import MIMEText

from flask import current_app, url_for


def _format_money(amount):
    try:
        return f"${float(amount or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _describe(kind, obj):
    """Return (label, title, amount, signer, customer_name, edit_endpoint).

    edit_endpoint is an owner-side page to deep-link to, or None.
    """
    customer = getattr(obj, 'customer', None)
    customer_name = getattr(customer, 'name', None) or 'a customer'
    signer = getattr(obj, 'signature_name', None) or customer_name

    if kind == 'quote':
        title = getattr(obj, 'title', '') or 'Proposal'
        return ('Proposal approved', title, getattr(obj, 'total', 0),
                signer, customer_name, ('quotes.edit', 'quote_id'))
    if kind == 'contract':
        number = getattr(obj, 'number', None)
        title = getattr(obj, 'title', '') or 'Contract'
        label = f"Contract {number} accepted" if number else 'Contract accepted'
        return (label, title, getattr(obj, 'contract_total', 0),
                signer, customer_name, ('contracts.edit', 'contract_id'))
    if kind == 'change_order':
        number = getattr(obj, 'number', None)
        title = getattr(obj, 'title', '') or 'Change order'
        label = (f"Change Order {number} approved" if number
                 else 'Change order approved')
        return (label, title, getattr(obj, 'total', 0),
                signer, customer_name, None)
    return ('Document signed', getattr(obj, 'title', '') or 'Document',
            0, signer, customer_name, None)


def _build_link(edit_endpoint, obj):
    if not edit_endpoint:
        return None
    endpoint, arg = edit_endpoint
    try:
        return url_for(endpoint, _external=True, **{arg: obj.id})
    except Exception:  # noqa: BLE001 — a missing endpoint must not block the alert
        return None


def _recipient():
    from quote_routes import COMPANY
    return current_app.config.get('SIGN_NOTIFY_EMAIL') or COMPANY['email']


def notify_signed(kind, obj):
    """Email the owner that `obj` (a Quote / Contract / ChangeOrder) was signed.

    Returns (ok, message). Never raises for an email/credentials problem.
    """
    try:
        from googleapiclient.discovery import build as gbuild
        from google_routes import get_credentials

        label, title, amount, signer, customer_name, edit_endpoint = \
            _describe(kind, obj)

        creds = get_credentials()
        if not creds:
            current_app.logger.warning(
                'sign-alert skipped: Google account not connected '
                '(GOOGLE_REFRESH_TOKEN missing).')
            return False, 'Google account not connected.'

        link = _build_link(edit_endpoint, obj)
        lines = [
            f"{label}.",
            "",
            f"Customer: {customer_name}",
            f"Signed by: {signer}",
            f"Item: {title}",
            f"Amount: {_format_money(amount)}",
        ]
        if link:
            lines += ["", f"Open it: {link}"]
        body = "\n".join(lines)

        msg = MIMEText(body)
        msg['To'] = _recipient()
        msg['From'] = 'me'
        msg['Subject'] = f"✓ {label}: {customer_name}"

        gmail = gbuild('gmail', 'v1', credentials=creds)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        gmail.users().messages().send(userId='me', body={'raw': raw}).execute()
        return True, f"Sign alert sent to {msg['To']}."
    except Exception as exc:  # noqa: BLE001 — never break the signing flow
        try:
            current_app.logger.exception('sign-alert email failed: %s', exc)
        except Exception:  # noqa: BLE001
            pass
        return False, f'Sign alert failed: {exc}'
