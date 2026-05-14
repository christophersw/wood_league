# Worker Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Sub-agents MUST use `vexp run_pipeline` (and `get_skeleton` for file inspection) instead of grep/glob/find. Use `context7` for any Django/HTMX/Tailwind library doc lookups. Do NOT spawn Agent(Explore) for free-form codebase searches — call `run_pipeline` first.**

**Goal:** Build a single live-refreshing admin page at `/admin/dashboard/` that shows worker health, queue depth, throughput, recently completed games, and recent failures; delete the now-redundant `/admin/diagnostics/` page and the dead serverless RunPod health probe.

**Architecture:** New `analysis/views_dashboard.py` exposes one shell view + six HTMX-polled partial views. Shared computation helpers move from `views.py` into a new `analysis/dashboard_helpers.py` so both `views.py` (queues_summary) and `views_dashboard.py` import from one canonical location. Templates live in `templates/analysis/dashboard.html` (shell) and `templates/analysis/_dash_*.html` (partials). The legacy diagnostics view + serverless health probe are deleted in the final slice of the same PR.

**Tech Stack:** Django 5, HTMX, Tailwind (existing Du Bois palette), pytest, ruff, bandit, mypy.

**Spec:** `docs/superpowers/specs/2026-05-14-worker-dashboard-design.md`

**Issue:** [#106](https://github.com/christophersw/wood_league/issues/106)

**Branch:** `issue/106-worker-dashboard`

---

## Repo Conventions (read once before starting)

- **Activate venv before any Python command:** `source .venv/bin/activate` from repo root.
- **Test command:** `cd services/app && pytest <path> -v`. Django settings auto-loaded.
- **Quality gate before each commit:** `ruff check <files>`, `bandit -ll <files>`, `mypy <files>`, `pytest <new tests>`.
- **File header** required on every new `.py`/`.html` per `~/.claude/docs/code-standards.md`: Title, Description, Changelog.
- **Subagent contract:** every dispatched subagent MUST be told (in its prompt) to use `vexp run_pipeline` / `get_skeleton`, not grep/glob, and to use `context7` for any library doc lookups.

---

## File Structure (locked in)

**Create:**
- `services/app/analysis/views_dashboard.py` — shell view + 6 partial views + private helpers specific to the dashboard
- `services/app/analysis/dashboard_helpers.py` — shared pure functions (liveness, rate, ETA, game-link, recent-grouping, plus the throughput helpers moved out of `views.py`)
- `services/app/templates/analysis/dashboard.html` — shell template (extends `base.html`)
- `services/app/templates/analysis/_dash_banner.html`
- `services/app/templates/analysis/_dash_workers.html`
- `services/app/templates/analysis/_dash_queues.html`
- `services/app/templates/analysis/_dash_throughput.html`
- `services/app/templates/analysis/_dash_recent.html`
- `services/app/templates/analysis/_dash_failures.html`
- `services/app/analysis/tests/test_dashboard_helpers.py` — pure-function tests
- `services/app/analysis/tests/test_dashboard_view.py` — view + redirect tests

**Modify:**
- `services/app/analysis/urls.py` — add 7 dashboard routes; swap `diagnostics/` to `RedirectView`
- `services/app/analysis/views.py` — drop moved helpers + drop `runpod_health` call from `queues_summary`
- `services/app/analysis/services_queries.py` — delete `runpod_health()` function
- `services/app/analysis/services/__init__.py` — drop the `runpod_health` re-export
- `services/app/analysis/apps.py` — drop docstring references to the removed probe
- `services/app/templates/analysis/queue.html` — remove "Running & submitted to RunPod" caption
- Any `{% url 'analysis:diagnostics' %}` callers → `analysis:dashboard`

**Delete:**
- `services/app/analysis/views.py::diagnostics_view` (function only)
- `services/app/templates/analysis/diagnostics.html`
- `services/app/analysis/tests/test_diagnostics_view.py`

---

## Slice 1 — Wire-up (commit 1)

End state: `GET /admin/dashboard/` returns 200, includes all six partial regions (stub content), `GET /admin/diagnostics/` 302s to it. No real data wired yet.

### Task 1.1: Create branch and confirm baseline

**Files:** none (git only)

- [ ] **Step 1: Branch from main**

```bash
git checkout main
git pull --ff-only
git checkout -b issue/106-worker-dashboard
```

- [ ] **Step 2: Confirm baseline tests pass**

```bash
source .venv/bin/activate
cd services/app && pytest analysis/tests/ -x -q
```

Expected: all green. If anything is red on `main`, stop and surface to the user.

---

### Task 1.2: Create the dashboard shell template

**Files:**
- Create: `services/app/templates/analysis/dashboard.html`

- [ ] **Step 1: Write the shell template**

```html
{% extends "base.html" %}
{% comment %}
  Title: dashboard.html — Worker dashboard shell
  Description: Single-page consolidated admin dashboard for worker health,
      queue depth, throughput, recently completed games, and recent
      failures. Each section is an HTMX-polled partial that refreshes on
      its own interval. Replaces the legacy /admin/diagnostics/ page.
  Changelog:
      2026-05-14 (#106): Initial wire-up.
{% endcomment %}

{% block title %}Worker Dashboard · Wood League Chess{% endblock %}

{% block content %}
<div class="page-hero">
  <div>
    <p class="page-hero-sub" style="margin-bottom: 0.4rem;">
      <a href="{% url 'analysis:queues_summary' %}"
         style="color: var(--color-peat); text-decoration: underline; text-underline-offset: 3px;">
        ← Analysis Queues
      </a>
    </p>
    <h1>Worker Dashboard</h1>
    <p class="page-hero-sub">Live worker health, queue depth, and throughput.</p>
  </div>
</div>

<div id="dash-banner"
     hx-get="{% url 'analysis:dash_banner' %}"
     hx-trigger="load, every 10s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="pg-caption">Loading banner…</span></div>
</div>

<div id="dash-workers"
     hx-get="{% url 'analysis:dash_workers' %}"
     hx-trigger="load, every 5s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="pg-caption">Loading workers…</span></div>
</div>

<div id="dash-queues"
     hx-get="{% url 'analysis:dash_queues' %}"
     hx-trigger="load, every 10s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="pg-caption">Loading queues…</span></div>
</div>

<div id="dash-throughput"
     hx-get="{% url 'analysis:dash_throughput' %}"
     hx-trigger="load, every 60s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="pg-caption">Loading throughput…</span></div>
</div>

<div id="dash-recent"
     hx-get="{% url 'analysis:dash_recent' %}"
     hx-trigger="load, every 30s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="pg-caption">Loading recently completed…</span></div>
</div>

<div id="dash-failures"
     hx-get="{% url 'analysis:dash_failures' %}"
     hx-trigger="load, every 60s"
     hx-swap="innerHTML">
  <div class="pg-section"><span class="pg-caption">Loading failures…</span></div>
</div>
{% endblock %}
```

- [ ] **Step 2: Create stub partials**

Create each of the six files below with the same minimal content (replace `<NAME>` per file):

```html
{% comment %}
  Title: _dash_<NAME>.html — Worker dashboard <NAME> partial (stub)
  Description: HTMX-polled partial for the worker dashboard. Stub content
      until slice <N> wires real data.
  Changelog:
      2026-05-14 (#106): Stub.
{% endcomment %}
<div class="pg-section">
  <div class="pg-head"><span class="pg-title"><NAME></span></div>
  <span class="pg-caption">stub</span>
</div>
```

Files: `_dash_banner.html`, `_dash_workers.html`, `_dash_queues.html`, `_dash_throughput.html`, `_dash_recent.html`, `_dash_failures.html`.

---

### Task 1.3: Create `views_dashboard.py` with stub views

**Files:**
- Create: `services/app/analysis/views_dashboard.py`

- [ ] **Step 1: Write the stub module**

```python
"""
Title: views_dashboard.py — Worker dashboard views
Description:
    Hosts the consolidated /admin/dashboard/ shell view plus the six
    HTMX-polled partials (banner, workers, queues, throughput, recent,
    failures). Replaces the legacy /admin/diagnostics/ page.

Changelog:
    2026-05-14 (#106): Initial wire-up — stub partials, no real data yet.
"""
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@staff_member_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Render the dashboard shell page.

    The shell page contains HTMX wrappers that each poll a partial view
    for live data. The shell itself carries no data — partials are the
    sole source of truth so a slow query in one section never blocks
    the rest of the page.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML response for ``analysis/dashboard.html``.
    """
    return render(request, "analysis/dashboard.html", {})


@staff_member_required
def dashboard_banner(request: HttpRequest) -> HttpResponse:
    """Render the health-banner partial (stub)."""
    return render(request, "analysis/_dash_banner.html", {})


@staff_member_required
def dashboard_workers(request: HttpRequest) -> HttpResponse:
    """Render the workers partial (stub)."""
    return render(request, "analysis/_dash_workers.html", {})


@staff_member_required
def dashboard_queues(request: HttpRequest) -> HttpResponse:
    """Render the queues partial (stub)."""
    return render(request, "analysis/_dash_queues.html", {})


@staff_member_required
def dashboard_throughput(request: HttpRequest) -> HttpResponse:
    """Render the throughput partial (stub)."""
    return render(request, "analysis/_dash_throughput.html", {})


@staff_member_required
def dashboard_recent(request: HttpRequest) -> HttpResponse:
    """Render the recently-completed partial (stub)."""
    return render(request, "analysis/_dash_recent.html", {})


@staff_member_required
def dashboard_failures(request: HttpRequest) -> HttpResponse:
    """Render the recent-failures partial (stub)."""
    return render(request, "analysis/_dash_failures.html", {})
```

---

### Task 1.4: Wire URL patterns and redirect

**Files:**
- Modify: `services/app/analysis/urls.py`

- [ ] **Step 1: Replace urls.py with the new layout**

Read the current file first to capture existing patterns. The final file should look like:

```python
"""
Title: urls.py — URL routing for analysis module views
Description:
    Defines URL patterns for the consolidated worker dashboard and the
    per-engine queues management pages.

Changelog:
    2026-05-14 (#106): Add /dashboard/ + 6 HTMX partial routes; convert
        /diagnostics/ to a redirect to /dashboard/.
    2026-05-14 (#101): Remove legacy /queues/<engine>/submit/ route.
    2026-05-14 (#86): Add diagnostics/ route.
    2026-05-11: Task 4 — rename URL family to /admin/queues/ (plural).
    2026-05-08: Added file header.
"""
from django.urls import path
from django.views.generic import RedirectView

from . import views, views_dashboard, views_queue

app_name = "analysis"

urlpatterns = [
    path("queues/", views.queues_summary, name="queues_summary"),
    path("queues/stockfish/", views_queue.queue_stockfish, name="queue_stockfish"),
    path("queues/lc0/", views_queue.queue_lc0, name="queue_lc0"),
    path("queues/<str:engine>/reorder/", views_queue.queue_reorder, name="queue_reorder"),
    path("runpod/start/", views.runpod_start_view, name="runpod_start"),

    # Dashboard (consolidated worker observability).
    path("dashboard/", views_dashboard.dashboard, name="dashboard"),
    path("dashboard/banner/", views_dashboard.dashboard_banner, name="dash_banner"),
    path("dashboard/workers/", views_dashboard.dashboard_workers, name="dash_workers"),
    path("dashboard/queues/", views_dashboard.dashboard_queues, name="dash_queues"),
    path("dashboard/throughput/", views_dashboard.dashboard_throughput, name="dash_throughput"),
    path("dashboard/recent/", views_dashboard.dashboard_recent, name="dash_recent"),
    path("dashboard/failures/", views_dashboard.dashboard_failures, name="dash_failures"),

    # Legacy diagnostics URL — preserved as a redirect for bookmarks.
    path(
        "diagnostics/",
        RedirectView.as_view(pattern_name="analysis:dashboard", permanent=False),
        name="diagnostics",
    ),
]
```

---

### Task 1.5: Write smoke tests

**Files:**
- Create: `services/app/analysis/tests/test_dashboard_view.py`

- [ ] **Step 1: Write the failing smoke tests**

```python
"""
Title: test_dashboard_view.py — Tests for /admin/dashboard/
Description:
    Verifies the dashboard shell and its six HTMX partials each return
    200 to admin users, the page contains all six partial wrappers, the
    legacy /admin/diagnostics/ URL redirects to /admin/dashboard/, and
    non-admin users cannot access any of these endpoints.

Changelog:
    2026-05-14 (#106): Initial smoke tests for the wire-up slice.
"""
from __future__ import annotations

import uuid

import pytest
from django.urls import reverse

from accounts.models import User


def _make_user(role: str) -> User:
    """Create a test user with the given role."""
    return User.objects.create_user(
        email=f"{role}-dash-{uuid.uuid4().hex[:6]}@test",
        password="x",  # noqa: S106 — test-only
        role=role,
    )


@pytest.mark.django_db
def test_dashboard_shell_renders_for_admin(client):
    """The shell page returns 200 and contains all six partial wrappers."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    response = client.get(reverse("analysis:dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    for wrapper_id in (
        "dash-banner", "dash-workers", "dash-queues",
        "dash-throughput", "dash-recent", "dash-failures",
    ):
        assert f'id="{wrapper_id}"' in content


@pytest.mark.django_db
@pytest.mark.parametrize("name", [
    "dash_banner", "dash_workers", "dash_queues",
    "dash_throughput", "dash_recent", "dash_failures",
])
def test_each_partial_renders_for_admin(client, name):
    """Each of the six partial endpoints returns 200 for an admin."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    response = client.get(reverse(f"analysis:{name}"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_diagnostics_redirects_to_dashboard(client):
    """Legacy /admin/diagnostics/ URL 302s to /admin/dashboard/."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    response = client.get(reverse("analysis:diagnostics"))

    assert response.status_code == 302
    assert response.url.endswith(reverse("analysis:dashboard"))


@pytest.mark.django_db
def test_dashboard_requires_admin(client):
    """Non-admin users get a redirect (login) on the dashboard URL."""
    player = _make_user("player")
    client.force_login(player)

    response = client.get(reverse("analysis:dashboard"))

    # staff_member_required redirects to admin login
    assert response.status_code == 302
```

- [ ] **Step 2: Run tests; expect them to pass now**

```bash
source .venv/bin/activate
cd services/app && pytest analysis/tests/test_dashboard_view.py -v
```

Expected: 9 passing (1 shell + 6 partials + 1 redirect + 1 auth gate).

---

### Task 1.6: Quality gate + commit slice 1

- [ ] **Step 1: Lint + bandit + mypy on new files**

```bash
source .venv/bin/activate
ruff check services/app/analysis/views_dashboard.py services/app/analysis/urls.py services/app/analysis/tests/test_dashboard_view.py
bandit -ll services/app/analysis/views_dashboard.py services/app/analysis/urls.py services/app/analysis/tests/test_dashboard_view.py
mypy services/app/analysis/views_dashboard.py
```

Expected: all clean. Fix anything Medium+ from bandit before committing.

- [ ] **Step 2: Commit**

```bash
git add services/app/analysis/views_dashboard.py \
        services/app/analysis/urls.py \
        services/app/templates/analysis/dashboard.html \
        services/app/templates/analysis/_dash_*.html \
        services/app/analysis/tests/test_dashboard_view.py
git commit -m "$(cat <<'EOF'
feat(dashboard): wire /admin/dashboard/ shell + 6 HTMX partials (#106)

Stub partials only; real data lands in subsequent slices. Legacy
/admin/diagnostics/ URL preserved as a redirect to the new dashboard.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Slice 2 — Banner + Workers + helpers module (commit 2)

End state: helper module exists with liveness, uptime, hardware, and game-link helpers (each unit-tested). Banner + Workers partials render real data. Throughput helpers move to the new module without breaking diagnostics (which is still live as a redirect — but `queues_summary` may also use them; we keep its imports working).

### Task 2.1: Create `dashboard_helpers.py` and move shared helpers

**Files:**
- Create: `services/app/analysis/dashboard_helpers.py`
- Modify: `services/app/analysis/views.py` (remove the moved helpers, re-import from new module)

- [ ] **Step 1: Identify helpers to move**

Helpers being moved out of `views.py`:
- `_percentile` (sorted-list percentile)
- `_engine_throughput_row` (per-engine 24h/Nh rollup)
- `_throughput_for_window` (list of per-engine rows)
- `_failure_timestamp` (best-available timestamp for a failed job)
- `_worker_log_url_for` (linked WorkerLogUpload admin URL for a failure)
- `_build_failure_row` (template row dict for a failure)

The new module also adds **new** dashboard helpers (separate tasks below).

- [ ] **Step 2: Write `dashboard_helpers.py` with the moved helpers**

```python
"""
Title: dashboard_helpers.py — Pure helpers for the worker dashboard
Description:
    Pure-function helpers consumed by both the legacy queues_summary view
    and the consolidated /admin/dashboard/ partials. Includes percentile
    calculation, per-engine throughput rollups, failure-row construction,
    worker-liveness classification, rate/ETA calculation, recent-game
    grouping, and game-link resolution.

Changelog:
    2026-05-14 (#106): Initial extraction from views.py (#86) + new
        dashboard-specific helpers.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.urls import reverse
from django.utils import timezone

from analysis.models import AnalysisJob


__all__ = [
    "_percentile",
    "_engine_throughput_row",
    "_throughput_for_window",
    "_failure_timestamp",
    "_worker_log_url_for",
    "_build_failure_row",
]


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile of an already-sorted list.

    Args:
        sorted_values: Floats sorted ascending. Empty list returns ``None``.
        pct: Target percentile in [0.0, 1.0] (e.g. 0.5 for median).

    Returns:
        Interpolated percentile value, or ``None`` if input is empty.
    """
    # ... (move body verbatim from analysis/views.py)


def _engine_throughput_row(engine: str, hours: int) -> dict[str, Any]:
    """Compute throughput metrics for one engine over the last ``hours``.

    Args:
        engine: Engine name (e.g. ``"stockfish"`` or ``"lc0"``).
        hours: Window length, in hours, ending at the current time.

    Returns:
        Dict with keys ``engine``, ``completed``, ``games_per_hour``,
        ``avg_seconds``, ``p50_seconds``, ``p95_seconds``, ``failure_rate``.
    """
    # ... (move body verbatim from analysis/views.py)


def _throughput_for_window(hours: int = 24) -> list[dict[str, Any]]:
    """Per-engine throughput rows for the last ``hours``.

    Args:
        hours: Length of the rolling time window. Defaults to 24.

    Returns:
        One dict per known engine (stockfish, lc0).
    """
    return [_engine_throughput_row(engine, hours) for engine in ("stockfish", "lc0")]


def _failure_timestamp(job: AnalysisJob) -> Any:
    """Best-available timestamp for a failed job (``completed_at`` first)."""
    # ... (move body verbatim from analysis/views.py)


def _worker_log_url_for(job: AnalysisJob) -> str | None:
    """Admin URL for the WorkerLogUpload matching a failure, if any."""
    # ... (move body verbatim from analysis/views.py)


def _build_failure_row(job: AnalysisJob) -> dict[str, Any]:
    """Convert one failed AnalysisJob into a template row dict."""
    # ... (move body verbatim from analysis/views.py)
```

**Important:** copy each function body byte-for-byte from the current `views.py` (lines ~155–360). The signatures and behavior do not change in this task — only the location.

- [ ] **Step 3: Update `views.py` to import from the new module**

Replace the in-file definitions in `views.py` with:

```python
from analysis.dashboard_helpers import (
    _build_failure_row,
    _engine_throughput_row,
    _failure_timestamp,
    _percentile,
    _throughput_for_window,
    _worker_log_url_for,
)
```

Delete the now-duplicated function bodies from `views.py`. The `diagnostics_view` still calls `_throughput_for_window` and the recent-failures path uses `_build_failure_row` — both via the import above.

- [ ] **Step 4: Run the full analysis test suite — nothing should regress**

```bash
source .venv/bin/activate
cd services/app && pytest analysis/tests/ -v
```

Expected: existing diagnostics tests still pass; new dashboard smoke tests still pass.

- [ ] **Step 5: Quality gate + commit**

```bash
ruff check services/app/analysis/dashboard_helpers.py services/app/analysis/views.py
bandit -ll services/app/analysis/dashboard_helpers.py services/app/analysis/views.py
mypy services/app/analysis/dashboard_helpers.py services/app/analysis/views.py

git add services/app/analysis/dashboard_helpers.py services/app/analysis/views.py
git commit -m "refactor(analysis): extract dashboard helpers from views.py (#106)"
```

---

### Task 2.2: Liveness helper + tests

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py`
- Create: `services/app/analysis/tests/test_dashboard_helpers.py`

- [ ] **Step 1: Write the failing tests**

```python
"""
Title: test_dashboard_helpers.py — Unit tests for dashboard helpers
Description:
    Pure-function tests for the dashboard's liveness, uptime, hardware,
    rate, ETA, game-link, and recent-game grouping helpers.

Changelog:
    2026-05-14 (#106): Initial test module.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from analysis.dashboard_helpers import (
    LIVENESS_HEALTHY_SECONDS,
    LIVENESS_WARNING_SECONDS,
    _liveness_for,
)


def test_liveness_healthy_under_threshold():
    """Deltas below 60s return ``'healthy'``."""
    assert _liveness_for(timedelta(seconds=0)) == "healthy"
    assert _liveness_for(timedelta(seconds=59)) == "healthy"


def test_liveness_warning_between_thresholds():
    """Deltas in [60s, 120s) return ``'warning'``."""
    assert _liveness_for(timedelta(seconds=60)) == "warning"
    assert _liveness_for(timedelta(seconds=119)) == "warning"


def test_liveness_stale_at_or_above_warning_ceiling():
    """Deltas >=120s return ``'stale'``."""
    assert _liveness_for(timedelta(seconds=120)) == "stale"
    assert _liveness_for(timedelta(hours=1)) == "stale"


def test_liveness_none_treated_as_stale():
    """A missing delta (no heartbeat ever) is ``'stale'``."""
    assert _liveness_for(None) == "stale"


def test_liveness_thresholds_are_constants():
    """Thresholds are exported as module-level constants for reuse."""
    assert LIVENESS_HEALTHY_SECONDS == 60
    assert LIVENESS_WARNING_SECONDS == 120
```

- [ ] **Step 2: Run tests; expect ImportError / NameError**

```bash
cd services/app && pytest analysis/tests/test_dashboard_helpers.py -v
```

Expected: fail with `ImportError: cannot import name 'LIVENESS_HEALTHY_SECONDS'`.

- [ ] **Step 3: Implement**

Append to `dashboard_helpers.py`:

```python
LIVENESS_HEALTHY_SECONDS = 60
LIVENESS_WARNING_SECONDS = 120


def _liveness_for(delta: timedelta | None) -> str:
    """Classify a "time since last_seen" delta into a liveness bucket.

    Args:
        delta: ``now - last_seen``, or ``None`` if no heartbeat exists.

    Returns:
        ``"healthy"`` when below 60s, ``"warning"`` when in [60s, 120s),
        ``"stale"`` at or above 120s and for ``None``.
    """
    if delta is None:
        return "stale"
    seconds = delta.total_seconds()
    if seconds < LIVENESS_HEALTHY_SECONDS:
        return "healthy"
    if seconds < LIVENESS_WARNING_SECONDS:
        return "warning"
    return "stale"
```

Also add the names to `__all__`:

```python
__all__ = [
    # ... existing ...
    "LIVENESS_HEALTHY_SECONDS",
    "LIVENESS_WARNING_SECONDS",
    "_liveness_for",
]
```

- [ ] **Step 4: Run tests; expect pass**

```bash
cd services/app && pytest analysis/tests/test_dashboard_helpers.py -v
```

Expected: 5 passing.

- [ ] **Step 5: Commit (squash later with the rest of slice 2)**

```bash
git add services/app/analysis/dashboard_helpers.py services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(dashboard): add _liveness_for helper + thresholds (#106)"
```

---

### Task 2.3: Uptime + memory formatters

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py`
- Modify: `services/app/analysis/tests/test_dashboard_helpers.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_dashboard_helpers.py`:

```python
from analysis.dashboard_helpers import _format_uptime, _format_memory_mb


def test_format_uptime_seconds():
    """Sub-minute uptimes are formatted in seconds."""
    assert _format_uptime(timedelta(seconds=5)) == "5s"
    assert _format_uptime(timedelta(seconds=59)) == "59s"


def test_format_uptime_minutes():
    """Sub-hour uptimes are formatted in minutes."""
    assert _format_uptime(timedelta(minutes=1)) == "1m"
    assert _format_uptime(timedelta(minutes=22, seconds=30)) == "22m"
    assert _format_uptime(timedelta(minutes=59, seconds=59)) == "59m"


def test_format_uptime_hours_and_days():
    """Long uptimes show hours, then days+hours."""
    assert _format_uptime(timedelta(hours=1)) == "1h 0m"
    assert _format_uptime(timedelta(hours=3, minutes=12)) == "3h 12m"
    assert _format_uptime(timedelta(days=1, hours=4)) == "1d 4h"
    assert _format_uptime(timedelta(days=10)) == "10d 0h"


def test_format_uptime_none_returns_dash():
    """Missing started_at renders as an em-dash placeholder."""
    assert _format_uptime(None) == "—"


def test_format_memory_mb_rounds_to_gb_above_1024():
    """Memory >=1024 MB renders as GB to one decimal."""
    assert _format_memory_mb(62000) == "60.5 GB"
    assert _format_memory_mb(1024) == "1.0 GB"


def test_format_memory_mb_keeps_megabytes_below_1024():
    """Memory <1024 MB stays in MB."""
    assert _format_memory_mb(512) == "512 MB"


def test_format_memory_mb_none_returns_dash():
    """Missing memory renders as an em-dash placeholder."""
    assert _format_memory_mb(None) == "—"
```

- [ ] **Step 2: Run tests; expect ImportError**

```bash
cd services/app && pytest analysis/tests/test_dashboard_helpers.py -v -k "uptime or memory"
```

- [ ] **Step 3: Implement**

Append to `dashboard_helpers.py`:

```python
def _format_uptime(delta: timedelta | None) -> str:
    """Format ``now - started_at`` as a compact human string.

    Args:
        delta: Worker uptime, or ``None`` if not reported.

    Returns:
        ``"—"`` for ``None``; ``"Ns"`` under a minute; ``"Nm"`` under an
        hour; ``"Xh Ym"`` under a day; ``"Xd Yh"`` otherwise.
    """
    if delta is None:
        return "—"
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        hours, rem = divmod(total, 3600)
        return f"{hours}h {rem // 60}m"
    days, rem = divmod(total, 86400)
    return f"{days}d {rem // 3600}h"


def _format_memory_mb(mb: int | None) -> str:
    """Format a megabyte count as MB or GB depending on magnitude.

    Args:
        mb: Memory in megabytes, or ``None``.

    Returns:
        ``"—"`` for ``None``; ``"<N> MB"`` below 1024; ``"<N>.<d> GB"``
        above.
    """
    if mb is None:
        return "—"
    if mb < 1024:
        return f"{mb} MB"
    return f"{mb / 1024:.1f} GB"
```

Add both names to `__all__`.

- [ ] **Step 4: Run tests; expect pass; commit**

```bash
cd services/app && pytest analysis/tests/test_dashboard_helpers.py -v
git add services/app/analysis/dashboard_helpers.py services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(dashboard): add uptime + memory formatters (#106)"
```

---

### Task 2.4: Game-link resolver

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py`
- Modify: `services/app/analysis/tests/test_dashboard_helpers.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_dashboard_helpers.py`:

```python
import uuid

from django.utils import timezone

from analysis.dashboard_helpers import _game_link_for
from games.models import Game


def _make_game_for_link() -> Game:
    unique = f"link-{uuid.uuid4().hex[:8]}"
    return Game.objects.create(
        id=unique,
        slug=unique,
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )


@pytest.mark.django_db
def test_game_link_for_resolves_pk_to_slug():
    """A numeric-string current_game_id is looked up and linked by slug."""
    game = _make_game_for_link()
    label, url = _game_link_for(str(game.pk))
    assert label == f"#{game.pk}"
    assert url is not None
    assert game.slug in url


@pytest.mark.django_db
def test_game_link_for_unknown_pk_returns_label_only():
    """An unknown numeric pk yields a label but no URL."""
    label, url = _game_link_for("nonexistent-id")
    assert label == "#nonexistent-id"
    assert url is None


def test_game_link_for_empty_returns_dash():
    """Missing/empty input renders as an em-dash placeholder."""
    label, url = _game_link_for("")
    assert label == "—"
    assert url is None
    label2, url2 = _game_link_for(None)
    assert label2 == "—"
    assert url2 is None
```

- [ ] **Step 2: Run tests; expect ImportError**

- [ ] **Step 3: Implement**

Append to `dashboard_helpers.py`:

```python
def _game_link_for(current_game_id: str | None) -> tuple[str, str | None]:
    """Resolve a worker's ``current_game_id`` to a (label, URL) tuple.

    Workers store ``current_game_id`` as ``str(Game.pk)``. We look the
    game up to get its ``slug`` for URL construction; if it is missing
    we still return a label so the card has something to show.

    Args:
        current_game_id: The string stored on ``WorkerHeartbeat``.

    Returns:
        ``(label, url)`` — label is ``"#<id>"`` or ``"—"`` when empty;
        url is the game analysis page URL when the lookup succeeds,
        else ``None``.
    """
    if not current_game_id:
        return ("—", None)
    label = f"#{current_game_id}"
    from games.models import Game  # local import: avoid app-load cycle

    slug = (
        Game.objects.filter(pk=current_game_id)
        .values_list("slug", flat=True)
        .first()
    )
    if slug is None:
        return (label, None)
    return (label, reverse("games:analysis", kwargs={"slug": slug}))
```

Add `_game_link_for` to `__all__`.

- [ ] **Step 4: Run tests; expect pass; commit**

```bash
cd services/app && pytest analysis/tests/test_dashboard_helpers.py -v
git add services/app/analysis/dashboard_helpers.py services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(dashboard): add _game_link_for helper (#106)"
```

---

### Task 2.5: Banner partial view

**Files:**
- Modify: `services/app/analysis/views_dashboard.py`
- Modify: `services/app/templates/analysis/_dash_banner.html`
- Modify: `services/app/analysis/tests/test_dashboard_view.py`

- [ ] **Step 1: Write the failing test**

Append to `test_dashboard_view.py`:

```python
from datetime import timedelta
from django.utils import timezone

from analysis.models import AnalysisJob, WorkerHeartbeat


def _make_dash_game(suffix: str = "") -> "Game":
    """Create a minimal Game row usable for URL reversal in dashboard tests."""
    from games.models import Game

    unique = f"dash-{suffix}-{uuid.uuid4().hex[:8]}"
    return Game.objects.create(
        id=unique,
        slug=unique,
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )


def _make_completed_job(engine: str, duration: float = 60.0,
                        minutes_ago: float = 1.0) -> AnalysisJob:
    """Create a completed AnalysisJob with the given duration."""
    completed_at = timezone.now() - timedelta(minutes=minutes_ago)
    return AnalysisJob.objects.create(
        game=_make_dash_game(engine),
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        duration_seconds=duration,
        started_at=completed_at - timedelta(seconds=duration),
        completed_at=completed_at,
    )


@pytest.mark.django_db
def test_banner_reports_worker_and_job_counts(client):
    """Banner shows ``healthy/total`` workers, pending count, and done-today."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    now = timezone.now()
    WorkerHeartbeat.objects.create(worker_id="w-fresh", status="working",
                                   engine="stockfish")
    stale = WorkerHeartbeat.objects.create(worker_id="w-stale", status="working",
                                           engine="lc0")
    WorkerHeartbeat.objects.filter(pk=stale.pk).update(last_seen=now - timedelta(minutes=10))

    _make_completed_job("stockfish", duration=60.0, minutes_ago=30)

    response = client.get(reverse("analysis:dash_banner"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "1/2" in body  # 1 healthy / 2 total
```

- [ ] **Step 2: Run, confirm failure (banner is still stub)**

- [ ] **Step 3: Implement the view**

Replace `dashboard_banner` in `views_dashboard.py`:

```python
@staff_member_required
def dashboard_banner(request: HttpRequest) -> HttpResponse:
    """Render the health-banner partial.

    Reports ``healthy_workers / total_workers``, ``pending_jobs`` across
    all engines, and ``jobs_completed_today`` (UTC midnight rollover).
    Banner-level "health" is the worst liveness state across workers.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_banner.html``.
    """
    from analysis.models import AnalysisJob, WorkerHeartbeat
    from analysis.dashboard_helpers import _liveness_for

    now = timezone.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    workers = list(WorkerHeartbeat.objects.all())
    livenesses = [_liveness_for(now - w.last_seen) for w in workers]
    healthy = sum(1 for v in livenesses if v == "healthy")

    if not workers or "stale" in livenesses:
        banner_state = "stale"
    elif "warning" in livenesses:
        banner_state = "warning"
    else:
        banner_state = "healthy"

    pending = AnalysisJob.objects.filter(
        status__in=[AnalysisJob.STATUS_PENDING, AnalysisJob.STATUS_SUBMITTED],
    ).count()
    done_today = AnalysisJob.objects.filter(
        status=AnalysisJob.STATUS_COMPLETED,
        completed_at__gte=midnight,
    ).count()

    context = {
        "healthy_workers": healthy,
        "total_workers": len(workers),
        "pending": pending,
        "done_today": done_today,
        "banner_state": banner_state,
    }
    return render(request, "analysis/_dash_banner.html", context)
```

Add `from django.utils import timezone` at module top.

- [ ] **Step 4: Implement the template**

Replace `_dash_banner.html`:

```html
{% comment %}
  Title: _dash_banner.html — Health banner partial
  Description: One-line summary across the top of the dashboard.
  Changelog:
      2026-05-14 (#106): Initial real implementation.
{% endcomment %}
<div class="pg-section dash-banner dash-banner--{{ banner_state }}">
  <span class="dash-dot dash-dot--{{ banner_state }}"></span>
  <strong>{{ healthy_workers }}/{{ total_workers }}</strong>
  worker{{ total_workers|pluralize }} healthy
  &middot;
  <strong>{{ pending }}</strong> pending
  &middot;
  <strong>{{ done_today }}</strong> done today
</div>
```

- [ ] **Step 5: Run all dashboard tests; expect pass**

```bash
cd services/app && pytest analysis/tests/test_dashboard_view.py analysis/tests/test_dashboard_helpers.py -v
```

---

### Task 2.6: Workers partial view

**Files:**
- Modify: `services/app/analysis/views_dashboard.py`
- Modify: `services/app/templates/analysis/_dash_workers.html`
- Modify: `services/app/analysis/tests/test_dashboard_view.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
@pytest.mark.django_db
def test_workers_partial_lists_each_heartbeat(client):
    """Each WorkerHeartbeat row produces a card with its worker_id."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    WorkerHeartbeat.objects.create(
        worker_id="runpod-stockfish",
        engine="stockfish",
        status="working",
        current_game_id="42",
        jobs_completed=6,
        jobs_failed=0,
        cpu_model="EPYC 75F3",
        cpu_cores=16,
        memory_mb=62000,
    )

    response = client.get(reverse("analysis:dash_workers"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "runpod-stockfish" in body
    assert "#42" in body
    assert "60.5 GB" in body  # _format_memory_mb output
```

- [ ] **Step 2: Implement the view**

Replace `dashboard_workers`:

```python
@staff_member_required
def dashboard_workers(request: HttpRequest) -> HttpResponse:
    """Render the workers partial (one card per WorkerHeartbeat).

    Each card carries: status dot color (from liveness bucket), seconds
    since last_seen, current game (linked when resolvable), jobs
    completed/failed counters, uptime, engine, hardware footer.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_workers.html``.
    """
    from analysis.models import WorkerHeartbeat
    from analysis.dashboard_helpers import (
        _format_memory_mb, _format_uptime, _game_link_for, _liveness_for,
    )

    now = timezone.now()
    cards: list[dict[str, Any]] = []
    for w in WorkerHeartbeat.objects.order_by("-last_seen"):
        delta_seen = now - w.last_seen if w.last_seen else None
        uptime = now - w.started_at if w.started_at else None
        game_label, game_url = _game_link_for(w.current_game_id)
        cards.append({
            "worker_id": w.worker_id,
            "engine": w.engine,
            "status": w.status,
            "status_message": w.status_message,
            "liveness": _liveness_for(delta_seen),
            "seconds_since_seen": int(delta_seen.total_seconds()) if delta_seen else None,
            "current_game_label": game_label,
            "current_game_url": game_url,
            "jobs_completed": w.jobs_completed,
            "jobs_failed": w.jobs_failed,
            "uptime": _format_uptime(uptime),
            "cpu_model": w.cpu_model or "—",
            "cpu_cores": w.cpu_cores,
            "memory": _format_memory_mb(w.memory_mb),
        })
    return render(request, "analysis/_dash_workers.html", {"cards": cards})
```

Add `from typing import Any` at module top.

- [ ] **Step 3: Implement the template**

Replace `_dash_workers.html`:

```html
{% comment %}
  Title: _dash_workers.html — Worker heartbeat cards
  Description: One card per WorkerHeartbeat row.
  Changelog:
      2026-05-14 (#106): Initial real implementation.
{% endcomment %}
<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Workers ({{ cards|length }})</span>
    <span class="pg-caption">live heartbeats — refresh every 5s</span>
  </div>
  {% if cards %}
    <div class="dash-worker-grid">
      {% for card in cards %}
        <div class="dash-worker-card dash-worker-card--{{ card.liveness }}">
          <div class="dash-worker-card__head">
            <span class="dash-dot dash-dot--{{ card.liveness }}"></span>
            <strong>{{ card.worker_id }}</strong>
            <span class="dash-worker-card__seen">
              {% if card.seconds_since_seen is not None %}{{ card.seconds_since_seen }}s{% else %}—{% endif %}
            </span>
          </div>
          <div class="dash-worker-card__row">
            <span class="pg-caption">{{ card.status }}</span>
            {% if card.status_message %}<span class="pg-caption">· {{ card.status_message }}</span>{% endif %}
          </div>
          <div class="dash-worker-card__row">
            Game
            {% if card.current_game_url %}
              <a href="{{ card.current_game_url }}">{{ card.current_game_label }}</a>
            {% else %}
              {{ card.current_game_label }}
            {% endif %}
          </div>
          <div class="dash-worker-card__row">
            ✓ {{ card.jobs_completed }} &nbsp;&nbsp; ✗ {{ card.jobs_failed }}
          </div>
          <div class="dash-worker-card__foot pg-caption">
            up {{ card.uptime }} · {{ card.engine }}<br>
            {{ card.cpu_cores|default:"—" }}c · {{ card.memory }}
          </div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <span class="pg-caption">No worker heartbeats yet.</span>
  {% endif %}
</div>
```

- [ ] **Step 4: Run all dashboard tests; expect pass**

```bash
cd services/app && pytest analysis/tests/ -v
```

- [ ] **Step 5: Quality gate + commit slice 2**

```bash
ruff check services/app/analysis/
bandit -ll services/app/analysis/dashboard_helpers.py services/app/analysis/views_dashboard.py
mypy services/app/analysis/dashboard_helpers.py services/app/analysis/views_dashboard.py

git add services/app/analysis/views_dashboard.py \
        services/app/templates/analysis/_dash_banner.html \
        services/app/templates/analysis/_dash_workers.html \
        services/app/analysis/tests/test_dashboard_view.py
git commit -m "feat(dashboard): banner + workers partials live data (#106)"
```

---

## Slice 3 — Queues + Throughput (commit 3)

### Task 3.1: Rate + ETA helpers

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py`
- Modify: `services/app/analysis/tests/test_dashboard_helpers.py`

- [ ] **Step 1: Write the failing tests**

```python
from analysis.dashboard_helpers import _eta_for, _rate_per_min


@pytest.mark.django_db
def test_rate_per_min_returns_zero_when_no_recent_completions():
    """No recent completions → 0.0 jobs/min."""
    rate = _rate_per_min("stockfish", window_minutes=10)
    assert rate == 0.0


@pytest.mark.django_db
def test_rate_per_min_counts_completions_inside_window():
    """Five completions in the window → 0.5 jobs/min."""
    # (build 5 AnalysisJob rows with completed_at within last 10 min,
    #  same pattern as test_diagnostics_view._make_completed_job)
    rate = _rate_per_min("stockfish", window_minutes=10)
    assert rate == pytest.approx(0.5)


def test_eta_for_zero_rate_returns_none():
    """Rate of 0 → ETA is ``None`` (renders as ``—``)."""
    assert _eta_for(pending=42, rate_per_min=0.0) is None


def test_eta_for_returns_formatted_string():
    """Pending=60 at 1/min → ``"1h 0m"``."""
    assert _eta_for(pending=60, rate_per_min=1.0) == "1h 0m"
    assert _eta_for(pending=30, rate_per_min=1.0) == "30m"
    assert _eta_for(pending=5, rate_per_min=10.0) == "30s"
```

- [ ] **Step 2: Implement**

Append to `dashboard_helpers.py`:

```python
def _rate_per_min(engine: str, window_minutes: int = 10) -> float:
    """Per-minute completion rate over the last ``window_minutes``.

    Args:
        engine: Engine name to filter on.
        window_minutes: Trailing window length. Defaults to 10.

    Returns:
        Completions in window divided by ``window_minutes``.
    """
    cutoff = timezone.now() - timedelta(minutes=window_minutes)
    completed = AnalysisJob.objects.filter(
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        completed_at__gte=cutoff,
    ).count()
    return completed / float(window_minutes)


def _eta_for(pending: int, rate_per_min: float) -> str | None:
    """Estimate "time to drain" pending jobs at current rate.

    Args:
        pending: Pending job count.
        rate_per_min: Completion rate in jobs per minute.

    Returns:
        ``None`` when rate is zero or pending is zero. Otherwise a
        compact string: seconds under a minute, ``Nm`` under an hour,
        ``Xh Ym`` otherwise.
    """
    if pending <= 0 or rate_per_min <= 0:
        return None
    total_seconds = int((pending / rate_per_min) * 60)
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m"
    hours, rem = divmod(total_seconds, 3600)
    return f"{hours}h {rem // 60}m"
```

Add both to `__all__`.

- [ ] **Step 3: Run tests; commit**

```bash
cd services/app && pytest analysis/tests/test_dashboard_helpers.py -v
git add services/app/analysis/dashboard_helpers.py services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(dashboard): add _rate_per_min + _eta_for helpers (#106)"
```

---

### Task 3.2: Queues partial view

**Files:**
- Modify: `services/app/analysis/views_dashboard.py`
- Modify: `services/app/templates/analysis/_dash_queues.html`
- Modify: `services/app/analysis/tests/test_dashboard_view.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_queues_partial_lists_both_engines(client):
    """Queues partial renders one row per engine with counts + rate."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    response = client.get(reverse("analysis:dash_queues"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "stockfish" in body.lower()
    assert "lc0" in body.lower()
```

- [ ] **Step 2: Implement the view**

Replace `dashboard_queues`:

```python
@staff_member_required
def dashboard_queues(request: HttpRequest) -> HttpResponse:
    """Render the queues partial.

    For each known engine, show pending/running counts, the per-minute
    completion rate over the last 10 minutes, and an ETA to drain.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_queues.html``.
    """
    from analysis.models import AnalysisJob
    from analysis.dashboard_helpers import _eta_for, _rate_per_min

    rows: list[dict[str, Any]] = []
    for engine in ("stockfish", "lc0"):
        pending = AnalysisJob.objects.filter(
            engine=engine,
            status__in=[AnalysisJob.STATUS_PENDING, AnalysisJob.STATUS_SUBMITTED],
        ).count()
        running = AnalysisJob.objects.filter(
            engine=engine, status=AnalysisJob.STATUS_RUNNING,
        ).count()
        rate = _rate_per_min(engine)
        rows.append({
            "engine": engine,
            "pending": pending,
            "running": running,
            "rate": round(rate, 2),
            "eta": _eta_for(pending, rate),
        })
    return render(request, "analysis/_dash_queues.html", {"rows": rows})
```

- [ ] **Step 3: Implement the template**

```html
{% comment %}
  Title: _dash_queues.html — Per-engine queue depth + rate + ETA
  Changelog:
      2026-05-14 (#106): Initial real implementation.
{% endcomment %}
<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Queues</span>
    <span class="pg-caption">depth + 10-minute completion rate</span>
  </div>
  <table class="pg-table">
    <thead>
      <tr>
        <th>Engine</th><th>Pending</th><th>Running</th>
        <th>Rate (10m)</th><th>ETA</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
        <tr>
          <td>{{ row.engine|title }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.running }}</td>
          <td>{{ row.rate }} / min</td>
          <td>{% if row.eta %}~{{ row.eta }}{% else %}—{% endif %}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
```

- [ ] **Step 4: Run + commit (squash with throughput later)**

```bash
cd services/app && pytest analysis/tests/test_dashboard_view.py::test_queues_partial_lists_both_engines -v
git add services/app/analysis/views_dashboard.py \
        services/app/templates/analysis/_dash_queues.html \
        services/app/analysis/tests/test_dashboard_view.py
git commit -m "feat(dashboard): queues partial live data (#106)"
```

---

### Task 3.3: Throughput partial view

**Files:**
- Modify: `services/app/analysis/views_dashboard.py`
- Modify: `services/app/templates/analysis/_dash_throughput.html`
- Modify: `services/app/analysis/tests/test_dashboard_view.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_throughput_partial_lists_engines_and_windows(client):
    """Throughput partial renders one row per engine and 1h/6h/24h columns."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    response = client.get(reverse("analysis:dash_throughput"))

    assert response.status_code == 200
    body = response.content.decode()
    for header in ("Stockfish", "Lc0", "1h", "6h", "24h"):
        assert header in body
```

- [ ] **Step 2: Implement the view**

```python
@staff_member_required
def dashboard_throughput(request: HttpRequest) -> HttpResponse:
    """Render the throughput partial (1h / 6h / 24h windows).

    Reuses :func:`analysis.dashboard_helpers._engine_throughput_row` to
    compute each engine's completed count and p50/p95 durations within
    each window.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_throughput.html``.
    """
    from analysis.dashboard_helpers import _engine_throughput_row

    engines = ("stockfish", "lc0")
    windows = (1, 6, 24)
    rows: list[dict[str, Any]] = []
    for engine in engines:
        window_data = {h: _engine_throughput_row(engine, h) for h in windows}
        # Take p50/p95 from the 24h window so the columns are stable.
        twenty_four = window_data[24]
        rows.append({
            "engine": engine,
            "h1": window_data[1]["completed"],
            "h6": window_data[6]["completed"],
            "h24": window_data[24]["completed"],
            "p50": twenty_four["p50_seconds"],
            "p95": twenty_four["p95_seconds"],
        })
    return render(request, "analysis/_dash_throughput.html", {"rows": rows})
```

- [ ] **Step 3: Implement the template**

```html
{% comment %}
  Title: _dash_throughput.html — 1h / 6h / 24h completion windows
  Changelog:
      2026-05-14 (#106): Initial real implementation.
{% endcomment %}
<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Throughput</span>
    <span class="pg-caption">completed jobs across rolling windows · p50/p95 from 24h</span>
  </div>
  <table class="pg-table">
    <thead>
      <tr>
        <th>Engine</th><th>1h</th><th>6h</th><th>24h</th>
        <th>p50 (s)</th><th>p95 (s)</th>
      </tr>
    </thead>
    <tbody>
      {% for row in rows %}
        <tr>
          <td>{{ row.engine|title }}</td>
          <td>{{ row.h1 }}</td>
          <td>{{ row.h6 }}</td>
          <td>{{ row.h24 }}</td>
          <td>{% if row.p50 %}{{ row.p50 }}{% else %}—{% endif %}</td>
          <td>{% if row.p95 %}{{ row.p95 }}{% else %}—{% endif %}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
```

- [ ] **Step 4: Run + quality gate + commit slice 3**

```bash
cd services/app && pytest analysis/tests/ -v
ruff check services/app/analysis/
bandit -ll services/app/analysis/views_dashboard.py services/app/analysis/dashboard_helpers.py

git add services/app/analysis/views_dashboard.py \
        services/app/templates/analysis/_dash_throughput.html \
        services/app/analysis/tests/test_dashboard_view.py
git commit -m "feat(dashboard): throughput partial 1h/6h/24h windows (#106)"
```

---

## Slice 4 — Recently completed (commit 4)

### Task 4.1: `_group_recent_by_game` helper

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py`
- Modify: `services/app/analysis/tests/test_dashboard_helpers.py`

- [ ] **Step 1: Write the failing tests**

```python
from analysis.dashboard_helpers import _group_recent_by_game
from analysis.models import AnalysisJob


def _make_completed(game, engine, duration_seconds, completed_at):
    return AnalysisJob.objects.create(
        game=game,
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        duration_seconds=duration_seconds,
        started_at=completed_at - timedelta(seconds=duration_seconds),
        completed_at=completed_at,
    )


@pytest.mark.django_db
def test_group_recent_returns_empty_when_no_jobs():
    """Empty DB → empty list."""
    assert _group_recent_by_game(limit=25) == []


@pytest.mark.django_db
def test_group_recent_groups_by_game_and_pivots_engines():
    """One game with both engines complete → single row, both columns filled."""
    game = _make_game_for_link()
    now = timezone.now()
    _make_completed(game, "stockfish", 252.0, now - timedelta(minutes=2))
    _make_completed(game, "lc0", 663.0, now - timedelta(minutes=1))

    rows = _group_recent_by_game(limit=25)

    assert len(rows) == 1
    row = rows[0]
    assert row["game_id"] == str(game.pk)
    assert row["stockfish_seconds"] == 252.0
    assert row["lc0_seconds"] == 663.0
    assert row["latest_completed_at"] is not None


@pytest.mark.django_db
def test_group_recent_handles_partial_completion():
    """A game with only stockfish done → lc0 column is None."""
    game = _make_game_for_link()
    now = timezone.now()
    _make_completed(game, "stockfish", 100.0, now - timedelta(minutes=5))

    rows = _group_recent_by_game(limit=25)

    assert len(rows) == 1
    row = rows[0]
    assert row["stockfish_seconds"] == 100.0
    assert row["lc0_seconds"] is None


@pytest.mark.django_db
def test_group_recent_orders_by_latest_completion_desc():
    """Most recently completed game appears first."""
    older = _make_game_for_link()
    newer = _make_game_for_link()
    now = timezone.now()
    _make_completed(older, "stockfish", 60.0, now - timedelta(hours=1))
    _make_completed(newer, "stockfish", 60.0, now - timedelta(minutes=1))

    rows = _group_recent_by_game(limit=25)

    assert [r["game_id"] for r in rows] == [str(newer.pk), str(older.pk)]


@pytest.mark.django_db
def test_group_recent_respects_limit():
    """``limit`` caps the number of distinct games returned."""
    now = timezone.now()
    for i in range(30):
        g = _make_game_for_link()
        _make_completed(g, "stockfish", 60.0, now - timedelta(minutes=i))

    assert len(_group_recent_by_game(limit=25)) == 25
```

- [ ] **Step 2: Implement**

Append to `dashboard_helpers.py`:

```python
def _group_recent_by_game(limit: int = 25) -> list[dict[str, Any]]:
    """Group recently completed AnalysisJobs by game and pivot engine → column.

    Pulls the most recent ``limit * 4`` completed jobs (a buffer that
    handles the common 2-engines-per-game case), groups them by
    ``game_id`` in Python, and produces one row per game with separate
    columns for each engine's ``duration_seconds`` plus the latest
    ``completed_at`` and the game's ``slug`` for URL building.

    Args:
        limit: Maximum number of distinct games to return.

    Returns:
        List of dicts with keys ``game_id``, ``game_slug``,
        ``stockfish_seconds``, ``lc0_seconds`` (each ``float | None``),
        ``latest_completed_at``.
    """
    buffer_size = max(limit * 4, 50)
    recent = list(
        AnalysisJob.objects
        .filter(status=AnalysisJob.STATUS_COMPLETED, completed_at__isnull=False)
        .select_related("game")
        .order_by("-completed_at")
        .values(
            "game_id", "game__slug", "engine", "duration_seconds",
            "completed_at",
        )[:buffer_size]
    )

    by_game: dict[str, dict[str, Any]] = {}
    for job in recent:
        gid = str(job["game_id"])
        row = by_game.setdefault(gid, {
            "game_id": gid,
            "game_slug": job["game__slug"],
            "stockfish_seconds": None,
            "lc0_seconds": None,
            "latest_completed_at": job["completed_at"],
        })
        if job["completed_at"] > row["latest_completed_at"]:
            row["latest_completed_at"] = job["completed_at"]
        if job["engine"] == "stockfish":
            row["stockfish_seconds"] = job["duration_seconds"]
        elif job["engine"] == "lc0":
            row["lc0_seconds"] = job["duration_seconds"]

    rows = sorted(by_game.values(), key=lambda r: r["latest_completed_at"], reverse=True)
    return rows[:limit]
```

Add to `__all__`.

- [ ] **Step 3: Run tests; commit**

```bash
cd services/app && pytest analysis/tests/test_dashboard_helpers.py -v
git add services/app/analysis/dashboard_helpers.py services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(dashboard): add _group_recent_by_game helper (#106)"
```

---

### Task 4.2: Recently-completed partial view

**Files:**
- Modify: `services/app/analysis/views_dashboard.py`
- Modify: `services/app/templates/analysis/_dash_recent.html`
- Modify: `services/app/analysis/tests/test_dashboard_view.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_recent_partial_links_to_game_page(client):
    """Each row links to the per-game analysis page using the slug."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    game = _make_dash_game("recent")
    now = timezone.now()
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED,
        duration_seconds=252.0,
        started_at=now - timedelta(minutes=5),
        completed_at=now - timedelta(minutes=2),
    )

    response = client.get(reverse("analysis:dash_recent"))

    assert response.status_code == 200
    body = response.content.decode()
    assert game.slug in body
    assert "252s" in body
```

- [ ] **Step 2: Implement the view**

```python
@staff_member_required
def dashboard_recent(request: HttpRequest) -> HttpResponse:
    """Render the recently-completed partial.

    Groups the most recent completed jobs by game (last 25 games) and
    shows per-engine runtime side by side, with a link to each game's
    analysis page.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_recent.html``.
    """
    from analysis.dashboard_helpers import _group_recent_by_game

    rows = _group_recent_by_game(limit=25)
    for row in rows:
        row["game_url"] = (
            reverse("games:analysis", kwargs={"slug": row["game_slug"]})
            if row["game_slug"] else None
        )
    return render(request, "analysis/_dash_recent.html", {"rows": rows})
```

Add `from django.urls import reverse` at module top.

- [ ] **Step 3: Implement the template**

```html
{% comment %}
  Title: _dash_recent.html — Recently completed games (grouped by game)
  Changelog:
      2026-05-14 (#106): Initial real implementation.
{% endcomment %}
<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Recently completed</span>
    <span class="pg-caption">last 25 games · refresh every 30s</span>
  </div>
  {% if rows %}
    <table class="pg-table">
      <thead>
        <tr>
          <th>Game</th><th>Stockfish</th><th>Lc0</th><th>Completed</th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
          <tr>
            <td>
              {% if row.game_url %}
                <a href="{{ row.game_url }}">#{{ row.game_id }}</a>
              {% else %}
                #{{ row.game_id }}
              {% endif %}
            </td>
            <td>{% if row.stockfish_seconds %}{{ row.stockfish_seconds|floatformat:0 }}s{% else %}—{% endif %}</td>
            <td>{% if row.lc0_seconds %}{{ row.lc0_seconds|floatformat:0 }}s{% else %}—{% endif %}</td>
            <td>{{ row.latest_completed_at|timesince }} ago</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <span class="pg-caption">No games completed yet.</span>
  {% endif %}
</div>
```

- [ ] **Step 4: Run + commit**

```bash
cd services/app && pytest analysis/tests/ -v
git add services/app/analysis/views_dashboard.py \
        services/app/templates/analysis/_dash_recent.html \
        services/app/analysis/tests/test_dashboard_view.py
git commit -m "feat(dashboard): recently completed partial (#106)"
```

---

## Slice 5 — Failures + cleanup + frontend polish (commit 5+)

### Task 5.1: Failures partial view

**Files:**
- Modify: `services/app/analysis/views_dashboard.py`
- Modify: `services/app/templates/analysis/_dash_failures.html`
- Modify: `services/app/analysis/tests/test_dashboard_view.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_failures_partial_lists_recent_failures(client):
    """A failed AnalysisJob shows up in the failures partial."""
    admin = _make_user("admin")
    admin.is_staff = True
    admin.save()
    client.force_login(admin)

    game = _make_dash_game("fail")
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_FAILED,
        error_message="boom",
        completed_at=timezone.now(),
    )

    response = client.get(reverse("analysis:dash_failures"))

    assert response.status_code == 200
    assert "boom" in response.content.decode()
```

- [ ] **Step 2: Implement the view**

```python
@staff_member_required
def dashboard_failures(request: HttpRequest) -> HttpResponse:
    """Render the recent-failures partial.

    Surfaces the 10 most-recently-failed analysis jobs, each linked to
    the matching worker log upload when one is available.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_failures.html``.
    """
    from analysis.models import AnalysisJob
    from analysis.dashboard_helpers import _build_failure_row

    failures = (
        AnalysisJob.objects
        .filter(status=AnalysisJob.STATUS_FAILED)
        .order_by("-completed_at", "-last_error_at", "-created_at")[:10]
    )
    rows = [_build_failure_row(job) for job in failures]
    return render(request, "analysis/_dash_failures.html", {"rows": rows})
```

- [ ] **Step 3: Implement the template**

The existing `diagnostics.html` already renders this row dict — copy its failure-row markup verbatim into `_dash_failures.html` and wrap it with the standard `pg-section` header. Use `<details>`/`<summary>` to keep it collapsed by default:

```html
{% comment %}
  Title: _dash_failures.html — Recent failures (collapsed by default)
  Changelog:
      2026-05-14 (#106): Initial implementation — reuses row dict from
          dashboard_helpers._build_failure_row.
{% endcomment %}
<details class="pg-section">
  <summary class="pg-head">
    <span class="pg-title">Recent failures ({{ rows|length }})</span>
    <span class="pg-caption">click to expand</span>
  </summary>
  {% if rows %}
    <table class="pg-table">
      <thead>
        <tr><th>When</th><th>Engine</th><th>Game</th><th>Error</th><th>Log</th></tr>
      </thead>
      <tbody>
        {% for row in rows %}
          <tr>
            <td>{{ row.timestamp|timesince }} ago</td>
            <td>{{ row.engine }}</td>
            <td>{{ row.game_id }}</td>
            <td><code>{{ row.error_snippet }}</code></td>
            <td>{% if row.log_url %}<a href="{{ row.log_url }}">log</a>{% else %}—{% endif %}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <span class="pg-caption">No recent failures.</span>
  {% endif %}
</details>
```

**Note:** verify the row-dict keys produced by `_build_failure_row` match `timestamp`, `engine`, `game_id`, `error_snippet`, `log_url`. If they differ, update the template (do **not** change the helper — it's shared with the old diagnostics view until we delete it in Task 5.5).

- [ ] **Step 4: Run + commit**

```bash
cd services/app && pytest analysis/tests/ -v
git add services/app/analysis/views_dashboard.py \
        services/app/templates/analysis/_dash_failures.html \
        services/app/analysis/tests/test_dashboard_view.py
git commit -m "feat(dashboard): failures partial (#106)"
```

---

### Task 5.2: Frontend visual polish (delegate to subagent)

**Files:**
- Modify: all six `_dash_*.html` partials + `dashboard.html` shell
- Modify: any global stylesheet that defines the Du Bois palette tokens

- [ ] **Step 1: Read the existing palette + utility classes**

```bash
# Find the canonical Tailwind/CSS file with .pg-section, .pg-head, .pg-title,
# .pg-caption, .pg-table, plus the parchment/peat/ebony color variables.
```

Use `vexp run_pipeline({ "task": "find Tailwind palette and .pg-* utility classes" })` instead of grep.

- [ ] **Step 2: Dispatch the frontend subagent**

Spawn an `Agent` with the frontend-design skill. Provide it with the following self-contained prompt:

```
You are styling the new Worker Dashboard at /admin/dashboard/.

GOAL: Bring six HTMX-polled partials and one shell up to the visual standard of
the existing queue.html and the W.E.B. Du Bois-inspired design system
(parchment/ebony palette, EB Garamond body, Playfair Display SC headings,
DM Mono labels). The dashboard must look at-a-glance scannable.

CONSTRAINTS:
- Use the existing utility classes (.pg-section, .pg-head, .pg-title,
  .pg-caption, .pg-table). Do not introduce a new naming convention.
- Status colors must come from existing palette tokens. Map liveness as:
  healthy=color-success (or peat green if no success token), warning=ochre,
  stale=oxblood.
- Each worker card should be a tight 3-line layout under a heading row.
- Banner is one horizontal line with a 8px dot at left.
- Tables must match the striping used in _queue_recent.html.
- All custom CSS goes in the same stylesheet as the existing .pg-* classes
  (find it via `vexp run_pipeline`, NOT grep).
- Add new classes only when an existing one truly doesn't fit. Each new
  class must be prefixed `dash-`.

DELIVERABLES:
- Updated six _dash_*.html partials (mostly class changes; keep template logic).
- Updated dashboard.html shell if needed.
- One CSS file update with any new .dash-* rules.

TOOLS:
- Use vexp run_pipeline / get_skeleton to locate the existing palette and the
  queue.html stylesheet hooks. Do NOT use grep/glob/find.
- Use context7 for any Tailwind/HTMX doc lookups.
- Invoke the frontend-design skill before writing HTML.

DO NOT touch the Python view functions. The templates must keep using the
existing context variables (cards, rows, banner_state, etc.).
```

- [ ] **Step 3: Review the subagent's diff**

After the agent returns, manually inspect:
1. No view function was modified.
2. No new dependency added.
3. Tests still pass.
4. The page renders end-to-end (open the local dev server).

- [ ] **Step 4: Run the dev server and verify in browser**

```bash
source .venv/bin/activate
cd services/app && python manage.py runserver
# Visit http://localhost:8000/admin/dashboard/ as an admin user.
# Confirm: banner renders, worker cards render, queue table renders,
# throughput table renders, recently completed table renders, failures
# section is collapsed, all sections refresh on their own intervals.
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "style(dashboard): apply Du Bois palette + .dash-* utilities (#106)"
```

---

### Task 5.3: Delete `diagnostics_view` + template + test

**Files:**
- Modify: `services/app/analysis/views.py`
- Delete: `services/app/templates/analysis/diagnostics.html`
- Delete: `services/app/analysis/tests/test_diagnostics_view.py`

- [ ] **Step 1: Delete the legacy view function**

In `views.py`, locate `def diagnostics_view(request: HttpRequest) -> HttpResponse:` (around line 368). Delete the function and its docstring. Also delete the helper `_recent_failures` if it is no longer referenced anywhere — but first run:

```bash
source .venv/bin/activate
cd services/app && python -c "from analysis import views; print([n for n in dir(views) if 'failure' in n.lower() or 'diagnostic' in n.lower()])"
```

Anything in that list that is no longer called by `urls.py` or any other view is dead code — remove it.

- [ ] **Step 2: Delete the template and test files**

```bash
rm services/app/templates/analysis/diagnostics.html
rm services/app/analysis/tests/test_diagnostics_view.py
```

- [ ] **Step 3: Verify URL `name="diagnostics"` still resolves**

This was already preserved as a redirect in Task 1.4. Re-run the redirect test:

```bash
cd services/app && pytest analysis/tests/test_dashboard_view.py::test_diagnostics_redirects_to_dashboard -v
```

Expected: pass.

- [ ] **Step 4: Migrate template callers from `analysis:diagnostics` → `analysis:dashboard`**

```bash
grep -rn "analysis:diagnostics" services/app/templates/ services/app/ 2>/dev/null | grep -v __pycache__ | grep -v migrations
```

For each hit, change to `analysis:dashboard`. After:

```bash
grep -r "analysis:diagnostics" services/app/templates/ services/app/ 2>/dev/null
# Expected: zero hits
grep -rn "diagnostics_view\|diagnostics.html" services/app/ 2>/dev/null | grep -v __pycache__ | grep -v docs
# Expected: zero hits
```

- [ ] **Step 5: Run full test suite**

```bash
cd services/app && pytest -x -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(analysis): remove legacy diagnostics_view + template + test (#106)"
```

---

### Task 5.4: Remove `runpod_health()` and stale queue-summary fields

**Files:**
- Modify: `services/app/analysis/services_queries.py`
- Modify: `services/app/analysis/services/__init__.py`
- Modify: `services/app/analysis/views.py` (`queues_summary` function)
- Modify: `services/app/analysis/apps.py`
- Modify: `services/app/templates/analysis/queue_summary.html` (or wherever `runpod` / `runpod_error` fields are rendered)
- Modify: any test that references `services.runpod_health`

- [ ] **Step 1: Delete `runpod_health` from `services_queries.py`**

Remove the `runpod_health` function entirely (currently at lines 63–101). Also remove its imports of `os` and `runpod` if those are no longer used elsewhere in the file.

- [ ] **Step 2: Drop the re-export**

In `services/__init__.py`, remove `runpod_health` from the import list and from `__all__`.

- [ ] **Step 3: Remove the call site from `queues_summary`**

In `views.py::queues_summary`, the row builder currently does:

```python
health, error = services.runpod_health(eng)
row: dict = {"name": eng, "runpod": health, "runpod_error": error}
```

Replace with:

```python
row: dict = {"name": eng}
```

The "Endpoint ID not configured for {engine}" text will no longer render because the `runpod_error` field no longer exists.

- [ ] **Step 4: Clean up `apps.py` docstrings**

Remove references to `services_queries.runpod_health` from the module docstring/class docstring on `services/app/analysis/apps.py`.

- [ ] **Step 5: Clean the queue_summary template**

```bash
# Find any template that references {{ row.runpod }} or {{ row.runpod_error }}.
# (Use vexp run_pipeline in a subagent if dispatched; otherwise the call site
#  is `services/app/templates/analysis/queue_summary.html` per the original PR
#  that added it.)
```

Delete any `{% if row.runpod_error %}` / `{{ row.runpod.* }}` blocks.

- [ ] **Step 6: Update any tests that reference `services.runpod_health`**

```bash
grep -rn "runpod_health" services/app/ 2>/dev/null | grep -v __pycache__
```

For each test file hit, either delete the test (if its sole purpose was the dead probe) or remove the call. Document each removal in the commit message.

- [ ] **Step 7: Run full test suite**

```bash
cd services/app && pytest -x -q
```

Expected: green.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "chore(analysis): remove dead serverless runpod_health probe (#106)"
```

---

### Task 5.5: Remove "submitted to RunPod" caption

**Files:**
- Modify: `services/app/templates/analysis/queue.html`

- [ ] **Step 1: Edit the caption**

At line 50 of `queue.html`, change:

```html
<span class="pg-caption">Running &amp; submitted to RunPod</span>
```

to:

```html
<span class="pg-caption">Currently running</span>
```

- [ ] **Step 2: Spot-check other queue partials for similar legacy phrases**

```bash
# Look for any remaining mentions of "submitted to RunPod" or "submitted-to-runpod"
# in the templates directory. Same phrase is sometimes in _queue_active.html.
```

Use `vexp run_pipeline({ "task": "find legacy 'submitted to RunPod' text in templates" })`.

- [ ] **Step 3: Run the queue page tests**

```bash
cd services/app && pytest analysis/tests/test_queue_view.py -v
```

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add services/app/templates/analysis/queue.html
git commit -m "chore(queue): drop 'submitted to RunPod' legacy caption (#106)"
```

---

### Task 5.6: Final quality gate

- [ ] **Step 1: Run repo-wide quality gate**

```bash
source .venv/bin/activate
ruff check services/app/analysis/ services/app/templates/analysis/
bandit -ll -r services/app/analysis/
mypy services/app/analysis/
cd services/app && pytest -q --cov=analysis --cov-report=term-missing
```

Coverage on `analysis/dashboard_helpers.py` should be ≥ 90%. Add tests if anything is uncovered.

- [ ] **Step 2: Run Snyk on edited Python files**

Per `~/.claude/CLAUDE.md` security rule, run `snyk_code_scan` on the new/modified Python files:

- `services/app/analysis/views_dashboard.py`
- `services/app/analysis/dashboard_helpers.py`
- `services/app/analysis/views.py`
- `services/app/analysis/services_queries.py`
- `services/app/analysis/services/__init__.py`
- `services/app/analysis/apps.py`
- `services/app/analysis/urls.py`

Fix any Medium/High findings before opening the PR.

- [ ] **Step 3: Manual browser pass against a local DB with synthetic data**

```bash
cd services/app && python manage.py shell <<'PY'
from analysis.models import WorkerHeartbeat, AnalysisJob
from games.models import Game
from django.utils import timezone
import uuid

# Create a fake fresh worker, a fake stale worker, and a handful of jobs in
# each state so all six partials render meaningful data.
PY
```

Visit `/admin/dashboard/` and confirm each section.

- [ ] **Step 4: Open the PR**

```bash
git push -u origin issue/106-worker-dashboard
gh pr create --title "Worker dashboard (#106)" --body "$(cat <<'EOF'
## Summary
- New `/admin/dashboard/` with six HTMX-polled partials: banner, workers, queues, throughput, recently completed, failures
- Shared helpers moved to `analysis/dashboard_helpers.py`
- Legacy `/admin/diagnostics/` view deleted; URL preserved as a redirect
- Dead serverless `runpod_health()` probe removed; "Endpoint ID not configured" message gone
- Legacy "submitted to RunPod" caption replaced

## Test plan
- [ ] `/admin/dashboard/` loads as admin; all six sections render
- [ ] Banner reports correct healthy/total workers
- [ ] Worker cards show liveness dot, current game link, ✓/✗ counters, hardware
- [ ] Queues row computes 10-min rate and ETA correctly
- [ ] Throughput shows 1h/6h/24h windows
- [ ] Recently completed groups jobs by game and links to game analysis page
- [ ] Failures section is collapsed by default
- [ ] `/admin/diagnostics/` 302s to `/admin/dashboard/`
- [ ] `/admin/queues/` no longer shows "Endpoint ID not configured"
- [ ] Pod runs end-to-end: dashboard reflects live state without SSH

Closes #106.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Companion Issue (file separately, do NOT include in this PR)

Spec Section 9.5 mentions a follow-up worker-side improvement that is **out of scope here** but worth filing now so it isn't lost:

- **Stale-active reaper:** management command `reap_stale_jobs` that flips
  any `status=running` job whose `worker_heartbeat.last_seen` is >5min stale
  back to `status=pending`. Optionally called on dashboard load so zombies
  clear themselves when an operator looks at the page.
- **Register `WorkerHeartbeat` in `analysis/admin.py`** for raw-table
  inspection. Currently `/admin/analysis/workerheartbeat/` 404s.

Open this as a separate `gh issue` after the dashboard PR is up.
