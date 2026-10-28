# Template organization

Templates are grouped by feature. Keep related list, detail, edit, form, public, and email templates together.

- `base.html` is the shared internal application shell.
- `partials/` contains reusable template fragments.
- Feature templates extend `base.html` where appropriate. Public documents, crew pages, sign-in screens, and emails can keep their specialized layout.
- Python `render_template()` calls use paths relative to this directory; update those calls whenever moving a template.
- Folder names do not change public URLs or route endpoint names.

## Current folders

- `admin/`: `activity_log.html`, `signature_audit.html`, `users.html`
- `ai/`: `history.html`
- `auth/`: `login.html`
- `change_orders/`: `email.html`, `form.html`, `public.html`
- `contracts/`: `combine.html`, `email.html`, `form.html`, `list.html`, `public.html`
- `crew/`: `home.html`, `login.html`
- `customers/`: `detail.html`, `index.html`
- `dashboard/`: `index.html`
- `documents/`: `document.html`, `form.html`
- `estimates/`: `edit.html`
- `expenses/`: `edit.html`, `index.html`
- `files/`: `edit.html`
- `income/`: `edit.html`, `index.html`
- `invoices/`: `email.html`, `form.html`, `list.html`, `packet.html`, `public.html`, `receipt_email.html`
- `jobs/`: `detail.html`, `edit.html`, `index.html`
- `licenses/`: `form.html`, `index.html`
- `lot_releases/`: `form.html`, `public.html`
- `partials/`: `status_tabs.html`
- `payments/`: `edit.html`, `index.html`
- `payroll/`: `index.html`
- `permits/`: `form.html`, `index.html`
- `portal/`: `email.html`, `index.html`
- `profitability/`: `index.html`
- `program/`: `index.html`
- `quotes/`: `email.html`, `form.html`, `list.html`, `public.html`
- `reminders/`: `index.html`
- `reports/`: `edit.html`, `index.html`
- `subcontractors/`: `form.html`, `index.html`
- `sworn/`: `form.html`
- `timeclock/`: `index.html`
- `vehicles/`: `form.html`, `index.html`
- `waivers/`: `form.html`, `index.html`
- `work_logs/`: `edit.html`, `index.html`
- `workers/`: `edit.html`, `index.html`

## Scope of this cleanup

Forty existing templates were moved without changing their contents. Existing grouped document workflows were retained; customer pages were separated from proposals. Backend modules and database scripts remain in the project root. The visual UI redesign is still pending.
