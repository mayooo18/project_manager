# Phase 4 — Change Orders (implementation brief for Codex)

You are extending an existing Flask app (Optimal SES, a general contractor). Phases 1–3
are done and in `main`. Implement **Phase 4: Change Orders**, following the exact
patterns already in the repo. Do **not** rewrite or refactor existing working code.

## Stack & repo rules (from CLAUDE.md — obey these)
- Flask + SQLAlchemy + PostgreSQL, Jinja2 templates, Tailwind (via CDN in page
  templates), vanilla JS, Flask-Login, deployed on Render. **No React.**
- One feature = its own Blueprint in its own file. Add to `models.py`, never remove.
- All secrets via `os.environ` only. Register blueprints in `app.py` only.
- Keep new templates under `templates/change_orders/`.

## Local dev
- Run: `python run_local.py` (serves on `http://localhost:5001`; templates are cached,
  so **restart after template edits**). Global `python3` has all deps.
- DB is **Postgres** via `DATABASE_URL` in `.env`. `SECRET_KEY=test python3 ...` works for
  one-off scripts.

## What a Change Order is (domain)
A priced amendment to a signed contract. It can **add** scope (positive) or be a
**deduction/credit** (negative). **The client must e-sign to approve it.** Only a
**signed** change order changes the contract total — until signed, nothing moves.
States: `draft → sent → approved` (or `declined`).

---

## Existing architecture you must reuse (do not duplicate)

### Models (`models.py`) — mirror these exactly
- `Customer(id, user_id FK user, name, email, phone, address, notes, created_at)`
- `Quote` / `QuoteItem` — the e-sign + public-link reference implementation.
  `Quote` has: `user_id, customer_id, project_id, title, status, notes, total,
  deposit, po_number, public_token, public_token_expires_at, public_token_revoked_at,
  signature_name, signature_data, signed_at, created_at, sent_at`. `QuoteItem` has
  `description, quantity, unit_price` + `line_total` property.
- `Invoice` / `InvoiceItem` — has `contract_id` FK (Phase 3 link).
- **`Contract`** (`contract` table): `id, user_id, customer_id, project_id, quote_id,
  number, title, contract_total, retainage_percent, status['draft'|'active'|'completed'],
  notes, created_at`. Relationship `draws`. Properties: `scheduled_total,
  billed_to_date, paid_to_date, remaining_to_bill, retainage_amount`.
- **`ContractDraw`** (`contract_draw`): `id, contract_id, sequence, description, amount,
  status['pending'|'invoiced'|'paid'], invoice_id`. Properties `is_billed`, `is_paid`.

### Blueprints (registered in `app.py`)
`quote_bp (/quotes)`, `invoice_bp (/invoices)`, `contract_bp (/contracts)`.

### Shared helpers to IMPORT (don't reimplement)
From `quote_routes.py`:
- `COMPANY` — dict with `name, address_line1, address_line2, phone, email, doc_title, footer`
  (Optimal SES letterhead).
- `LOGO_PATH` — path to the logo PNG for PDFs.
- `_pdf_text(value, max_length=5000, preserve_newlines=False)` — escapes untrusted text
  before passing to ReportLab. **Always** run stored text through this in PDFs.
- `_validated_signature_data(value)` — validates a base64 PNG data-URL signature and
  returns a normalized value or `None`. Use this on the public approve endpoint.
- `_parse_items(form)` — reads parallel `item_description[]/item_quantity[]/item_price[]`
  arrays into dicts `{description, quantity, unit_price}`.
From `invoice_routes.py`: `_new_invoice_token()`, `_next_number()` (if you create draws
that get billed later — you don't need to bill inside Phase 4, the contract's existing
"Bill this draw" handles it).

### Conventions (match these precisely)
- **Ownership:** every customer-facing row has `user_id`; all queries filter by
  `current_user.id`; use an `_owned_change_order_or_404(id)` helper like the others.
- **Public tokenized links:** `public_token` (unique), `public_token_expires_at`
  (default `datetime.utcnow()+timedelta(days=30)`, not null), `public_token_revoked_at`
  (nullable). Public routes are rate-limited: `from extensions import db, limiter` and
  decorate with `@limiter.limit("60 per minute")` (view) / `"5 per minute"` (approve) /
  `"10 per minute"` (pdf), exactly like `quote_routes.py`.
- **E-signature:** the public page reuses `static/js/signature.js` and the same canvas
  markup as `templates/quotes/public.html` (a `<canvas id="sigpad">`, hidden inputs
  `signature_name` and `signature_data`, `onsubmit="return prepareSignature();"`).
- **CSRF:** every POST form (including on public pages) includes
  `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`.
- **Templates:** extend `base.html`; inside `{% block content %}` render a full doc that
  loads Tailwind via
  `<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>`.
  Dark theme: black bg, accent `#ff6b35`, `gray-900` cards. Reuse the `.fld` and `.sec`
  CSS classes from `templates/quotes/form.html`. **Note:** `base.html` itself uses a
  purged `main.css` (NOT the Tailwind CDN), so nav/base styling must not rely on Tailwind
  utility classes.
- Green action buttons may render orange due to a global button style in `main.css` —
  that's a known cosmetic quirk, not a bug; don't chase it.

---

## Phase 4 deliverables

### 1. Models — add to `models.py`
```python
class ChangeOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey('contract.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)

    number = db.Column(db.String(50))          # e.g. "CON-0001-CO1"
    title = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.Text)                # why the change is needed
    status = db.Column(db.String(20), default='draft', nullable=False)  # draft/sent/approved/declined
    total = db.Column(db.Float, default=0.0)   # sum of items; negative = deduction/credit
    notes = db.Column(db.Text)

    # Whether, on approval, to append a billable ContractDraw for this CO amount.
    add_as_draw = db.Column(db.Boolean, default=True)

    # Audit snapshot captured when applied to the contract (no ALTER on contract needed).
    applied_at = db.Column(db.DateTime)
    contract_total_before = db.Column(db.Float)
    contract_total_after = db.Column(db.Float)

    # Public link + e-signature (mirror Quote)
    public_token = db.Column(db.String(64), unique=True, nullable=False)
    public_token_expires_at = db.Column(
        db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=30), nullable=False)
    public_token_revoked_at = db.Column(db.DateTime)
    signature_name = db.Column(db.String(150))
    signature_data = db.Column(db.Text)
    signed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime)

    contract = db.relationship('Contract', backref='change_orders')
    customer = db.relationship('Customer')
    items = db.relationship('ChangeOrderItem', back_populates='change_order',
                            cascade='all, delete-orphan', order_by='ChangeOrderItem.id')

    def recalculate_total(self):
        self.total = sum((i.line_total or 0) for i in self.items)
        return self.total

class ChangeOrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    change_order_id = db.Column(db.Integer, db.ForeignKey('change_order.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    quantity = db.Column(db.Float, default=1.0)
    unit_price = db.Column(db.Float, default=0.0)   # may be negative for deductions
    change_order = db.relationship('ChangeOrder', back_populates='items')

    @property
    def line_total(self):
        return (self.quantity or 0) * (self.unit_price or 0)
```
`datetime` and `timedelta` are already imported at the top of `models.py`.

### 2. Blueprint — new file `change_order_routes.py`
`change_order_bp = Blueprint('change_orders', __name__, url_prefix='/change-orders')`.
Import shared helpers from `quote_routes`. Routes:

- `POST /contracts/<contract_id>/change-orders/new` **and** `GET/POST /change-orders/<id>/edit`
  — builder. New COs are created **in the context of a contract** (contract_id fixed;
  customer_id inherited from the contract). Number = `f"{contract.number}-CO{len(contract.change_orders)+1}"`.
  Line items via `_parse_items(request.form)`; also read `add_as_draw` checkbox, `reason`,
  `notes`, `title`. Call `recalculate_total()`.
  - (Provide a `GET /change-orders/new?contract_id=..` entry from the contract page, or a
    button `POST /contracts/<id>/change-orders/new`; either is fine — keep it consistent
    with how `contract_routes.from_quote` is triggered.)
- `POST /change-orders/<id>/delete`
- `POST /change-orders/<id>/send` — `status='sent'`, set `sent_at`, refresh public link if
  inactive (mirror `invoice_routes.send`). Flash the public link.
- `POST /change-orders/<id>/email` — reuse the Gmail send pattern (`send_quote_email` /
  `send_invoice_email` in the repo). Add `templates/change_orders/email.html`.
- `GET /change-orders/<id>/pdf` — `build_change_order_pdf` (below).
- **Public (no login):**
  - `GET /co/<token>` — public view + signature pad (mirror `templates/quotes/public.html`).
  - `POST /co/<token>/approve` — validate name + `_validated_signature_data(...)`. On
    success: set `signature_*`, `signed_at`, `status='approved'`, then **apply once**
    (guard on `applied_at is None`):
    ```python
    co.contract_total_before = co.contract.contract_total or 0
    co.contract.contract_total = (co.contract.contract_total or 0) + co.total
    co.contract_total_after = co.contract.contract_total
    co.applied_at = datetime.utcnow()
    if co.add_as_draw and co.total > 0:
        seq = len(co.contract.draws)
        co.contract.draws.append(ContractDraw(
            sequence=seq, description=f"Change Order {co.number}: {co.title}",
            amount=co.total, status='pending'))
    if co.contract.status == 'draft':
        co.contract.status = 'active'
    ```
    (For a negative CO, don't add a draw — the total simply decreases.)
  - `GET /co/<token>/pdf`.
- Ownership helper `_owned_change_order_or_404(id)` filtering by `current_user.id`.
- Public token helpers: replicate `_new_*_token` / `_public_link_is_active` /
  `_refresh_public_link` / `_get_public_*` for change orders (they query the CO table).

### 3. `build_change_order_pdf(change_order)`
Copy the structure of `build_invoice_pdf` / `build_contract_pdf`. Title `CHANGE ORDER`.
Show: `CHANGE ORDER # <number>`, `DATE`, the parent contract number; a Description|Amount
table of the CO items with the CO total (label it "Change Order Total"; show a leading
"−" for negatives); a line "Original contract: $X → New contract total: $Y" (use
`contract_total_before/after` if applied, else compute preview); the `reason`/`notes`; and
a Client/Contractor signature block. If `signed_at`, embed the signature image (see how
`build_quote_pdf` renders `signature_data`).

### 4. Templates (`templates/change_orders/`)
- `list.html` (optional top-level list) — mirror `templates/contracts/list.html`.
- `form.html` — mirror `templates/invoices/form.html`: section 1 read-only contract +
  customer context; section 2 line items editor (reuse the JS from
  `templates/quotes/form.html`, incl. **"✦ Suggest with AI"** pointing to
  `url_for('quotes.suggest')`); allow negative unit prices; a checkbox for `add_as_draw`;
  a live total that shows "Deduction/Credit" when negative and previews
  "New contract total = current + this CO". After save: a Send/share panel (email button +
  copy public link) exactly like the invoice form. Show approval state if `signed_at`.
- `public.html` — mirror `templates/quotes/public.html`: read-only CO summary + the
  signature pad + "Sign to approve." After signing, show ✓ Approved with the signature and
  the resulting new contract total. Include `<script src="{{ url_for('static', filename='js/signature.js') }}"></script>`.
- `email.html` — mirror `templates/invoices/email.html`.

### 5. Wire-up
- `app.py`: `from change_order_routes import change_order_bp` and
  `app.register_blueprint(change_order_bp)` (next to the others).
- `templates/base.html`: this is optional — COs live under a contract. Prefer surfacing
  them on the **contract edit page** (`templates/contracts/form.html`): add a
  "Change Orders" panel listing `contract.change_orders` (number, title, ± amount, status,
  links to edit/PDF/public) and a **"+ New change order"** button. If you also add a nav
  link, append the CO endpoints to `sales_endpoints` in `base.html` and add a
  `<a>` in the Sales dropdown, matching the existing Proposals/Contracts/Invoices entries.

### 6. Migration / deploy
Phase 4 adds **only new tables** (`change_order`, `change_order_item`) and **no columns on
existing tables** (the audit snapshot lives on the CO). So deploy on Render is just:
```
python quick_init.py
```
No `migrate_*.py` needed. (Locally, `SECRET_KEY=test python3 -c "import app; from extensions import db;\nwith app.app.app_context(): db.create_all()"` creates the tables.)

---

## Acceptance criteria (verify end-to-end)
1. From a contract, create a change order with line items; total computes (supports
   negatives). Save works; CO gets number `CON-XXXX-COn`.
2. Send → public `/co/<token>` shows the CO and a signature pad. Approving with a typed
   name + drawn signature sets `status=approved`, stores the signature, and **increments
   the contract's `contract_total` by the CO total exactly once** (re-approve is a no-op).
3. With `add_as_draw` on and a positive CO, a new **pending ContractDraw** appears in the
   contract's draw schedule for the CO amount, billable via the existing "Bill this draw".
4. A negative CO reduces the contract total and adds no draw.
5. Change-order PDF renders (valid `%PDF-` header) and shows before→after totals; signed
   COs embed the signature.
6. Email-to-customer works via the existing Gmail integration.
7. Everything is scoped by `user_id`; public routes are rate-limited; unsigned COs never
   change the contract total.

## Out of scope for v1 (note, don't build)
- Requiring a deposit on the CO before work starts (owner may want this later; leave a
  TODO).
- Formal AIA G701 change-order form layout (simple PDF is fine for now).
