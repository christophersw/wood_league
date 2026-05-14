# Worker Dashboard — Consolidated `/admin/dashboard/`

**Issue:** [#106](https://github.com/christophersw/wood_league/issues/106)
**Status:** Design — pending user review
**Date:** 2026-05-14

## 1. Problem

The admin surface for worker observability is fragmented. While debugging the
RunPod L40S deployment, we repeatedly SSH'd into the pod to tail logs because
the Django UI couldn't answer the most basic operational questions:

- Are my workers alive right now?
- What game is each worker analysing?
- How fast are they processing jobs?
- How much work is left in the queue?
- Which recently-completed games can I open to verify the analysis worked?

Today the answers are scattered:

- `/admin/diagnostics/` — sparse: 24h throughput summary + recent failures only
- `/admin/queues/` and per-engine queue pages — counts, but no live worker state
- `WorkerHeartbeat` model is populated by workers but **not registered in admin**;
  `/admin/analysis/workerheartbeat/` returns 404
- No throughput page surfaces rates over short windows (5–10 min) where you can
  actually see whether a worker just started or is steady-state

## 2. Goal

A single dashboard at `/admin/dashboard/` that replaces `/admin/diagnostics/`
and answers all five questions above on one page. The page should feel live
(HTMX polling of partials) so an operator can leave it open and watch progress.

## 3. Out of Scope

- **Move-level progress within a job.** The worker has it locally
  (`move X/N` log lines) but does not heartbeat it. Adding `current_move`/
  `total_moves` to `WorkerHeartbeat` would require a model migration and a
  worker-side change + PyPI bump. Defer to a follow-up if useful.
- **Websockets.** HTMX polling at 5–10s is sufficient for a dashboard.
- **Historical drilldown / per-day rollups.** This page is "now-and-recent."
  A separate Reports page can come later if needed.
- **Stale-active job reaper.** Belongs to companion issue (to be filed
  separately) — flips `status=running` jobs whose worker heartbeat is >5min
  stale back to `pending`. Out of scope for this dashboard PR but listed here
  so we don't lose it.

## 4. Layout

Top-to-bottom, six sections. Each section is its own HTMX partial with an
independent refresh interval.

```
┌─ Health banner ─────────────────────────────────────────────┐
│  ● 2/2 workers healthy  ·  18 jobs pending  ·  47 today    │
│  (dot reflects worst worker state: green / yellow / red)    │
└─────────────────────────────────────────────────────────────┘

┌─ Workers (one card per WorkerHeartbeat row) ───────────────┐
│  ┌─ runpod-stockfish ─┐  ┌─ runpod-lc0 ────┐               │
│  │ ● working  · 12s   │  │ ● working · 8s  │               │
│  │ Game #10729        │  │ Game #10844     │               │
│  │ ✓ 6  ✗ 0           │  │ ✓ 1  ✗ 0        │               │
│  │ up 22m · stockfish │  │ up 22m · lc0    │               │
│  │ 16c · 62GB         │  │ 16c · 62GB      │               │
│  └────────────────────┘  └─────────────────┘               │
│  Stale rows (last_seen > 2min) shown faded red             │
└─────────────────────────────────────────────────────────────┘

┌─ Queues ────────────────────────────────────────────────────┐
│  Engine     Pending  Running  Rate (10m)   ETA              │
│  Stockfish  234      17       2.1 / min    ~1h 51m          │
│  Lc0        89       1        0.2 / min    ~7h 24m          │
└─────────────────────────────────────────────────────────────┘

┌─ Throughput (1h / 6h / 24h) ────────────────────────────────┐
│              1h     6h     24h    p50 dur   p95 dur         │
│  Stockfish   18     94     211    3m 18s    7m 02s          │
│  Lc0          3     17      38    9m 11s   22m 47s          │
└─────────────────────────────────────────────────────────────┘

┌─ Recently completed (last 25 games) ────────────────────────┐
│  Game            Stockfish   Lc0        Completed           │
│  #10729 [link]   4m 12s      11m 03s    2 min ago           │
│  #10728 [link]   3m 58s      ─          5 min ago           │
│  #10726 [link]   5m 21s      9m 47s     12 min ago          │
└─────────────────────────────────────────────────────────────┘

┌─ Recent failures (last 10, collapsed by default) ──────────┐
│  (reuses existing diagnostics failure-row helper)           │
└─────────────────────────────────────────────────────────────┘
```

## 5. Data Sources

All exist already. No model changes, no migrations.

### 5.1 `analysis.WorkerHeartbeat`

Source of truth for worker liveness. Fields used:

| Field | Use |
|---|---|
| `worker_id` (pk) | Card identity (`runpod-stockfish`, `runpod-lc0`, `local-...`) |
| `last_seen` | Liveness — `now - last_seen` drives status dot color |
| `engine` | Card label |
| `status` | "idle" / "working" / "error" — direct dot color hint |
| `status_message` | Optional sub-line on card |
| `current_game_id` | "Game #N" line + link target — see note below |
| `jobs_completed`, `jobs_failed` | Card stats |
| `started_at` | Uptime calc |
| `cpu_model`, `cpu_cores`, `memory_mb` | Hardware footer line |

**Linking `current_game_id` to a Game page:** the field is `CharField(64)`,
which workers set to `str(game.pk)`. The card resolves the link by trying
`Game.objects.filter(pk=int(value)).values_list("slug", flat=True).first()`,
catching `ValueError` (non-numeric) and falling back to plain text. Helper
function: `_game_link_for(current_game_id) -> tuple[str, str | None]`
returning `(label, url_or_None)`.

**Liveness thresholds (defined as constants in the view module):**

- `last_seen` < 60s → green ("healthy")
- 60s ≤ `last_seen` < 120s → yellow ("warning")
- `last_seen` ≥ 120s → red ("stale")

### 5.2 `analysis.AnalysisJob`

Status enum (already in code): `pending`, `submitted`, `running`, `completed`,
`failed`. Key fields: `engine`, `created_at`, `started_at`, `completed_at`,
`duration_seconds`, `game_id` (FK).

Used for:

- **Queue counts** — `filter(status__in=[pending, submitted], engine=E).count()`
  and `filter(status=running, engine=E).count()`
- **Rate (10m)** — `filter(status=completed, completed_at__gte=now-10min, engine=E).count() / 10.0`
- **ETA** — `pending_count / rate_per_min`, formatted as `Xh Ym` or `—` if rate=0
- **Throughput windows** — reuse the existing `_engine_throughput_row(engine, hours)`
  helper in `analysis/views.py` for the 1h / 6h / 24h rows
- **Recently completed** — `AnalysisJob.objects.filter(status=completed).order_by('-completed_at')`,
  group in Python by `game_id`, take first 25 distinct games, pivot per-engine
  `duration_seconds` into columns

### 5.3 No `ThroughputSample` model

The earlier inline plan referenced this. It doesn't exist. Throughput is
computed on the fly from `AnalysisJob` via the existing helper, which is
fine for our row counts (a few hundred jobs over 24h).

## 6. URL & View Structure

```
services/app/analysis/
  urls.py              # add dashboard/ + 6 partial routes
  views_dashboard.py   # new file — view + partials live here
  templates/analysis/
    dashboard.html              # shell
    _dash_banner.html           # partial
    _dash_workers.html          # partial
    _dash_queues.html           # partial
    _dash_throughput.html       # partial
    _dash_recent_completed.html # partial
    _dash_failures.html         # partial
```

**URL patterns added to `analysis/urls.py`:**

```python
path("dashboard/", views_dashboard.dashboard, name="dashboard"),
path("dashboard/banner/", views_dashboard.dashboard_banner, name="dash_banner"),
path("dashboard/workers/", views_dashboard.dashboard_workers, name="dash_workers"),
path("dashboard/queues/", views_dashboard.dashboard_queues, name="dash_queues"),
path("dashboard/throughput/", views_dashboard.dashboard_throughput, name="dash_throughput"),
path("dashboard/recent/", views_dashboard.dashboard_recent, name="dash_recent"),
path("dashboard/failures/", views_dashboard.dashboard_failures, name="dash_failures"),
```

`/admin/diagnostics/` becomes a redirect to `/admin/dashboard/` (preserve
muscle memory + any existing bookmarks).

**Why a new file** (`views_dashboard.py`): `views.py` is already 400+ lines
covering queues + diagnostics + RunPod admin. Adding 6 new view functions
would push it past where it's comfortable to navigate. Splitting now follows
the same pattern as `views_queue.py`.

## 7. HTMX Refresh Strategy

Each partial polls its own URL on a `hx-trigger="every Ns"` timer:

| Partial | Interval | Why |
|---|---|---|
| Banner | 10s | Coarse — only worker count + total pending changes |
| Workers | 5s | Most useful live signal; cheap query |
| Queues | 10s | Counts + 10-min rate; not super volatile |
| Throughput | 60s | Hourly windows barely move at sub-minute cadence |
| Recently completed | 30s | New games arrive infrequently |
| Failures | 60s | Failures are rare; no need to poll fast |

All partials are independent — if one query is slow, the others keep updating.

Server-side: each partial view uses `cache_control(no_store=True)` so HTMX
doesn't get stale browser-cached fragments.

## 8. Visual Design (Tailwind + Du Bois Palette)

The site already uses a W.E.B. Du Bois-inspired design system (parchment
backgrounds, ebony text, EB Garamond body, Playfair Display SC headings,
DM Mono labels — see `services/app/templates/analysis/queue.html` header).

Dashboard reuses that system:

- **Cards** — parchment background, ebony border, `.pg-section` style
  (already defined for queue pages)
- **Status dots** — solid 8px circles, colors mapped from worker liveness
  via Tailwind tokens already in the palette
- **Numbers** — DM Mono (matches existing queue counters)
- **Tables** — same striping + header style as `_queue_recent.html`
- **Game links** — underline + `var(--color-peat)` (same as breadcrumb in
  queue.html)

A subagent invoking `frontend-design` will own the per-section markup so the
visual language matches the rest of the admin.

## 9. Implementation Order (one PR, sequenced commits)

This is one PR, but committed in reviewable slices:

1. **Wire-up commit** — add `views_dashboard.py` skeleton (each view returns
   stub markup), URL patterns, `dashboard.html` shell that includes all six
   partials, redirect from `/admin/diagnostics/` → `/admin/dashboard/`. Page
   renders end-to-end with placeholders. Tests: smoke test that `GET /admin/dashboard/`
   returns 200 and includes all six partial regions.
2. **Banner + Workers partials** — real data, including liveness thresholds
   and uptime/hardware formatting. Tests for the threshold helper.
3. **Queues + Throughput partials** — rate calc, ETA helper, reuse existing
   throughput row helper. Tests for rate/ETA functions.
4. **Recently completed partial** — game grouping logic + per-engine pivot.
   Tests: group-by-game with mixed engine completion states (both done, only
   stockfish done, only lc0 done).
5. **Failures partial + final polish** — reuse existing `_build_failure_row`
   helper. Visual pass via `frontend-design` subagent. Tests for the
   end-to-end render.

## 10. Testing

- **View-layer tests** in `services/app/analysis/tests/test_dashboard_view.py`
  - `GET /admin/dashboard/` returns 200, contains all six partial wrappers
  - Each partial URL returns 200 with the expected content keys
  - Redirect: `GET /admin/diagnostics/` → 302 to `/admin/dashboard/`
- **Helper tests** — pure-function helpers (`_liveness_for(timedelta)`,
  `_rate_per_min(engine)`, `_eta_for(pending, rate)`, `_group_recent_by_game(qs)`)
  are tested in isolation
- **No new integration tests** — the existing diagnostics integration tests
  cover the throughput helper we're reusing

Quality gate (per repo CLAUDE.md): ruff → bandit+semgrep → radon/xenon → mypy
→ pytest+cov, with bandit `-ll` on any edited `.py` files before commit.

## 11. Delegation Plan

Three subagents in sequence (not parallel — each depends on the previous):

1. **Architect / Plan agent** (Sonnet) — translates this spec into a writing-plans
   doc with concrete files-to-touch list, function signatures, and per-slice
   commits. Uses `vexp run_pipeline` to locate the existing queue/diagnostics
   helpers we'll reuse.
2. **Backend implementation agent** (Sonnet) — writes `views_dashboard.py`,
   URL patterns, and helper functions per the plan. Uses `vexp` for any new
   lookups, `context7` only if a Django/HTMX API question comes up.
3. **Frontend implementation agent** (Sonnet, invokes `frontend-design` skill)
   — writes the six partial templates + the shell, matching the Du Bois
   palette. Receives the rendered context dicts from agent #2 as input.

Each agent is briefed to use `vexp run_pipeline` instead of grep/glob, and to
use `context7` for any library-doc lookups. The frontend agent specifically
invokes the `frontend-design` skill before writing HTML.

## 12. Risks & Mitigations

- **Risk: HTMX polling load on a busy admin.** Six partials × the polling
  intervals above = roughly 10 requests/minute per open dashboard tab. Cheap
  queries — no concern. If we ever embed this on a public page, revisit.
- **Risk: Worker heartbeats not updating during long jobs.** The Lc0 wrapper
  is busy in C++ for minutes at a time; if the Python heartbeat thread is
  blocked, `last_seen` will go yellow/red despite the worker being healthy.
  Not introduced by this dashboard — it's an existing condition we'll just
  *expose* here. Worth a follow-up to confirm heartbeats run on a daemon
  thread, but not blocking.
- **Risk: Stale "running" jobs from dead pods bloat the running count.** The
  stale-active reaper (companion issue) addresses this. Until then, the
  dashboard will faithfully show "17 running" when most are zombies. Acceptable
  for v1 — visibility of the problem is itself a win.

## 13. Done When

- `/admin/dashboard/` exists, renders all six sections with live data
- `/admin/diagnostics/` redirects to it
- Tests pass; ruff/bandit/mypy clean
- The page can be left open during a real RunPod run and you can answer all
  five Section 2 questions from it without SSH
