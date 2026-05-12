# Analysis Queue UI/UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Code search:** Use `mcp__vexp__run_pipeline` / `mcp__vexp__get_skeleton` rather than grep/glob (project rule — see `.claude/CLAUDE.md`).
> **Library docs:** When unsure about Django/HTMX/Tailwind APIs, query `mcp__plugin_context7_context7__query-docs` before writing code.
> **Frontend visual design:** Use the `frontend-design` agent for the visual rework tasks. Follow `wood_league.wiki/Design-Inspiration.md` — Du Bois-inspired palette/fonts, source of truth `services/app/static/css/main.css`. Use existing classes like `.wc-btn`, `.wc-table`, `.pg-section`, `.pg-head`, `.pg-title`, `.pg-caption`, `.page-hero` rather than inventing new ones.
> **Security gate:** After editing each `.py` file, run `bandit -ll <file>` and fix any Medium/High findings before committing (see `services/app/CLAUDE.md`).

**Goal:** Rework the analysis-queue admin pages so admins can manage hundreds of pending jobs effectively via priority tiers, freshness-first ordering, bulk reorder, and a sticky toolbar + paginated table layout under `/admin/queues/`.

**Architecture:** Backend: introduce three `priority` tiers (HIGH/NORMAL/LOW), change both worker claim and admin display ordering to `priority DESC, games.played_at DESC`, add a reorder POST endpoint, rename URL family to plural. Frontend: replace stacked three-section page with a tabbed page (Pending/Active/Recent), sticky top toolbar containing the bulk-action form, server-paginated tbody via HTMX `hx-get`. Summary page at `/admin/queues/` reuses existing `services.queue_by_engine()`.

**Tech Stack:** Django 5 + HTMX + Tailwind (project CSS in `services/app/static/css/main.css`), pytest-django.

**Spec:** `docs/superpowers/specs/2026-05-11-analysis-queue-ui-overhaul-design.md`

---

## File map

**Modify:**
- `services/app/analysis/models.py` — add three priority constants on `AnalysisJob`.
- `services/app/analysis/services/jobs.py` — change worker claim ordering at lines 116 and 125.
- `services/app/games/views.py` — `queue_analysis` sets `priority=AnalysisJob.PRIORITY_HIGH` (line ~643).
- `services/app/analysis/urls.py` — rename URL paths to plural `queues/` family; drop `analysis-status/`.
- `services/app/analysis/views.py` — rename `status` view to `queues_summary`, point to new template.
- `services/app/analysis/views_queue.py` — update `_queue_context` ordering and add pagination; add `queue_reorder` view.
- `services/app/templates/base.html` — update two `{% url 'analysis:status' %}` references → `{% url 'analysis:queues_summary' %}`.
- `services/app/templates/analysis/_overview_cards.html` — used by HTMX partial; engine link URLs unchanged (names preserved).
- `services/app/templates/analysis/queue.html` — restructure with sticky toolbar + tabs.
- `services/app/templates/analysis/_queue_pending.html` — rewrite as paginated form using `.wc-btn`.
- `services/app/templates/analysis/_queue_submit_result.html` — wrap returned partial to match new swap target.

**Create:**
- `services/app/templates/analysis/queues_summary.html` — new summary page template.
- `services/app/templates/analysis/_queue_pending_table.html` — paginated pending tbody partial (HTMX swap target).
- `services/app/analysis/tests/test_priority_tiers.py` — unit tests for priority constants + ordering.
- `services/app/analysis/tests/test_views_queue_reorder.py` — view tests for reorder endpoint.
- `services/app/analysis/tests/test_views_queues_summary.py` — view tests for summary page.

**Delete (after rename):**
- old `analysis-status/` route (replaced).

---

## Task 1: Priority tier constants

**Files:**
- Modify: `services/app/analysis/models.py:179-241` (class `AnalysisJob`)
- Test: `services/app/analysis/tests/test_priority_tiers.py` (create)

- [ ] **Step 1: Write failing test**

Create `services/app/analysis/tests/test_priority_tiers.py`:

```python
"""
Title: test_priority_tiers.py — Tests for AnalysisJob priority tier constants and ordering
Description: Verifies HIGH/NORMAL/LOW priority constants and that pending jobs
    sort by priority desc then game.played_at desc for both admin display and
    worker claim.
Changelog:
    2026-05-11: Initial — Task 1 of analysis-queue-ui-overhaul plan.
"""
import pytest
from analysis.models import AnalysisJob


def test_priority_tier_constants_exist():
    """Three named priority tiers expose integer values, HIGH > NORMAL > LOW."""
    assert AnalysisJob.PRIORITY_HIGH > AnalysisJob.PRIORITY_NORMAL > AnalysisJob.PRIORITY_LOW
    assert AnalysisJob.PRIORITY_HIGH == 100
    assert AnalysisJob.PRIORITY_NORMAL == 0
    assert AnalysisJob.PRIORITY_LOW == -100
```

- [ ] **Step 2: Run test and confirm failure**

```bash
cd services/app && pytest analysis/tests/test_priority_tiers.py::test_priority_tier_constants_exist -v
```

Expected: FAIL with `AttributeError: type object 'AnalysisJob' has no attribute 'PRIORITY_HIGH'`.

- [ ] **Step 3: Add constants to model**

In `services/app/analysis/models.py`, inside `class AnalysisJob`, add immediately after the existing `STATUS_CHOICES` block:

```python
    PRIORITY_HIGH = 100
    PRIORITY_NORMAL = 0
    PRIORITY_LOW = -100
```

- [ ] **Step 4: Run test and confirm pass**

```bash
cd services/app && pytest analysis/tests/test_priority_tiers.py::test_priority_tier_constants_exist -v
```

Expected: PASS.

- [ ] **Step 5: Security scan**

```bash
bandit -ll services/app/analysis/models.py
```

Expected: no Medium/High findings.

- [ ] **Step 6: Commit**

```bash
git add services/app/analysis/models.py services/app/analysis/tests/test_priority_tiers.py
git commit -m "feat(analysis): add priority tier constants (HIGH/NORMAL/LOW)"
```

---

## Task 2: Worker claim ordering — priority DESC, played_at DESC

**Files:**
- Modify: `services/app/analysis/services/jobs.py:116`, `services/app/analysis/services/jobs.py:125`
- Test: `services/app/analysis/tests/test_priority_tiers.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `services/app/analysis/tests/test_priority_tiers.py`:

```python
from datetime import datetime, timedelta, timezone as dt_tz
from django.contrib.auth import get_user_model

from games.models import Game
from analysis.services.jobs import checkout_jobs


@pytest.fixture
def two_pending_jobs(db):
    """Two pending stockfish jobs at same priority; older played_at vs newer."""
    User = get_user_model()
    user = User.objects.create_user(username="claim-test", password="x", role="admin")
    older_game = Game.objects.create(
        white_username="a", black_username="b",
        played_at=datetime(2024, 1, 1, tzinfo=dt_tz.utc),
    )
    newer_game = Game.objects.create(
        white_username="c", black_username="d",
        played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
    )
    older_job = AnalysisJob.objects.create(
        game=older_game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, priority=AnalysisJob.PRIORITY_NORMAL,
    )
    newer_job = AnalysisJob.objects.create(
        game=newer_game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, priority=AnalysisJob.PRIORITY_NORMAL,
    )
    return older_job, newer_job


def test_worker_claim_prefers_recent_played_at(two_pending_jobs):
    """Same priority: worker should claim the job whose game was played most recently."""
    older_job, newer_job = two_pending_jobs
    claimed = checkout_jobs(
        engine="stockfish", worker_id="w1", key_prefix="abcd1234", batch_size=1,
    )
    assert len(claimed) == 1
    assert claimed[0].id == newer_job.id


def test_worker_claim_high_priority_beats_recent(two_pending_jobs):
    """HIGH priority on the older game still wins over NORMAL on the newer game."""
    older_job, newer_job = two_pending_jobs
    older_job.priority = AnalysisJob.PRIORITY_HIGH
    older_job.save(update_fields=["priority"])
    claimed = checkout_jobs(
        engine="stockfish", worker_id="w2", key_prefix="abcd1234", batch_size=1,
    )
    assert len(claimed) == 1
    assert claimed[0].id == older_job.id
```

- [ ] **Step 2: Run tests and confirm failures**

```bash
cd services/app && pytest analysis/tests/test_priority_tiers.py -v
```

Expected: both new tests FAIL — current ordering is `-priority, created_at`, which on same-priority returns the older-`created_at` job.

- [ ] **Step 3: Update worker claim ordering**

In `services/app/analysis/services/jobs.py`, change both occurrences:

- Line 116: `.order_by('-priority', 'created_at')[:1]` → `.order_by('-priority', '-game__played_at')[:1]`
- Line 125: `.order_by('-priority', 'created_at')` → `.order_by('-priority', '-game__played_at')`

- [ ] **Step 4: Run tests and confirm pass**

```bash
cd services/app && pytest analysis/tests/test_priority_tiers.py -v
```

Expected: PASS for both new tests.

- [ ] **Step 5: Run existing job-claim tests for regression**

```bash
cd services/app && pytest analysis/tests/ -v -k "claim or checkout or enqueue"
```

Expected: no regressions.

- [ ] **Step 6: Security scan + commit**

```bash
bandit -ll services/app/analysis/services/jobs.py
git add services/app/analysis/services/jobs.py services/app/analysis/tests/test_priority_tiers.py
git commit -m "feat(analysis): order pending jobs by priority then played_at desc"
```

---

## Task 3: Bump reanalysis priority to HIGH

**Files:**
- Modify: `services/app/games/views.py` (around line 643, inside `queue_analysis`)

- [ ] **Step 1: Locate the literal**

Open `services/app/games/views.py` and find the `AnalysisJob.objects.create(... priority=1, ...)` call in `queue_analysis` (~line 639-645).

- [ ] **Step 2: Replace literal**

Change `priority=1` to `priority=AnalysisJob.PRIORITY_HIGH`. Verify `AnalysisJob` is already imported at top of file; if not, add the import.

- [ ] **Step 3: Run games tests**

```bash
cd services/app && pytest games/tests/ -v -k "queue_analysis or reanaly"
```

Expected: PASS.

- [ ] **Step 4: Security scan + commit**

```bash
bandit -ll services/app/games/views.py
git add services/app/games/views.py
git commit -m "feat(games): user reanalysis enqueues at PRIORITY_HIGH"
```

---

## Task 4: Rename URL family to /admin/queues/

**Files:**
- Modify: `services/app/analysis/urls.py`
- Modify: `services/app/templates/base.html`
- Modify: any test that references old paths (search and update)

- [ ] **Step 1: Rewrite `analysis/urls.py`**

Replace the body of `services/app/analysis/urls.py` (from `urlpatterns = [...]` block) with:

```python
urlpatterns = [
    path("queues/", views.queues_summary, name="queues_summary"),
    path("queues/stockfish/", views_queue.queue_stockfish, name="queue_stockfish"),
    path("queues/lc0/", views_queue.queue_lc0, name="queue_lc0"),
    path("queues/<str:engine>/submit/", views_queue.queue_submit, name="queue_submit"),
    path("queues/<str:engine>/reorder/", views_queue.queue_reorder, name="queue_reorder"),
]
```

Update the changelog at top of file.

Note: `queues_summary` and `queue_reorder` views don't exist yet — Tasks 5 and 6 add them. Module-level import of these names happens at startup, so this task **must commit together with Tasks 5 and 6** to avoid breaking the app between commits. Alternatively, defer this rewrite until after those tasks. Recommended order: do Tasks 5 and 6 first, then return to this task. If executing strictly in plan order, hold this commit until 5+6 are complete.

- [ ] **Step 2: Update template references**

In `services/app/templates/base.html`, replace both occurrences of `{% url 'analysis:status' %}` with `{% url 'analysis:queues_summary' %}`. There are exactly two (lines 43 and 84 in current file).

- [ ] **Step 3: Update test references**

```bash
cd services/app && grep -rn "analysis-status\|/queue/stockfish\|/queue/lc0\|'analysis:status'" --include='*.py' analysis/ games/ accounts/
```

Replace each old path with the new `/queues/...` equivalent and `'analysis:status'` → `'analysis:queues_summary'`.

- [ ] **Step 4: Run full suite for URL regressions**

```bash
cd services/app && pytest analysis/tests/ games/tests/ -v
```

Expected: PASS (after Tasks 5/6 are in).

- [ ] **Step 5: Security scan + commit**

```bash
bandit -ll services/app/analysis/urls.py
git add services/app/analysis/urls.py services/app/templates/base.html services/app/analysis/tests services/app/games/tests
git commit -m "feat(analysis): rename URL family to /admin/queues/"
```

---

## Task 5: `queues_summary` view + template

**Files:**
- Modify: `services/app/analysis/views.py` (rename `status` to `queues_summary`, point at new template)
- Create: `services/app/templates/analysis/queues_summary.html`
- Create: `services/app/analysis/tests/test_views_queues_summary.py`

- [ ] **Step 1: Write failing view test**

Create `services/app/analysis/tests/test_views_queues_summary.py`:

```python
"""
Title: test_views_queues_summary.py — Tests for /admin/queues/ summary page
Description: Verifies the summary view renders engine cards with pending/active
    counts and that each card links to the per-engine queue detail page.
Changelog:
    2026-05-11: Initial — Task 5 of analysis-queue-ui-overhaul plan.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


@pytest.fixture
def admin_client(db, client):
    User = get_user_model()
    user = User.objects.create_user(username="admin", password="x", role="admin")
    client.force_login(user)
    return client


def test_summary_renders_engine_cards(admin_client):
    """Summary page renders 200, contains both engine names, links to detail pages."""
    resp = admin_client.get(reverse("analysis:queues_summary"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "stockfish" in body.lower()
    assert "lc0" in body.lower()
    assert reverse("analysis:queue_stockfish") in body
    assert reverse("analysis:queue_lc0") in body


def test_summary_requires_admin(db, client):
    """Non-admin users are denied."""
    User = get_user_model()
    User.objects.create_user(username="user", password="x", role="player")
    client.login(username="user", password="x")
    resp = client.get(reverse("analysis:queues_summary"))
    assert resp.status_code in (302, 403)
```

- [ ] **Step 2: Rename view**

In `services/app/analysis/views.py`, rename function `status` to `queues_summary`. Change its `render(..., "analysis/status.html", ...)` call to `render(..., "analysis/queues_summary.html", ...)`. Keep the `_admin_required` decorator and `_queue_context()` helper as-is.

- [ ] **Step 3: Create summary template**

Create `services/app/templates/analysis/queues_summary.html`. This task only stubs in a minimal compliant template so tests pass; the **visual rebuild is Task 9** (frontend-design agent). Stub:

```html
{% extends "base.html" %}
{% block title %}Analysis Queues — Wood League Chess{% endblock %}
{% block content %}
<div class="page-hero">
  <div>
    <h1>Analysis Queues</h1>
    <p class="page-hero-sub">Per-engine queue summary and dispatch health.</p>
  </div>
</div>

<div class="pg-section">
  {% for row in queue_by_engine %}
  <a href="{% if row.name == 'stockfish' %}{% url 'analysis:queue_stockfish' %}{% else %}{% url 'analysis:queue_lc0' %}{% endif %}"
     class="block">
    <div class="pg-head">
      <span class="pg-title">{{ row.name|title }}</span>
      <span class="pg-caption">
        Pending: {{ row.pending }} · Active: {{ row.active }}
      </span>
    </div>
  </a>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 4: Run new tests**

```bash
cd services/app && pytest analysis/tests/test_views_queues_summary.py -v
```

Expected: PASS.

- [ ] **Step 5: Security scan + commit**

```bash
bandit -ll services/app/analysis/views.py
git add services/app/analysis/views.py services/app/templates/analysis/queues_summary.html services/app/analysis/tests/test_views_queues_summary.py
git commit -m "feat(analysis): add queues_summary view and minimal template"
```

---

## Task 6: Reorder endpoint

**Files:**
- Modify: `services/app/analysis/views_queue.py`
- Create: `services/app/analysis/tests/test_views_queue_reorder.py`

- [ ] **Step 1: Write failing tests**

Create `services/app/analysis/tests/test_views_queue_reorder.py`:

```python
"""
Title: test_views_queue_reorder.py — Tests for POST /admin/queues/<engine>/reorder/
Description: Verifies the reorder endpoint sets priority to HIGH for action=top
    and LOW for action=bottom, ignores wrong-engine and non-pending jobs, rejects
    bad action with 400, and is admin-only.
Changelog:
    2026-05-11: Initial — Task 6 of analysis-queue-ui-overhaul plan.
"""
import pytest
from datetime import datetime, timezone as dt_tz
from django.contrib.auth import get_user_model
from django.urls import reverse

from games.models import Game
from analysis.models import AnalysisJob


@pytest.fixture
def admin_client(db, client):
    User = get_user_model()
    User.objects.create_user(username="admin", password="x", role="admin")
    client.login(username="admin", password="x")
    return client


@pytest.fixture
def pending_job(db):
    game = Game.objects.create(
        white_username="w", black_username="b",
        played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
    )
    return AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING,
        priority=AnalysisJob.PRIORITY_NORMAL,
    )


def test_reorder_top_sets_high(admin_client, pending_job):
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "top"})
    assert resp.status_code == 200
    pending_job.refresh_from_db()
    assert pending_job.priority == AnalysisJob.PRIORITY_HIGH


def test_reorder_bottom_sets_low(admin_client, pending_job):
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "bottom"})
    assert resp.status_code == 200
    pending_job.refresh_from_db()
    assert pending_job.priority == AnalysisJob.PRIORITY_LOW


def test_reorder_ignores_wrong_engine(admin_client, pending_job):
    url = reverse("analysis:queue_reorder", kwargs={"engine": "lc0"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "top"})
    assert resp.status_code == 200
    pending_job.refresh_from_db()
    assert pending_job.priority == AnalysisJob.PRIORITY_NORMAL


def test_reorder_ignores_non_pending(admin_client, db):
    game = Game.objects.create(
        white_username="w", black_username="b",
        played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
    )
    job = AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED,
        priority=AnalysisJob.PRIORITY_NORMAL,
    )
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = admin_client.post(url, {"job_ids": [job.id], "action": "top"})
    assert resp.status_code == 200
    job.refresh_from_db()
    assert job.priority == AnalysisJob.PRIORITY_NORMAL


def test_reorder_bad_action_returns_400(admin_client, pending_job):
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "sideways"})
    assert resp.status_code == 400


def test_reorder_bad_engine_returns_400(admin_client, pending_job):
    url = reverse("analysis:queue_reorder", kwargs={"engine": "nope"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "top"})
    assert resp.status_code == 400


def test_reorder_requires_admin(db, client, pending_job):
    User = get_user_model()
    User.objects.create_user(username="u", password="x", role="player")
    client.login(username="u", password="x")
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = client.post(url, {"job_ids": [pending_job.id], "action": "top"})
    assert resp.status_code in (302, 403)
```

- [ ] **Step 2: Implement `queue_reorder`**

In `services/app/analysis/views_queue.py`, append the new view (above the closing of the module). Add the import for `JsonResponse` if not present.

```python
@_admin_required
@require_POST
def queue_reorder(request: HttpRequest, engine: str) -> HttpResponse:
    """Bulk-update priority for selected pending jobs to HIGH or LOW.

    Sets `priority` to AnalysisJob.PRIORITY_HIGH for action='top' or
    AnalysisJob.PRIORITY_LOW for action='bottom'. Only affects pending jobs
    for the given engine; non-matching IDs are silently skipped.

    Args:
        request: POST request with `job_ids` list and `action` field.
        engine: 'stockfish' or 'lc0' from the URL.

    Returns:
        HttpResponse: refreshed pending-table partial for HTMX swap.
        HttpResponseBadRequest: on invalid engine or action.
    """
    if engine not in _ENGINES:
        return HttpResponseBadRequest("invalid engine")
    action = request.POST.get("action", "")
    if action == "top":
        new_priority = AnalysisJob.PRIORITY_HIGH
    elif action == "bottom":
        new_priority = AnalysisJob.PRIORITY_LOW
    else:
        return HttpResponseBadRequest("invalid action")

    raw_ids = request.POST.getlist("job_ids")
    job_ids: list[int] = []
    for raw in raw_ids:
        try:
            job_ids.append(int(raw))
        except ValueError:
            continue

    updated = AnalysisJob.objects.filter(
        id__in=job_ids,
        engine=engine,
        status=AnalysisJob.STATUS_PENDING,
    ).update(priority=new_priority)

    context = {
        "engine": engine,
        "moved": updated,
        "moved_to": action,
        **_queue_context(engine),
    }
    return render(request, "analysis/_queue_submit_result.html", context)
```

- [ ] **Step 3: Run new tests**

```bash
cd services/app && pytest analysis/tests/test_views_queue_reorder.py -v
```

Expected: PASS.

- [ ] **Step 4: Security scan + commit**

```bash
bandit -ll services/app/analysis/views_queue.py
git add services/app/analysis/views_queue.py services/app/analysis/tests/test_views_queue_reorder.py
git commit -m "feat(analysis): add queue_reorder endpoint for HIGH/LOW priority bumps"
```

---

## Task 7: Paginated context + ordering for per-engine page

**Files:**
- Modify: `services/app/analysis/views_queue.py` (`_queue_context`)
- Test: `services/app/analysis/tests/test_views_queue.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `services/app/analysis/tests/test_views_queue.py`:

```python
def test_pending_ordered_by_priority_then_played_at(admin_client, db):
    """Pending table orders by priority desc, then game.played_at desc."""
    from datetime import datetime, timezone as dt_tz
    from games.models import Game
    from analysis.models import AnalysisJob

    old_game = Game.objects.create(
        white_username="a", black_username="b",
        played_at=datetime(2024, 1, 1, tzinfo=dt_tz.utc),
    )
    new_game = Game.objects.create(
        white_username="c", black_username="d",
        played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
    )
    high_old = AnalysisJob.objects.create(
        game=old_game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING,
        priority=AnalysisJob.PRIORITY_HIGH,
    )
    normal_new = AnalysisJob.objects.create(
        game=new_game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING,
        priority=AnalysisJob.PRIORITY_NORMAL,
    )

    resp = admin_client.get(reverse("analysis:queue_stockfish"))
    body = resp.content.decode()
    assert body.index(str(high_old.id)) < body.index(str(normal_new.id))


def test_pending_pagination_per_page(admin_client, db):
    """?per_page=25 limits the pending table to 25 rows in the page object."""
    from datetime import datetime, timezone as dt_tz
    from games.models import Game
    from analysis.models import AnalysisJob

    for i in range(30):
        g = Game.objects.create(
            white_username=f"w{i}", black_username=f"b{i}",
            played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
        )
        AnalysisJob.objects.create(
            game=g, engine="stockfish",
            status=AnalysisJob.STATUS_PENDING,
            priority=AnalysisJob.PRIORITY_NORMAL,
        )
    resp = admin_client.get(reverse("analysis:queue_stockfish") + "?per_page=25")
    assert resp.status_code == 200
    assert resp.context["pending_page"].object_list.count() == 25 if hasattr(
        resp.context["pending_page"].object_list, "count"
    ) else len(list(resp.context["pending_page"].object_list)) == 25
```

(If the existing test file doesn't already have `admin_client` fixture, copy it from `test_views_queue_reorder.py`.)

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd services/app && pytest analysis/tests/test_views_queue.py -v -k "ordered or pagination"
```

Expected: FAIL.

- [ ] **Step 3: Update `_queue_context`**

In `services/app/analysis/views_queue.py`, replace the body of `_queue_context` and update view callers:

```python
from django.core.paginator import Paginator

_DEFAULT_PAGE_SIZE = 50
_ALLOWED_PAGE_SIZES = {25, 50, 100}


def _queue_context(engine: str, request: HttpRequest | None = None) -> dict:
    """Build context for one engine's queue detail page.

    Pending jobs are ordered priority desc, game.played_at desc, paginated
    via ?page= and ?per_page=. Active and recent are unchanged.

    Args:
        engine: 'stockfish' or 'lc0'.
        request: Optional request used to read pagination query params.

    Returns:
        dict: keys engine, pending_page (Page object), pending_count,
            per_page, active, recent.
    """
    pending_qs = (
        AnalysisJob.objects
        .filter(engine=engine, status=AnalysisJob.STATUS_PENDING)
        .select_related("game")
        .order_by("-priority", "-game__played_at")
    )

    per_page = _DEFAULT_PAGE_SIZE
    page_number = 1
    if request is not None:
        try:
            requested = int(request.GET.get("per_page", _DEFAULT_PAGE_SIZE))
            if requested in _ALLOWED_PAGE_SIZES:
                per_page = requested
        except ValueError:
            pass
        try:
            page_number = max(1, int(request.GET.get("page", 1)))
        except ValueError:
            page_number = 1

    paginator = Paginator(pending_qs, per_page)
    pending_page = paginator.get_page(page_number)

    active = list(
        AnalysisJob.objects
        .filter(engine=engine, status__in=[
            AnalysisJob.STATUS_RUNNING, AnalysisJob.STATUS_SUBMITTED,
        ])
        .select_related("game")
        .order_by("-started_at")
    )
    recent = list(
        AnalysisJob.objects
        .filter(engine=engine, status__in=[
            AnalysisJob.STATUS_COMPLETED, AnalysisJob.STATUS_FAILED,
        ])
        .select_related("game")
        .order_by("-completed_at")[:50]
    )
    return {
        "engine": engine,
        "pending_page": pending_page,
        "pending_count": paginator.count,
        "per_page": per_page,
        "active": active,
        "recent": recent,
    }
```

Update the two `_queue_context(engine)` calls in `queue_stockfish` and `queue_lc0` to pass `request`: `_queue_context("stockfish", request)`, `_queue_context("lc0", request)`. Update `queue_submit` and `queue_reorder` similarly: `_queue_context(engine, request)`.

- [ ] **Step 4: Update existing pending template to consume new context**

Edit `services/app/templates/analysis/_queue_pending.html`. Replace `{% for job in pending %}` with `{% for job in pending_page %}` and `{% if pending %}` with `{% if pending_page %}`. Replace the `btn-primary` class on the submit button with `wc-btn wc-btn-primary` (matches the existing project pattern — verify class names exist in `main.css`; if only `wc-btn` exists, use that).

- [ ] **Step 5: Run tests**

```bash
cd services/app && pytest analysis/tests/test_views_queue.py -v
```

Expected: PASS.

- [ ] **Step 6: Security scan + commit**

```bash
bandit -ll services/app/analysis/views_queue.py
git add services/app/analysis/views_queue.py services/app/templates/analysis/_queue_pending.html services/app/analysis/tests/test_views_queue.py
git commit -m "feat(analysis): paginate pending queue, order by priority + played_at"
```

---

## Task 8: Frontend rebuild of per-engine queue page (sticky toolbar + tabs + pagination)

**Use the `frontend-design` agent for this task.** Brief it with:

> Rebuild `services/app/templates/analysis/queue.html` and `services/app/templates/analysis/_queue_pending.html`. Follow Du Bois-inspired aesthetic from `wood_league.wiki/Design-Inspiration.md` — earthy palette (parchment, ebony, forest, crimson, gold), strong section rules, framed blocks, compact metadata. Source of truth for classes: `services/app/static/css/main.css`. Layout per design spec `docs/superpowers/specs/2026-05-11-analysis-queue-ui-overhaul-design.md` §4. Use vexp `get_skeleton` to inspect existing templates and CSS; use context7 for HTMX docs as needed.

**Files:**
- Modify: `services/app/templates/analysis/queue.html`
- Modify: `services/app/templates/analysis/_queue_pending.html`
- Create: `services/app/templates/analysis/_queue_pending_table.html` (the inner tbody+pagination — HTMX swap target)

- [ ] **Step 1: Brief the frontend-design agent**

Dispatch the `frontend-design` agent with the brief above plus this concrete requirement list:

  1. Sticky top toolbar with: `[☐ select page] {N selected} [Submit to RunPod] [↑ Top] [↓ Bottom]` and a tab strip `Pending (N) | Active (N) | Recent (N)` underneath.
  2. The form wraps the table; all three action buttons submit the same form to different endpoints. Use `hx-post` with `hx-include="closest form"` (or per-button `formaction`). Target the wrapper div via `hx-target="#queue-table-wrap"` `hx-swap="innerHTML"`.
  3. Tabs swap the table region via `hx-get` (server-side: query param `?tab=pending|active|recent`); only one table is rendered at a time. Pagination + checkboxes only on the pending tab.
  4. Pagination row at the bottom of the table: prev/page-numbers/next; page-size dropdown (25/50/100). Each link is an `hx-get` swapping `#queue-table-wrap`.
  5. Priority badge column on pending rows: HIGH (gold/crimson), NORMAL (slate), LOW (muted). Use existing palette tokens.
  6. Per-row inline `↑` / `↓` icon buttons in the rightmost column that POST a single `job_ids` to the reorder endpoint.
  7. Submit button uses `.wc-btn` (or whatever the established primary-button class is in `main.css`). Confirm before substituting — the bug we're fixing is that `.btn-primary` does not exist.
  8. Read-only tabs (Active, Recent) hide the toolbar buttons and the checkbox column.

  Agent should produce the three templates listed above and update `_queue_submit_result.html` so its outer wrapper matches the new swap target.

- [ ] **Step 2: Visual smoke**

Start dev server, visit `/admin/queues/stockfish/`, verify:
  - Sticky toolbar stays visible on scroll
  - Submit button looks like a button (not raw text)
  - Pagination links swap the table without full page reload
  - Tabs switch without page reload
  - Per-row ↑/↓ buttons update priority and refresh table

```bash
cd services/app && python manage.py runserver
```

- [ ] **Step 3: Run all view tests**

```bash
cd services/app && pytest analysis/tests/ -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add services/app/templates/analysis/
git commit -m "feat(analysis): rebuild per-engine queue page with sticky toolbar, tabs, pagination"
```

---

## Task 9: Frontend rebuild of summary page

**Use the `frontend-design` agent for this task.** Brief it with:

> Rebuild `services/app/templates/analysis/queues_summary.html` per spec §3. Two large clickable engine cards (Stockfish, Lc0) showing pending count (with HIGH-tier sub-count), active count, failed-24h count, RunPod health, and worker last-seen. Each whole card links into the per-engine detail page. Follow Du Bois-inspired aesthetic from `wood_league.wiki/Design-Inspiration.md`. Inspect `services/app/static/css/main.css` for available classes via `mcp__vexp__get_skeleton`.

- [ ] **Step 1: Confirm context contains needed data**

In `services/app/analysis/views.py::queues_summary`, ensure context exposes per-engine: `pending`, `pending_high`, `active`, `failed_24h`, `runpod_health`, `worker_last_seen`. Extend `_queue_context` in `views.py` if the existing structure misses any of these. Add a unit test in `test_views_queues_summary.py` for the HIGH-tier sub-count.

- [ ] **Step 2: Dispatch frontend-design agent**

With the brief above and the data shape from Step 1.

- [ ] **Step 3: Smoke + test**

```bash
cd services/app && pytest analysis/tests/test_views_queues_summary.py -v && python manage.py runserver
```

Visit `/admin/queues/` and confirm both cards render and link.

- [ ] **Step 4: Commit**

```bash
git add services/app/templates/analysis/queues_summary.html services/app/analysis/views.py services/app/analysis/tests/test_views_queues_summary.py
git commit -m "feat(analysis): rebuild /admin/queues/ summary page"
```

---

## Task 10: End-to-end smoke + Snyk sweep

- [ ] **Step 1: Run full suite**

```bash
cd services/app && pytest -v
```

Expected: all green.

- [ ] **Step 2: Project security scan**

```bash
./security-scan.sh
```

Fix any new findings.

- [ ] **Step 3: Manual smoke checklist**

  - `/admin/queues/` loads, both cards visible.
  - Each card links into its engine page.
  - Pending table is most-recent-first within priority.
  - Bulk select → Submit to RunPod produces an HTMX swap with submitted/skipped/failed counts.
  - Bulk select → ↑ Top moves selected rows to top (priority badge changes to HIGH).
  - Bulk select → ↓ Bottom drops to bottom (LOW badge).
  - Per-row ↑/↓ work.
  - Pagination switches pages without full reload.
  - Tab switches Pending/Active/Recent without full reload.
  - Submit button is visibly a button.

- [ ] **Step 4: Final commit + PR**

```bash
git push -u origin issue/30-analysis-queue-ui-overhaul
gh pr create --title "Analysis Queue UI/UX overhaul (#30)" --body "$(cat <<'EOF'
## Summary
- Priority tiers (HIGH/NORMAL/LOW); user reanalysis enqueues HIGH
- Worker claim + admin display order: priority desc, played_at desc
- New /admin/queues/ summary + plural URL family
- Sticky toolbar + tabs + paginated table on per-engine page
- Bulk reorder endpoint
- Fixes non-functional .btn-primary class on bulk submit button

Closes #30

## Test plan
- [x] Unit tests for priority constants and ordering
- [x] View tests for reorder endpoint (top/bottom/wrong-engine/non-pending/bad-action/admin-only)
- [x] View tests for paginated pending
- [x] View tests for summary page
- [ ] Manual smoke of bulk submit, reorder, pagination, tab swap

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review

Spec coverage:
- §1 data model & ordering → Tasks 1, 2, 3
- §2 routing → Task 4
- §3 summary page → Tasks 5, 9
- §4 per-engine page UI → Tasks 7, 8
- §5 reorder endpoint → Task 6
- §6 HTMX targeting fix → Task 8 (covered in the agent brief, point 2)
- §7 testing → embedded in each task; full sweep in Task 10
- §8 security → bandit gate at each step; Snyk in Task 10

Placeholder scan: clean — every step has concrete code or commands.

Type/name consistency: `PRIORITY_HIGH/NORMAL/LOW`, `queue_reorder`, `queues_summary`, `pending_page`, `_queue_pending_table.html` used identically across tasks.

Ordering note: Task 4 (URL rename) depends on Tasks 5 and 6 because the URLs reference views those tasks introduce. Plan order should be: 1 → 2 → 3 → 5 → 6 → 4 → 7 → 8 → 9 → 10. The text in Task 4 calls this out explicitly.
