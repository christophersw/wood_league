# Analysis Scheduling UI + Recurrence — Design

**Status:** Draft (2026-05-18)
**Issue:** #155 — Sub-project B (layers on Sub-project A)
**Depends on:** `2026-05-18-vast-provisioning-design.md` (Sub-project A — the
reconcile cron orchestrator; **frozen, unchanged by this spec except the
additive Step 0 below**)
**Components:** `services/app` (Django: `analysis` app — models, one
management-command step, admin-gated views/templates)

## Background

Sub-project A delivers a 45-minute idempotent reconcile cron that consumes
opaque `pending AnalysisSchedule` rows and owns the cost-safe vast.ai
instance lifecycle (launch → drain → destroy, hard-deadline backstop). It
deliberately does **not** care how schedule rows appear.

This sub-project is the **producer** side: an admin UI to define when
analysis runs, including **recurring** runs expressed as a crontab string,
plus visibility into recent and upcoming runs. It layers cleanly on A
because A treats a pending schedule as an opaque instruction.

## Scope

- **In scope:** a `RecurringAnalysisSchedule` rule model; one additive
  "Step 0" in the existing reconcile command that materializes due rules
  into `pending AnalysisSchedule` rows; an admin-gated web page to
  create/edit/enable/disable/delete rules and create one-off runs; two
  read tables ("recent runs", "future planned runs"); cron-string
  validation + a human-readable "next runs" preview.
- **Out of scope:** any change to A's reap/launch passes, the vast client,
  or A's cost-safety mechanics (all inherited unchanged); game selection /
  campaign creation (still out per A); per-rule engine selection;
  notifications/email; multi-tenant scheduling; sub-hour precision beyond
  what the 45-min cron resolves.

## Goal

An admin defines "run analysis on this crontab" (or "run once" → next
tick) from a web page, sees the next few planned runs and the recent run
history with clear success/failure, and the existing reconcile cron turns
due rules into runs — with the same cost-safety guarantees A already
provides. Scheduling a one-off for a *future specific time* is done by a
recurring rule, not a dated one-off, so Sub-project A's `AnalysisSchedule`
stays unchanged (no "not-before" field).

## Design

### Recurrence → orchestrator integration (the crux, additive)

A new **Step 0** is prepended to the existing `reconcile_vast_analysis`
command (Sub-project A). It runs before A's reap and launch passes and is
the *only* change to A:

For each **enabled** `RecurringAnalysisSchedule`:
1. Compute the rule's most-recent fire time `≤ now` from its crontab
   string, evaluated in the rule's timezone, using `croniter`
   (`croniter(expr, now).get_prev(datetime)`).
2. If that fire time is **strictly after** the rule's
   `last_materialized_at` → create one `pending AnalysisSchedule`
   (FK back to the rule, `max_jobs` copied from the rule or null →
   `VAST_MAX_JOBS`), then set the rule's `last_materialized_at = now`.

Properties that fall out of "last fire ≤ now vs. last_materialized_at":

- **Coalesced catch-up:** if the cron runner was down across several
  occurrences, exactly **one** make-up run is materialized, never a
  backlog. (Cost-safe; confirmed requirement.)
- **Failure does not auto-retry (Option A, confirmed):** keying off
  *materialized* time (not *successful* time) means a failed run does
  **not** re-fire on later ticks. The period is spent; the next run is
  the rule's next occurrence. Failures are surfaced loudly in the
  "recent runs" table for manual re-trigger, not silently relaunched.
- A's invariants (≤1 live instance, reap-before-launch, hard deadline)
  still bound everything; Step 0 only ever *creates pending rows*, never
  launches.

`AnalysisSchedule` gains an optional `recurring_rule` FK (null for
one-offs) so history can attribute a run to its rule.

### Data model

`RecurringAnalysisSchedule` (new, `analysis` app):
- `id`, `created_at`, `updated_at`
- `name` (short label, e.g. "Weekly Monday 02:00")
- `crontab` (str; validated as a 5-field cron expression)
- `timezone` (str; default = configured app timezone)
- `enabled` (bool, default True)
- `max_jobs` (int, nullable → falls back to `VAST_MAX_JOBS`)
- `last_materialized_at` (datetime, nullable)
- `note` (optional free text)

`AnalysisSchedule` (from A) — **additive only:** add
`recurring_rule` FK (nullable, `SET_NULL`) → `RecurringAnalysisSchedule`.
No status/semantics change; A's reconcile is unaffected.

### Web UI

One admin-gated page in the `analysis` app, mirroring existing patterns:

- **Gating:** `_admin_login_required` (the same decorator the analysis
  views/dashboard use); non-staff → 403, consistent with the codebase.
  Not gated by `VAST_ENABLED` (you may want to plan schedules before
  enabling vast); the *cron* still no-ops when `VAST_ENABLED` is False per
  A, so planning is harmless.
- **URL:** added to the `analysis` urlconf alongside the dashboard.
- **Templates:** new templates under `analysis/` templates dir, reusing
  existing table styling — **`.wc-table .wc-table--zebra`** for these
  data-dense admin tables (do not introduce `.pg-table`).
- **HTMX:** the cron "next runs" preview uses the project's existing HTMX
  pattern (a small partial endpoint), consistent with the analysis
  overview auto-refresh approach.

Page contents:

1. **Rules section** — list of `RecurringAnalysisSchedule` with
   enable/disable toggle, edit, delete; a create/edit form with: name,
   crontab string, timezone, max_jobs (optional), note. The form shows a
   live **"next 3 runs" preview** computed via `croniter` and rejects an
   invalid crontab on both client submit and model `clean()`.
   Weekly/Monthly **preset buttons** simply fill the crontab field with a
   canonical expression (e.g. weekly → `0 2 * * 1`); no separate model.
2. **"Future planned runs" table** — for each enabled rule, its next
   occurrence (croniter `get_next`), plus any `pending`/`running`
   `AnalysisSchedule` not yet terminal. Columns: when, source
   (rule name or "one-off"), max_jobs, status.
3. **"Recent runs" table** — terminal `AnalysisSchedule` history joined to
   their `AnalysisInstance` (from A): when, source, status (**done /
   failed visually distinct — failed rows loud**), instance id,
   `offer_dph`, duration. A per-row **"Re-run"** action creates a fresh
   one-off `pending AnalysisSchedule`.
4. **"Run once" control** — creates a one-off `pending AnalysisSchedule`
   immediately (the manual trigger from A, now with a UI affordance
   instead of Django admin).

### Dependency

Add `croniter` to `services/app` requirements — used for both Step 0
(prev fire) and the UI preview (next fires). Single, well-established lib;
no hand-rolled cron math.

## Error handling

- Invalid crontab → form error + model `clean()` rejection; never stored.
- Unknown/invalid timezone → form error.
- A rule whose `croniter` evaluation raises → Step 0 logs and skips that
  rule (one bad rule cannot break the reconcile run or other rules).
- Disabled rule → Step 0 skips entirely (no materialization, no stamp).
- Deleting a rule with historical runs → FK is `SET_NULL`; history rows
  remain and show source as "(deleted rule)".
- All A error handling (vast failures, hard deadline, no-offer, etc.)
  is inherited unchanged.

## Testing

- **Step 0 unit tests** (reconcile, vast client mocked per A): due rule →
  one pending schedule + stamp; not-due → nothing; disabled → skipped;
  runner-down-across-N-occurrences → exactly one materialization;
  failed prior run does **not** re-fire (Option A); bad crontab in one
  rule doesn't break others; ordering — Step 0 before reap/launch.
- **Model tests:** crontab/timezone validation, `max_jobs` fallback,
  `last_materialized_at` transitions, `AnalysisSchedule.recurring_rule`
  SET_NULL on rule delete.
- **View tests:** `_admin_login_required` gating (anon redirect,
  non-staff 403, staff 200); rule create/edit/delete/toggle;
  "run once" creates a pending schedule; "re-run" creates a one-off;
  both tables render expected rows; failed run rendered as failed.
- **Preview tests:** "next N runs" matches croniter for sample
  expressions and timezones; invalid expr → graceful preview error.

## Out of scope / non-goals

Changes to A's reap/launch/cost-safety; per-rule engine or campaign
selection; notifications; auto-retry of failed runs (Option A —
deliberate); sub-cron precision; calendar/UX beyond the two tables and a
rule form; bulk rule import; auth changes beyond reusing
`_admin_login_required`.
