# Batch 3 — Tabbed Job Hub: implementation handoff

Resume this in a fresh session. The plan is approved; only execution remains.
Target file: `templates/jobs/detail.html` (currently one long scroll, 636 lines, 35 forms).
Scope: **client-side tabs only** — no backend/route changes. Build in **vanilla JS** (project rule: NO React).

## Goal
Reorganize the job detail page into 5 tabs under a persistent header, matching
CONTEXT.md: Overview / Financials / Documents / Field & Compliance / Crew & Tasks.
Move markup only — do NOT edit any `<form>` internals, action URLs, CSRF tokens,
confirmations, or conditionals.

## Persistent header (stays above the tabs, not inside a panel)
- Job name, status pill, customer/address/start (lines ~50–85).
- Condensed KPIs: Contract · Billed · Paid · Profit (from the money snapshot, lines 87–97).
- Actions: Edit job, File documents, Close out. **Delete job** in a clearly-labeled
  danger area, keeping its existing confirm dialog.

## Section → tab map (current line ranges in jobs/detail.html)
- **Overview**: progress bars card (~99–117), activity feed include (118), client portal card (202–254).
- **Financials**: full money snapshot (87–97) + expenses-by-category (120–130) + Money entries
  forms (132–200) + Sales & Billing card (258–294). Estimates control lives in the Field card
  today (`estimates.new`/`estimates.edit`, ~519) — move it here.
- **Documents**: Files list + upload/delete (`upload_file`, `edit_file`, `delete_file`, ~560–608)
  and the File-documents action.
- **Field & Compliance**: the big card (296–558): permits/inspections (`add_project_permit`,
  `permits.add/edit`, ~539), lot releases (`lot_releases.*`, ~307–338), hold points + photos
  (`hold_points.*`, 339–420), **closeout/punch list** (`closeout.*`, 426–450), **warranty** calls
  + photos (`warranty.*`, 468–510). KEEP closeout + warranty here (explicit decision).
- **Crew & Tasks**: Crew tasks card (608–636: `add_task`, `delete_task`) + work logs/records.

## Implementation steps
1. Add a sticky tab bar in the header and 5 `<div class="jobtab" data-tab="...">` panels.
   Tab bar scrolls horizontally on mobile; active tab marked with the orange accent.
2. Move each section group (above) into its panel. Mechanical cut/paste — no form edits.
   Watch nested `{% if %}`/`{% for %}` boundaries (portal conditional, lot-release conditional,
   `twocol` wrapper at 256 splits Sales & Billing vs Field — they go to DIFFERENT tabs now).
3. Tab switching: ~20 lines vanilla JS. Pick active tab from `location.hash` (e.g. #financials),
   else `localStorage['jobtab:'+projectId]`, else Overview. On tab click, update both. This
   matters because most forms POST→redirect back to `project_detail` with no hash — persistence
   keeps the user on their tab after an action.
4. Mobile: panels stack full-width; sticky tab bar; big touch targets (reuse existing styles).

## Verification (must do)
- Endpoint baseline saved at: `scratchpad/jobhub_endpoints_before.txt` (60 lines). After the
  refactor run `grep -oE "url_for\('[^']+'" templates/jobs/detail.html | sort` and diff — it
  MUST match exactly (no form lost). (Regenerate the baseline from git if the scratchpad is gone:
  `git show HEAD:templates/jobs/detail.html | grep -oE "url_for\('[^']+'" | sort`.)
- Render the page logged in (test_client with `sess['_user_id']='1'`, or the live app) and confirm
  all 5 tabs show their sections.
- Spot-check 2 real submits (e.g. add expense, toggle a punch item) still work.
- Check mobile (375px): tab bar scrolls, panels stack, and the active tab persists across a submit.

## Context
- Dev server: `python3 run_local.py` → http://localhost:5001 (NOT `-I`; cwd must be on path).
- Login: `admin` / see `DEV_LOGIN.txt` (gitignored).
- Flask-Limiter caps 200 req/hour per process; restart the server to reset if you hit 429.
- Workflow: branch off main, show changes, commit with the Co-Authored-By trailer, then PR on request.
