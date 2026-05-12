# Analysis Queue UI/UX Overhaul — Design

**Issue:** [#30](https://github.com/christophersw/wood_league/issues/30)
**Date:** 2026-05-11
**Status:** Approved — ready for implementation plan

## Goal

Rework the analysis-queue admin pages so admins can manage hundreds of pending jobs effectively. Specifically: control priority via tiers, see the freshest games first, reorder rows in bulk, submit to RunPod with a real button, and keep controls visible while scrolling. Restructure routing so `/admin/queues/` is a real summary page that links into the per-engine queues.

## Non-Goals

- Persisting selection across pages.
- Drag-and-drop reordering.
- Cross-engine bulk operations.
- Changes to the RunPod dispatch payload or worker claim contract beyond the SQL `ORDER BY` clause.

## 1. Data model and ordering

`AnalysisJob.priority` is already an `IntegerField`; no migration needed. Introduce three module-level constants in `services/app/analysis/models.py`:

```python
PRIORITY_HIGH = 100    # user-initiated reanalysis, "send to top"
PRIORITY_NORMAL = 0    # default bulk-ingest
PRIORITY_LOW = -100    # "send to bottom"
```

**Ordering — display and claim both use:**

```sql
ORDER BY priority DESC, games.played_at DESC
```

This means: highest tier first; within a tier, the most recently played game ranks first. Worker claim order and admin pending-table display order are kept in sync so the order admins see is the order workers will pick.

**Update `games.queue_analysis`** (`services/app/games/views.py:603`) to set `priority=PRIORITY_HIGH` instead of the current literal `1`. Bulk ingest stays at `PRIORITY_NORMAL` (the model default).

## 2. Routing

Rename the URL family to plural. Old singular URLs are removed (not redirected — no real bookmark base).

| New URL | View | Notes |
|---|---|---|
| `/admin/queues/` | new `queues_summary` | Replaces `/admin/analysis-status/`. |
| `/admin/queues/stockfish/` | `queue_stockfish` (existing) | |
| `/admin/queues/lc0/` | `queue_lc0` (existing) | |
| `/admin/queues/<engine>/submit/` | `queue_submit` (existing) | |
| `/admin/queues/<engine>/reorder/` | new `queue_reorder` | POST only. |

Update every `{% url %}` reference and any hard-coded path in templates, nav, and tests.

## 3. Summary page `/admin/queues/`

Reuses the existing `services.queue_by_engine()` and `runpod_health` calls from `views.py::_queue_context`. New template renders two large cards, each a clickable link to the engine page:

```
┌─────────────────────────┬──────────────────────────┐
│ STOCKFISH               │ LC0                      │
│ → /admin/queues/stockfish/   → /admin/queues/lc0/  │
│                         │                          │
│ Pending: 123 (12 HIGH)  │ Pending: 42              │
│ Active:  4              │ Active:  1               │
│ Failed (24h): 2         │ Failed (24h): 0          │
│                         │                          │
│ RunPod: ✓ healthy       │ RunPod: ✓ healthy        │
│ Worker last seen: 2m    │ Worker last seen: 8m     │
└─────────────────────────┴──────────────────────────┘
```

The HIGH count surfaces user-initiated reanalysis pressure at a glance.

## 4. Per-engine queue page (`/admin/queues/<engine>/`)

Layout (A + C: sticky top toolbar over a server-paginated table):

```
┌─────────────────────────────────────────────────────────┐
│ HERO: <Engine> Queue · breadcrumb back to /queues/      │
├─────────────────────────────────────────────────────────┤
│ STICKY TOOLBAR (position: sticky; top: 0)               │
│  [☐ select page] {N selected}                           │
│  [Submit to RunPod] [↑ Top] [↓ Bottom]                  │
│  ─── tabs: Pending (123) │ Active (4) │ Recent (50) ─── │
├─────────────────────────────────────────────────────────┤
│ TABLE (paginated, 50/page default; hx-get swaps tbody)  │
│  ☐ │ Game │ Played │ Depth │ Priority │ Last error │ ⋯  │
├─────────────────────────────────────────────────────────┤
│ PAGINATION (hx-get): ‹ 1 2 [3] 4 5 … 8 ›  Show 25/50/100│
└─────────────────────────────────────────────────────────┘
```

### Toolbar

One `<form>` wraps the pending tab's table. Three submit buttons share the same `job_ids[]` field:

- **Submit to RunPod** → `POST /admin/queues/<engine>/submit/` (existing endpoint).
- **↑ Top** → `POST /admin/queues/<engine>/reorder/?action=top` (sets priority to HIGH).
- **↓ Bottom** → `POST /admin/queues/<engine>/reorder/?action=bottom` (sets priority to LOW).

All use the project's existing `.wc-btn` class — fixes the current `.btn-primary` (undefined class → unstyled text) bug.

Sticky CSS keeps the toolbar visible while the tbody scrolls. The toolbar also contains the tabs.

### Tabs

Pending, Active, Recent. Only one table is rendered at a time, drastically shortening the page. Tab links use `hx-get` to swap the table region. The active and recent tabs are read-only — the toolbar action buttons and the checkbox column are hidden on those tabs (the tab strip itself remains).

### Pagination

Server-side via Django `Paginator`. Default 50 rows per page. Page size selector offers 25 / 50 / 100. Page links carry `?page=N&per_page=M` and use `hx-get` with `hx-target` set to the table+pagination wrapper. Selection is per-page only — checkboxes are part of the swapped DOM, so navigating loses the selection by design.

### Per-row inline reorder

Trailing column with `↑` and `↓` icon buttons that `hx-post` to the reorder endpoint with a single `job_ids` value. Useful for moving one row without selecting.

### Priority badge

Replaces or augments the priority cell:

- HIGH → amber pill, label "HIGH"
- NORMAL → slate, label "NORMAL" (or empty for visual quiet)
- LOW → muted, label "LOW"

User-initiated reanalysis is visually obvious.

## 5. Reorder endpoint

```
POST /admin/queues/<engine>/reorder/
  job_ids[]: list[int]
  action:    "top" | "bottom"
```

Body:

```python
new_priority = PRIORITY_HIGH if action == "top" else PRIORITY_LOW
AnalysisJob.objects.filter(
    id__in=job_ids,
    engine=engine,
    status=AnalysisJob.STATUS_PENDING,
).update(priority=new_priority)
```

Returns the refreshed pending table + a flash count ("Moved 12 jobs to top"). Renders the same partial as bulk-submit so HTMX swaps one region. Admin-only via `_admin_required`. Returns 400 on bad `engine` or `action`. Non-pending or wrong-engine jobs in `job_ids` are silently filtered (same pattern as `queue_submit`).

## 6. HTMX targeting fix

The current `_queue_pending.html` has:

```html
<form id="bulk-submit-form" hx-target="#bulk-submit-form" hx-swap="outerHTML">
```

This is fine *if* the response always contains `<div id="bulk-submit-form">…`, which `_queue_submit_result.html` does. We keep the same outer-HTML swap pattern but rename the wrapper to something clearer and put it on a `<div>` that contains both the toolbar and the table, so that all three actions (submit, top, bottom) target the same region.

## 7. Testing

- **Unit** — priority constants used by `games.queue_analysis` and `analysis.services.enqueue`; ordering query yields `priority desc, played_at desc` for worker claim + admin display.
- **Views** — `queue_reorder`: sets correct priority for top/bottom; ignores wrong-engine and non-pending jobs; rejects bad action with 400; admin-only.
- **Views** — pagination respects `?page=` and `?per_page=`; out-of-range pages return last page (Django default).
- **Views** — summary page renders engine cards with counts; HIGH-tier count is correct.
- **Snapshot** — 200-row fixture renders the pending table; toolbar and pagination present in DOM.
- **Manual** — visit each new URL; confirm bulk-submit button is visibly a button; click bulk-submit on a real pending job and confirm HTMX swap; click ↑ Top on a row and confirm it jumps to the top.

## 8. Security review

After editing each Python file, run `bandit -ll <file>` per `services/app/CLAUDE.md`. The reorder endpoint accepts user-submitted IDs but uses parameterized ORM updates and filters by `engine` + `status` — no SQLi or privilege-escalation surface beyond what `queue_submit` already exposes.

## 9. Out of scope / followups

- Fixing `.btn-primary` in the 4xx/500 error templates (unrelated).
- Worker fairness tuning (e.g. starvation guards for LOW-tier jobs).
- Cross-engine summary actions.
- Drag-to-reorder.
