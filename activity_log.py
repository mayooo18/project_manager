# activity_log.py
# Audit trail of office-user actions (Owner + Admin/Foreman).
#
# How it works: a single after_request hook records every *mutating* request
# (POST/PUT/PATCH/DELETE) made by a logged-in office user. This captures what
# each person does — creating jobs, editing payments, deleting records, adding
# workers, etc. — without touching any of the existing route files.
#
# What is NOT logged: plain page views (GET), crew/worker field actions, the
# customer portal, and the API blueprints (those authenticate differently and
# aren't office users). Failed requests (4xx/5xx) are skipped too.
from datetime import datetime

from flask_login import current_user

from extensions import db


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Who — snapshot the username/role at action time so the log stays readable
    # even if the account is later renamed, demoted, or deleted.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    username = db.Column(db.String(64), nullable=True)
    role = db.Column(db.String(20), nullable=True)

    # What — a human-readable label plus the raw request details for auditing.
    action = db.Column(db.String(120), nullable=False)   # "Recorded a payment"
    target = db.Column(db.String(80), nullable=True)     # "job #12"
    method = db.Column(db.String(10), nullable=True)
    path = db.Column(db.String(255), nullable=True)
    endpoint = db.Column(db.String(120), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)


# Requests that change data. GETs (page views) are ignored.
_MUTATING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

# Blueprints whose actions are NOT office-user activity (skip entirely).
_SKIP_BLUEPRINTS = {'field_api', 'google', 'portal', 'crew'}

# Endpoints to never log (auth noise / static).
_SKIP_ENDPOINTS = {'login', 'logout', 'static'}

# Curated readable labels for the actions worth naming precisely.
# Key = Flask endpoint name; value = what to show in the log.
_ACTION_LABELS = {
    # Jobs / projects
    'create_project': 'Created a job',
    'edit_project': 'Edited a job',
    'delete_project': 'Deleted a job',
    'upload_file': 'Uploaded a file',
    'add_task': 'Added a task',
    'add_note': 'Added a note',
    # Workers / time / pay
    'add_worker': 'Added a worker',
    'edit_worker': 'Edited a worker',
    'add_worklog': 'Logged work',
    'add_payment': 'Recorded a payment',
    'add_expense': 'Recorded an expense',
    'add_income': 'Recorded income',
    # User management
    'users': 'Created an admin account',
    'user_role': 'Changed a user role',
    'user_toggle_active': 'Activated/deactivated a user',
    # Sales blueprints
    'quotes.new': 'Created a proposal',
    'quotes.edit': 'Edited a proposal',
    'invoices.new': 'Created an invoice',
    'invoices.edit': 'Edited an invoice',
    'contracts.new': 'Created a contract',
    'contracts.edit': 'Edited a contract',
    # Compliance
    'permits.add': 'Added a permit',
    'permits.edit': 'Edited a permit',
    'licenses.add': 'Added a license',
    'subcontractors.add': 'Added a subcontractor',
    'waivers.new': 'Created a waiver/cert',
}

# Verbs inferred from the tail of an endpoint name when it's not in the map.
_VERB_HINTS = [
    ('delete', 'Deleted'), ('remove', 'Removed'), ('void', 'Voided'),
    ('create', 'Created'), ('new', 'Created'), ('add', 'Added'),
    ('edit', 'Edited'), ('update', 'Updated'), ('save', 'Saved'),
    ('toggle', 'Toggled'), ('approve', 'Approved'), ('send', 'Sent'),
    ('mark', 'Updated'), ('set', 'Updated'), ('upload', 'Uploaded'),
]

# View-arg keys that identify the affected record, in priority order.
_TARGET_KEYS = [
    ('project_id', 'job'), ('job_id', 'job'), ('worker_id', 'worker'),
    ('quote_id', 'proposal'), ('invoice_id', 'invoice'),
    ('contract_id', 'contract'), ('permit_id', 'permit'),
    ('license_id', 'license'), ('user_id', 'user'),
    ('payment_id', 'payment'), ('task_id', 'task'), ('id', 'record'),
]


def _humanize_endpoint(endpoint):
    """Fallback label for endpoints not in _ACTION_LABELS.
    e.g. 'subcontractors.delete' -> 'Deleted subcontractor'."""
    parts = endpoint.split('.')
    blueprint = parts[0] if len(parts) > 1 else None
    name = parts[-1]  # drop blueprint prefix
    verb = None
    for hint, word in _VERB_HINTS:
        if hint in name:
            verb = word
            name = name.replace(hint, '')
            break
    noun = name.strip('_').replace('_', ' ').strip()
    # If the action word left no noun (e.g. 'subcontractors.delete' -> ''),
    # fall back to the blueprint name so it still names the record type.
    if verb and not noun and blueprint:
        noun = blueprint.replace('_', ' ')
    if verb and noun:
        return f'{verb} {noun}'
    if verb:
        return verb
    # No verb hint: just present the cleaned endpoint name.
    return endpoint.replace('.', ' ').replace('_', ' ').strip().capitalize()


def _target_from_view_args(view_args):
    """Turn Flask view_args into a short 'job #12' style target string."""
    if not view_args:
        return None
    for key, noun in _TARGET_KEYS:
        if key in view_args:
            return f'{noun} #{view_args[key]}'
    return None


def _client_ip(request):
    """Real client IP, honoring Render's X-Forwarded-For proxy header."""
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr


def record_activity(request, response):
    """after_request hook. Records a row when a logged-in office user
    successfully performs a mutating action. Never raises — auditing must
    not break the request it is observing."""
    try:
        if request.method not in _MUTATING_METHODS:
            return response
        if not getattr(current_user, 'is_authenticated', False):
            return response
        # Office users only: they carry a 'role' of owner/admin. Crew/workers
        # authenticate through a different model and won't match.
        role = getattr(current_user, 'role', None)
        if role not in ('owner', 'admin'):
            return response
        # Only successful actions (a failed form submit didn't change data).
        if response.status_code >= 400:
            return response

        endpoint = request.endpoint or ''
        if endpoint in _SKIP_ENDPOINTS:
            return response
        blueprint = endpoint.split('.')[0] if '.' in endpoint else None
        if blueprint in _SKIP_BLUEPRINTS:
            return response

        action = _ACTION_LABELS.get(endpoint) or _humanize_endpoint(endpoint or request.path)

        entry = ActivityLog(
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            role=role,
            action=action,
            target=_target_from_view_args(request.view_args),
            method=request.method,
            path=request.path[:255],
            endpoint=endpoint[:120],
            ip_address=_client_ip(request),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:  # noqa: BLE001 — auditing must never break a request
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
    return response
