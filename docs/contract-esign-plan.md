# Plan: Contract Acceptance / E-Signature

**Status:** planned, not started (saved 2026-10-22)

## Why
When a customer signs a **proposal**, they agree to the **scope + total** only.
The **payment terms — the draw schedule** (e.g. 50% deposit / 50% on completion),
retainage, and any contract-level notes — are added on the **contract**, *after*
the proposal is signed. So today the customer never formally agrees to *how/when*
they pay. This feature makes the **contract** a customer-accepted, provable
agreement that includes the payment schedule.

Mirrors the e-sign flow proposals (`/q/<token>`) and change orders already use —
~80% of the code can be reused.

## Status flow
Current: `draft → active → completed`
New:     `draft → sent → accepted → active → completed`
- `sent` — contract sent to customer for signature
- `accepted` — customer e-signed; now binding
- Gate: only an `accepted` contract should move to `active` / allow billing a draw
  (warn or block if billing before acceptance).

## Model changes (`models.py` — additive, needs migration)
Add to `Contract` (mirror `Quote` fields):
- `public_token` (String(64), unique) + `public_token_expires_at` + `public_token_revoked_at`
- `signature_name` (String(150)), `signature_data` (Text, base64 data-URL), `signed_at` (DateTime)
- `sent_at` (DateTime)

No change needed to the e-signature audit model: `signature_audit.record_signature_event`
takes a generic `doc_type`, so pass `doc_type='contract'`.

## Migration
- `quick_init.py`: add idempotent ALTERs for the new `contract` columns (same
  pattern as `quote.revision_of_id`). `public_token` must be backfilled —
  generate a token for every existing contract row (don't add a NOT NULL unique
  column without backfilling). Simplest: add nullable, then generate tokens for
  rows where it's null.
- Reminder: Render runs gunicorn, so `db.create_all()` won't add columns —
  `quick_init.py` must run on deploy.

## Routes (`contract_routes.py`) — mirror `quote_routes.py`
- `POST /contracts/<id>/send` — ensure `public_token`, set `status='sent'`, `sent_at`;
  optionally email the customer a public accept link (reuse email machinery).
- `GET /c/<token>` — public, tokenized contract view (no login): header, scope of
  work, total, **draw schedule / payment terms**, retainage, notes + a signature pad.
- `POST /c/<token>/accept` — capture `signature_name` + `signature_data`, set
  `signed_at`, `status='accepted'`; call `record_signature_event('contract', id, 'approved', …)`.
- `POST /contracts/<id>/revoke_public_link` and `/regenerate_public_link` — mirror quotes.
- Reuse `_validated_signature_data` from `quote_routes` for the signature payload.

## Templates
- `templates/contracts/public.html` — customer-facing accept page + signature pad
  (reuse the proposal's signature-pad JS).
- `templates/contracts/form.html` + `list.html` — status pill (`sent`/`accepted`),
  a **"Send for signature"** button, and a "✓ Accepted by X on <date>" line once signed.
- `build_contract_pdf` (`contract_routes.py`) — add a signature block showing signer
  name + date when signed (like the proposal / change-order PDFs).

## Retention — the signed contract must be retrievable later
A core requirement: once accepted, the e-signed contract can always be brought
up again (disputes, records, audits). Covered by:
- The **signature is stored permanently** on the Contract row
  (`signature_name`, `signature_data` base64 image, `signed_at`).
- Each signing writes an **immutable `ESignatureEvent`** (the signature audit log).
- The **signed PDF is reproducible on demand** — regenerated from the frozen
  contract data (scope/total/draws are already snapshotted and don't change with
  later proposal edits) plus the stored signature, with the signature block shown.
  No separate file storage needed; it always rebuilds exactly what was signed.

## Audit / signature log
- Already generic: `record_signature_event`, `latest_event`, `events_for` take
  `doc_type` — use `'contract'`. The existing Signature Log page (audit routes)
  should then include contracts automatically, or with a small doc-type label add.

## Build order (one step at a time, show before applying)
1. Model fields + `quick_init.py` migration (with token backfill).
2. `send` route + "Send for signature" button + status pill.
3. Public `/c/<token>` view + `accept` route + signature pad template.
4. PDF signature block.
5. Gate `active`/billing on `accepted`.
6. Verify locally, then branch → PR → merge → deploy (run `quick_init.py` on Render).

## Effort
Medium. Most of the work is reuse from the proposal e-sign flow.
