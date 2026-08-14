"""Shared role-permission helpers (Phase 8 finer gating).

Kept dependency-free (only flask + flask_login) so any blueprint can import it
without a circular import back to app.py.
"""

from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user


def owner_required(view):
    """Restrict a route to Owner accounts. Admin (foreman) users are bounced
    home with a message. Used for user management and deleting/voiding
    financial records."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_owner', False):
            flash('That action is owner-only.', 'error')
            return redirect(url_for('home'))
        return view(*args, **kwargs)
    return wrapped
