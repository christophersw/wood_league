# Analysis Dashboard Rework — Design

**Issue:** #200 — Rework Analysis Dashboard
**Date:** 2026-05-22
**Status:** Approved (design)

## Summary

Collapse the three separate admin analysis surfaces — the worker dashboard
(`admin/dashboard/`), the scheduling page (`admin/schedule/`), and the queue
pages (`admin/queues/…`) — into a single page at `admin/analysis/`. The queue
pages are deleted outright. The dashboard content stacks at the top of the new
page, the scheduling content below it, and several panels move into responsive
two-column rows to use horizontal space more efficiently.

## Goals

- One admin page at `admin/analysis/` (URL name `analysis:overview`).
- The header "Analysis" link (admin-only) points to this page.
- Dashboard content first, scheduling content second.
- Dense tables laid out two-up on desktop, stacked on mobile.
- Worker-card recent-game IDs truncated so each fits on one line.
- Remove the `admin/queues/…` pages and their supporting code/templates.

## Non-goals

- No change to how the dashboard partials compute their data.
- No change to the scheduling/reconcile backend or the recurring-rule model.
- No redesign of the worker-card internals beyond the gameId truncation.

## Routing & views

### New combined page

- Rename `views_schedule.scheduling_page` → `overview`; it renders the new
  `analysis/overview.html` and supplies the existing schedule context
  (`form`, `rules`, `future_rows`, `recent_rows`). The schedule context
  builders (`_future_rows`, `_recent_rows`, `_render_page`) already live in
  `views_schedule.py`, so the combined view stays where its data is.
- Decorators unchanged: `@_admin_login_required @require_GET`.
- The dashboard sections are HTMX-polled, so `overview` needs no dashboard
  data of its own — it only renders the shell wrappers.
- URL: `path("analysis/", views_schedule.overview, name="overview")` in
  `analysis/urls.py` (mounted at `admin/`, so the live path is
  `admin/analysis/`).

### Header link

- In `templates/base.html`, repoint the desktop nav and the mobile drawer
  "Analysis" link from `analysis:queues_summary` → `analysis:overview`.
  The `nav-link--active` namespace check (`namespace == 'analysis'`) is
  unchanged.

### Dashboard partials

- Keep all seven partial views in `views_dashboard.py` (`dashboard_banner`,
  `dashboard_workers`, `dashboard_queues`, `dashboard_throughput`,
  `dashboard_recent`, `dashboard_failures`, `dashboard_logs`).
- Repath their URLs from `dashboard/<x>/` → `analysis/<x>/` in
  `analysis/urls.py`. URL **names are unchanged** (`dash_banner`,
  `dash_workers`, `dash_queues`, `dash_throughput`, `dash_recent`,
  `dash_failures`, `dash_logs`), so template `{% url %}` references keep
  working.
- Remove the `dashboard/` shell route and the `views_dashboard.dashboard`
  shell view (the new `overview` view + template replace it).

### Schedule action handlers

- Keep `rule_create`, `rule_edit`, `rule_delete`, `rule_toggle`, `run_once`,
  `rerun`, and `schedule_preview`.
- Their success redirects change from `analysis:scheduling` →
  `analysis:overview`.
- Remove the old `schedule/` shell route + the `scheduling` URL name (the
  page itself is now `overview`); the action sub-routes (`schedule/rule/…`,
  `schedule/run-once/`, `schedule/<pk>/rerun/`, `schedule/preview/`) stay.

## `analysis/overview.html` layout

New template extending `base.html`. Top-to-bottom:

1. `page-hero` titled "Analysis".
2. **Banner** — HTMX wrapper, full width (`hx-get analysis:dash_banner`).
3. **Workers** grid — HTMX wrapper, full width.
4. **Recently completed games** — HTMX wrapper, full width.
5. Row (`.panel-grid .panel-grid--even`): **Queues** (½) + **Throughput** (½),
   each an HTMX wrapper as a grid cell.
6. Row (`.panel-grid .panel-grid--even`): **Recent failures** (½) +
   **Worker logs** (½).
7. Scheduling sub-header (a `page-hero`-style or section heading separating
   the two halves of the page).
8. Row: **Run-once form** + **New recurring rule form** (existing
   `.panel-grid .panel-grid--2`, carried over verbatim from `scheduling.html`).
9. Row (`.panel-grid .panel-grid--even`): **Recurring rules** table (½) +
   **Future planned runs** table (½).
10. **Recent runs** table — full width.

Each HTMX section keeps its existing `hx-trigger` polling intervals. Inside a
`--even` row, the two HTMX target `<div>`s are the grid children; each swaps in
its own `.pg-section`.

## CSS

Add to `static/css/main.css`, inside the existing `@media (min-width: 880px)`
block next to `.panel-grid--2`:

```css
.panel-grid--even { grid-template-columns: 1fr 1fr; }
```

`main.css` is the Tailwind v4 source; `static/css/tailwind.css` is the
committed, served artifact. After editing `main.css`, rebuild via
`services/app/bin/build_tailwind.sh`. The build output is byte-sensitive to
the Node major version — CI uses Node 22, so rebuild under Node 22 (e.g.
`npx node@22 …` or an nvm-selected Node 22) or the CSS-staleness guard fails.

## Worker-card gameId truncation

- In `analysis/dashboard_helpers.py::_worker_recent_games`, add
  `game_label_short = f"#{str(job.game_id)[:6]}"` to each row dict (keep the
  full `game_label` for the hover title).
- In `templates/analysis/_dash_workers.html`, the recent-games `<li>` shows
  `g.game_label_short` as the link/label text with `title="{{ g.game_label }}"`
  so the full id is available on hover and each row stays single-line.

## Removals (hard delete, no redirects)

Per the issue and confirmed scope, these are removed outright.

### Routes (`analysis/urls.py`)

- `queues/`, `queues/stockfish/`, `queues/lc0/`, `queues/<engine>/reorder/`
- `dashboard/` shell
- `schedule/` shell (the `scheduling` name)
- the legacy `diagnostics/` redirect

### Views

- `views.queues_summary`, `views.overview_partial`, `views._queue_context`,
  `views._engine_metric`
- `views_dashboard.dashboard` (shell)
- all of `views_queue.py`

`views._admin_login_required` and the RunPod helpers stay (still imported
elsewhere) — see RunPod note below.

### Templates

Remove after confirming nothing else references each:
`dashboard.html`, `scheduling.html` (content merged into `overview.html`),
`queues_summary.html`, `queue.html`, `_overview_cards.html`, `status.html`,
and the `_queue_*` partials (`_queue_action_result`, `_queue_active`,
`_queue_partial`, `_queue_pending_table`, `_queue_recent`) plus
`_workers_panel.html`.

### Partial URLs

- Remove the `analysis/queue/` → `overview_partial` entry from
  `analysis/partial_urls.py` (its view is deleted).

### RunPod endpoint

`runpod_start_view` (`runpod/start/`) had its only UI trigger on the deleted
queues page. During implementation, verify references; if it is exclusively
orphaned, remove the route + view. If anything else still references it, leave
it in place — RunPod removal is out of scope for this issue.

## Tests

### Remove / rework

- Delete queue-specific tests: `test_views_queue.py`,
  `test_views_queue_reorder.py`, `test_views_queues_summary.py`,
  `test_status_overview.py`.
- Rework `test_dashboard_view.py` and `test_views_schedule.py` to target
  `analysis:overview` instead of the removed shells.

### Add

- `analysis:overview` returns 200 for an admin and the HTML contains the
  dashboard HTMX wrappers (by `hx-get` URL or container id) and the schedule
  sections (recurring rules, future runs, recent runs, both forms).
- `analysis:overview` blocks non-admins (login redirect / 403 consistent with
  `_admin_login_required`).
- Schedule POST handlers (`run_once`, `rule_create`, …) redirect to
  `analysis:overview`.
- Removed URLs (`admin/queues/`, `admin/dashboard/`, `admin/schedule/`) now
  resolve to 404.
- `_worker_recent_games` populates `game_label_short` correctly (first 6 chars
  of the id, `#`-prefixed) — assertion in `test_dashboard_helpers.py`.

## Risks / notes

- Repathing the partial URLs means the new template must use the same URL
  names; a missed `{% url %}` would surface as a reverse error at render — the
  added overview render test catches this.
- The `--even` grid reuses the established `.panel-grid` breakpoint (880px),
  so mobile stacking is consistent with the existing forms row.
- tailwind.css must be rebuilt and committed together with the `main.css`
  change, under Node 22, or CI's staleness guard fails.
