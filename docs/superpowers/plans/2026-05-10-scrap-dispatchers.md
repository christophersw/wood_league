# Scrap Dispatchers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **MANDATORY tooling for every task:**
> - Use `mcp__vexp__run_pipeline` for code search/exploration. Do NOT use `Grep`, `Glob`, or `find` to explore the codebase. Pre-tool hooks block these when the vexp daemon is running.
> - Use `mcp__vexp__get_skeleton` (preferred) over `Read` for inspecting files; only use `Read` when you must see exact bytes to edit a specific line.
> - Use `mcp__plugin_context7_context7__query-docs` (context7) when you need authoritative documentation for any library/framework — Django, runpod, psycopg, htmx, pytest, chess.com APIs, etc. Do NOT guess library APIs from training data.
> - After editing any `.py` file, run `bandit -ll <file>` and fix Medium/High findings before committing (per `services/app/CLAUDE.md`).
> - Bump `services/local_worker/pyproject.toml` version only if you modify files under `services/local_worker/` (per project CLAUDE.md). This plan does not modify the local worker.

**Goal:** Delete the `services/dispatchers` Railway service. Move Chess.com ingest to a Django management command run by Railway cron. Replace auto-dispatch with admin-gated `/queue/<engine>/` pages where admins explicitly submit selected jobs to RunPod. Drop `AnalysisJob.dispatch_mode` entirely.

**Architecture:** Two Django services (one app code, one cron schedule), plus the unchanged `local_worker` PyPI package. Dedup and dispatch logic centralize in Django. First-mover wins between local workers and admin RunPod submissions via `SELECT FOR UPDATE SKIP LOCKED` on the `pending` row.

**Tech Stack:** Django 5.x, HTMX (existing pattern), PostgreSQL advisory locks (`pg_try_advisory_lock`), `runpod` SDK, pytest with Django test DB.

**Spec:** `docs/superpowers/specs/2026-05-10-scrap-dispatchers-design.md`

**Deploy order intent:** Phases A–D are additive (existing dispatcher keeps running). After Phase D ships, the dispatcher service is stopped manually. Phase F drops the column once nothing depends on it. Phase G deletes the dispatcher source.

---

## Phase A — Settings & service layer (additive)

### Task A1: `SiteSettings` singleton model

**Files:**
- Create: `services/app/core/__init__.py` (if `core` app does not exist; otherwise reuse)
- Create: `services/app/core/models.py`
- Create: `services/app/core/admin.py`
- Create: `services/app/core/apps.py`
- Modify: `services/app/config/settings.py` — add `'core'` to `INSTALLED_APPS`
- Test: `services/app/core/tests/test_models.py`

> First, run `mcp__vexp__run_pipeline({task: "find existing app for site-wide singleton settings or general configuration models in the Django app"})`. If a suitable app already exists, **put `SiteSettings` there instead of creating a new `core` app**. Update file paths in this task accordingly. Document the choice in the commit message.

- [ ] **Step 1: Write failing test for SiteSettings.get_solo idempotency**

```python
# services/app/core/tests/test_models.py
"""
Title: test_models.py — SiteSettings singleton tests
Description: Verify SiteSettings.get_solo() returns the same row across calls
    and exposes auto_enqueue_stockfish / auto_enqueue_lc0 booleans.
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
"""
import pytest
from core.models import SiteSettings


@pytest.mark.django_db
def test_get_solo_returns_singleton():
    a = SiteSettings.get_solo()
    b = SiteSettings.get_solo()
    assert a.pk == b.pk
    assert SiteSettings.objects.count() == 1


@pytest.mark.django_db
def test_default_toggles():
    s = SiteSettings.get_solo()
    assert s.auto_enqueue_stockfish is True
    assert s.auto_enqueue_lc0 is False
```

- [ ] **Step 2: Run test, verify it fails**

```bash
cd services/app && pytest core/tests/test_models.py -v
```
Expected: ImportError or ModuleNotFoundError.

- [ ] **Step 3: Implement model + admin + apps**

```python
# services/app/core/models.py
"""
Title: models.py — Site-wide singleton settings
Description: Holds toggles that apply to the whole installation, currently the
    auto-enqueue flags for new Chess.com games per analysis engine.
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
"""
from __future__ import annotations

from django.db import models


class SiteSettings(models.Model):
    """Singleton row of site-wide configuration. Always pk=1."""

    auto_enqueue_stockfish = models.BooleanField(
        default=True,
        help_text="Auto-enqueue Stockfish AnalysisJob for newly ingested games.",
    )
    auto_enqueue_lc0 = models.BooleanField(
        default=False,
        help_text="Auto-enqueue Lc0 AnalysisJob for newly ingested games.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "site_settings"
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"

    def __str__(self) -> str:
        """Return a stable label for the singleton row."""
        return "Site settings"

    @classmethod
    def get_solo(cls) -> "SiteSettings":
        """Return the singleton row, creating it on first access."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
```

```python
# services/app/core/apps.py
from django.apps import AppConfig


class CoreConfig(AppConfig):
    """App config for site-wide configuration models."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
```

```python
# services/app/core/admin.py
"""
Title: admin.py — Admin registration for SiteSettings singleton
Description: Registers the SiteSettings model so admins can flip auto-enqueue
    flags from the Django admin UI.
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
"""
from django.contrib import admin
from .models import SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """Admin for the singleton settings row; hides add when one already exists."""

    list_display = ("__str__", "auto_enqueue_stockfish", "auto_enqueue_lc0", "updated_at")

    def has_add_permission(self, request):
        """Allow add only if the singleton has not yet been created."""
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Disable delete entirely; singleton must always exist."""
        return False
```

Add `'core'` to `INSTALLED_APPS` in `services/app/config/settings.py`. Use vexp to find the file: `mcp__vexp__run_pipeline({task: "find Django INSTALLED_APPS settings"})`.

- [ ] **Step 4: Generate and run migration**

```bash
cd services/app && python manage.py makemigrations core && python manage.py migrate
```
Expected: `core/migrations/0001_initial.py` created; migration applies cleanly.

- [ ] **Step 5: Run tests**

```bash
cd services/app && pytest core/tests/test_models.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll services/app/core/models.py services/app/core/admin.py services/app/core/apps.py
git add services/app/core/ services/app/config/settings.py
git commit -m "feat(core): add SiteSettings singleton with auto-enqueue toggles"
```

---

### Task A2: `last_error` / `last_error_at` columns on `AnalysisJob`

**Files:**
- Modify: `services/app/analysis/models.py` (around line 215, near `error_message`)
- Test: `services/app/analysis/tests/test_models_last_error.py`

- [ ] **Step 1: Write failing test**

```python
# services/app/analysis/tests/test_models_last_error.py
"""
Title: test_models_last_error.py — AnalysisJob.last_error/last_error_at fields
Description: Verify the new last_error and last_error_at fields can be set,
    cleared, and round-trip through the ORM.
Changelog:
    2026-05-10: Initial — Task A2 of scrap-dispatchers plan.
"""
import pytest
from django.utils import timezone

from analysis.models import AnalysisJob
from games.models import Game


@pytest.mark.django_db
def test_last_error_fields_round_trip():
    game = Game.objects.create(game_id="test-game-A2", pgn="*")
    job = AnalysisJob.objects.create(game=game, engine="stockfish")
    assert job.last_error is None
    assert job.last_error_at is None

    job.last_error = "boom"
    job.last_error_at = timezone.now()
    job.save()

    fresh = AnalysisJob.objects.get(pk=job.pk)
    assert fresh.last_error == "boom"
    assert fresh.last_error_at is not None
```

> If `Game(...)` requires more fields, run `mcp__vexp__get_skeleton({files: ["services/app/games/models.py"], detail: "detailed"})` to see the required constructor.

- [ ] **Step 2: Run test, verify it fails**

```bash
cd services/app && pytest analysis/tests/test_models_last_error.py -v
```
Expected: AttributeError or migration-needed error.

- [ ] **Step 3: Add fields to `AnalysisJob`**

In `services/app/analysis/models.py`, after the existing `error_message = models.TextField(...)` line:

```python
    last_error = models.TextField(
        null=True, blank=True,
        help_text="Most recent RunPod submission error, if any. Job stays pending for retry.",
    )
    last_error_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 4: Generate and run migration**

```bash
cd services/app && python manage.py makemigrations analysis && python manage.py migrate
```

- [ ] **Step 5: Run test**

```bash
cd services/app && pytest analysis/tests/test_models_last_error.py -v
```
Expected: 1 passed.

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll services/app/analysis/models.py
git add services/app/analysis/
git commit -m "feat(analysis): add last_error/last_error_at to AnalysisJob"
```

---

### Task A3: `enqueue_analysis_job` service

**Files:**
- Create: `services/app/analysis/services/enqueue.py`
- Modify: `services/app/analysis/services/__init__.py` — re-export `enqueue_analysis_job`
- Test: `services/app/analysis/tests/test_enqueue.py`

> Use `mcp__vexp__run_pipeline({task: "current job dedup logic in dispatcher and how AnalysisJob.dispatch_mode and depth gating work"})` before writing this task to confirm the exact filter semantics. The spec mandates: skip if active job exists (status in pending/running/submitted) for engine+game; skip if completed at depth ≥ requested. **Do not include `dispatch_mode` in the filter** — it's being removed in Phase F.

- [ ] **Step 1: Write failing test (dedup matrix)**

```python
# services/app/analysis/tests/test_enqueue.py
"""
Title: test_enqueue.py — Dedup matrix for enqueue_analysis_job
Description: Six cases: no-existing creates; pending/running/submitted skip;
    completed at sufficient depth skips; completed at lower depth creates.
Changelog:
    2026-05-10: Initial — Task A3 of scrap-dispatchers plan.
"""
import pytest

from analysis.models import AnalysisJob
from analysis.services.enqueue import enqueue_analysis_job
from games.models import Game


@pytest.fixture
def game(db):
    return Game.objects.create(game_id="test-A3", pgn="*")


@pytest.mark.django_db
def test_no_existing_creates(game):
    job = enqueue_analysis_job(game=game, engine="stockfish", depth=20)
    assert job is not None
    assert job.status == AnalysisJob.STATUS_PENDING


@pytest.mark.django_db
@pytest.mark.parametrize("status", [
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_RUNNING,
    AnalysisJob.STATUS_SUBMITTED,
])
def test_active_existing_skips(game, status):
    AnalysisJob.objects.create(game=game, engine="stockfish", status=status, depth=20)
    assert enqueue_analysis_job(game=game, engine="stockfish", depth=20) is None


@pytest.mark.django_db
def test_completed_sufficient_depth_skips(game):
    AnalysisJob.objects.create(
        game=game, engine="stockfish", status=AnalysisJob.STATUS_COMPLETED, depth=25
    )
    assert enqueue_analysis_job(game=game, engine="stockfish", depth=20) is None


@pytest.mark.django_db
def test_completed_lower_depth_creates(game):
    AnalysisJob.objects.create(
        game=game, engine="stockfish", status=AnalysisJob.STATUS_COMPLETED, depth=15
    )
    job = enqueue_analysis_job(game=game, engine="stockfish", depth=20)
    assert job is not None
```

- [ ] **Step 2: Run test, verify it fails**

```bash
cd services/app && pytest analysis/tests/test_enqueue.py -v
```
Expected: ImportError on `enqueue_analysis_job`.

- [ ] **Step 3: Implement service**

```python
# services/app/analysis/services/enqueue.py
"""
Title: enqueue.py — Dedup-safe AnalysisJob creation
Description: Single source of truth for deciding whether a Game needs a new
    AnalysisJob. Replaces the dispatcher-side _enqueue_job_if_needed logic and
    centralizes dedup so issue #12 (dispatch_mode-blind dedup) cannot recur.
Changelog:
    2026-05-10: Initial — Task A3 of scrap-dispatchers plan.
"""
from __future__ import annotations

from django.db import transaction

from analysis.models import AnalysisJob
from games.models import Game

_ACTIVE_STATUSES = (
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_RUNNING,
    AnalysisJob.STATUS_SUBMITTED,
)


def enqueue_analysis_job(
    *,
    game: Game,
    engine: str,
    depth: int = 20,
    priority: int = 10,
) -> AnalysisJob | None:
    """Create a pending AnalysisJob for game+engine if dedup permits.

    Args:
        game: The Game instance to analyze.
        engine: Engine name, e.g. 'stockfish' or 'lc0'.
        depth: Stockfish depth or Lc0 node budget threshold for completed-skip.
        priority: Job priority; higher runs first.

    Returns:
        The new AnalysisJob, or None if an active or sufficiently-deep
        completed job already exists.
    """
    with transaction.atomic():
        active_exists = AnalysisJob.objects.filter(
            game=game, engine=engine, status__in=_ACTIVE_STATUSES
        ).exists()
        if active_exists:
            return None

        completed_sufficient = AnalysisJob.objects.filter(
            game=game,
            engine=engine,
            status=AnalysisJob.STATUS_COMPLETED,
            depth__gte=depth,
        ).exists()
        if completed_sufficient:
            return None

        return AnalysisJob.objects.create(
            game=game,
            engine=engine,
            depth=depth,
            priority=priority,
            status=AnalysisJob.STATUS_PENDING,
        )
```

Update `services/app/analysis/services/__init__.py` to re-export:

```python
from analysis.services.enqueue import enqueue_analysis_job
```

Add `"enqueue_analysis_job"` to its `__all__`.

- [ ] **Step 4: Run tests**

```bash
cd services/app && pytest analysis/tests/test_enqueue.py -v
```
Expected: all parametrized cases pass (6+ tests).

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/analysis/services/enqueue.py
git add services/app/analysis/services/
git commit -m "feat(analysis): enqueue_analysis_job service with full dedup matrix"
```

---

### Task A4: `submit_job_to_runpod` service

**Files:**
- Create: `services/app/analysis/services/runpod_dispatch.py`
- Modify: `services/app/analysis/services/__init__.py` — re-export
- Modify: `services/app/config/settings.py` — read `RUNPOD_API_KEY`, `RUNPOD_STOCKFISH_ENDPOINT_ID`, `RUNPOD_LC0_ENDPOINT_ID` from env
- Test: `services/app/analysis/tests/test_runpod_dispatch.py`

> Use context7 if needed: `mcp__plugin_context7_context7__query-docs({query: "runpod python SDK Endpoint.run payload return type"})`. Confirm that `endpoint.run()` returns an object with a `.job_id` attribute. The dispatcher source is at `services/dispatchers/dispatchers/main.py` lines 144-211 — extract the payload-building logic from there.

- [ ] **Step 1: Write failing test with mocked endpoint**

```python
# services/app/analysis/tests/test_runpod_dispatch.py
"""
Title: test_runpod_dispatch.py — submit_job_to_runpod payload + return-id tests
Description: Mocks runpod.Endpoint.run to verify payload shape per engine and
    that the returned RunPod job id is propagated.
Changelog:
    2026-05-10: Initial — Task A4 of scrap-dispatchers plan.
"""
from unittest.mock import MagicMock, patch

import pytest

from analysis.models import AnalysisJob
from analysis.services.runpod_dispatch import submit_job_to_runpod
from games.models import Game


@pytest.fixture
def stockfish_job(db):
    g = Game.objects.create(game_id="t-rd-sf", pgn="1. e4 *")
    return AnalysisJob.objects.create(
        game=g, engine="stockfish", depth=20, status=AnalysisJob.STATUS_PENDING
    )


@pytest.fixture
def lc0_job(db):
    g = Game.objects.create(game_id="t-rd-lc0", pgn="1. e4 *")
    return AnalysisJob.objects.create(
        game=g, engine="lc0", depth=25000, nodes=25000,
        status=AnalysisJob.STATUS_PENDING,
    )


@pytest.mark.django_db
def test_stockfish_payload_and_id(stockfish_job, settings):
    settings.RUNPOD_STOCKFISH_ENDPOINT_ID = "sf-ep-1"
    settings.ANALYSIS_THREADS = 8
    settings.ANALYSIS_HASH_MB = 2048

    fake_endpoint = MagicMock()
    fake_endpoint.run.return_value = MagicMock(job_id="rp-123")

    with patch("analysis.services.runpod_dispatch.runpod.Endpoint",
               return_value=fake_endpoint) as ep_cls:
        result = submit_job_to_runpod(stockfish_job)

    ep_cls.assert_called_once_with("sf-ep-1")
    payload = fake_endpoint.run.call_args[0][0]
    assert payload["job_id"] == stockfish_job.id
    assert payload["pgn"] == "1. e4 *"
    assert payload["depth"] == 20
    assert payload["threads"] == 8
    assert payload["hash_mb"] == 2048
    assert result == "rp-123"


@pytest.mark.django_db
def test_lc0_payload(lc0_job, settings):
    settings.RUNPOD_LC0_ENDPOINT_ID = "lc0-ep-1"
    settings.LC0_NODES = 25000
    settings.LC0_NETWORK = ""

    fake_endpoint = MagicMock()
    fake_endpoint.run.return_value = MagicMock(job_id="rp-lc0-1")

    with patch("analysis.services.runpod_dispatch.runpod.Endpoint",
               return_value=fake_endpoint):
        submit_job_to_runpod(lc0_job)

    payload = fake_endpoint.run.call_args[0][0]
    assert payload["nodes"] == 25000
    assert "weights_path" not in payload
```

- [ ] **Step 2: Run test, verify it fails**

```bash
cd services/app && pytest analysis/tests/test_runpod_dispatch.py -v
```

- [ ] **Step 3: Implement service**

```python
# services/app/analysis/services/runpod_dispatch.py
"""
Title: runpod_dispatch.py — Submit AnalysisJob to RunPod serverless endpoint
Description: Pure function that builds the engine-specific payload and calls
    runpod.Endpoint.run(). Returns the RunPod job id. Caller is responsible
    for the row lock and status transition.
Changelog:
    2026-05-10: Initial — Task A4 of scrap-dispatchers plan.
"""
from __future__ import annotations

import runpod
from django.conf import settings

from analysis.models import AnalysisJob


def _build_payload(job: AnalysisJob) -> dict:
    """Build the engine-specific payload for one AnalysisJob."""
    if job.engine == "stockfish":
        return {
            "job_id": job.id,
            "pgn": job.game.pgn,
            "depth": job.depth,
            "threads": int(getattr(settings, "ANALYSIS_THREADS", 8)),
            "hash_mb": int(getattr(settings, "ANALYSIS_HASH_MB", 2048)),
        }
    payload: dict = {
        "job_id": job.id,
        "pgn": job.game.pgn,
        "nodes": job.nodes if job.nodes else int(getattr(settings, "LC0_NODES", 25000)),
    }
    network = getattr(settings, "LC0_NETWORK", "") or ""
    if network:
        payload["weights_path"] = network
    return payload


def _endpoint_id(engine: str) -> str:
    """Return the configured RunPod endpoint id for an engine, or raise."""
    if engine == "stockfish":
        ep = getattr(settings, "RUNPOD_STOCKFISH_ENDPOINT_ID", "") or ""
    elif engine == "lc0":
        ep = getattr(settings, "RUNPOD_LC0_ENDPOINT_ID", "") or ""
    else:
        raise ValueError(f"Unknown engine: {engine}")
    if not ep:
        raise RuntimeError(f"RunPod endpoint id not configured for engine={engine}")
    return ep


def submit_job_to_runpod(job: AnalysisJob) -> str:
    """Submit one AnalysisJob to RunPod and return the RunPod job id.

    Side effects: calls runpod.Endpoint.run(). Does NOT mutate the AnalysisJob;
    the caller is responsible for taking a row lock and transitioning status.

    Raises:
        RuntimeError: if the engine's endpoint id is not configured.
        Any exception raised by the runpod SDK propagates to the caller.
    """
    if not job.game.pgn:
        raise RuntimeError(f"Job {job.id} has no PGN")
    payload = _build_payload(job)
    endpoint = runpod.Endpoint(_endpoint_id(job.engine))
    run_request = endpoint.run(payload)
    return run_request.job_id
```

Add the engine endpoint settings to `services/app/config/settings.py`:

```python
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_STOCKFISH_ENDPOINT_ID = os.environ.get("RUNPOD_STOCKFISH_ENDPOINT_ID", "") or os.environ.get("RUNPOD_ENDPOINT_ID", "")
RUNPOD_LC0_ENDPOINT_ID = os.environ.get("RUNPOD_LC0_ENDPOINT_ID", "")
ANALYSIS_THREADS = int(os.environ.get("ANALYSIS_THREADS", "8"))
ANALYSIS_HASH_MB = int(os.environ.get("ANALYSIS_HASH_MB", "2048"))
LC0_NODES = int(os.environ.get("LC0_NODES", "25000"))
LC0_NETWORK = os.environ.get("LC0_NETWORK", "")
```

In Django app startup (`services/app/config/urls.py` or settings.py), set `runpod.api_key`:

```python
import runpod
runpod.api_key = settings.RUNPOD_API_KEY
```

Place this once in settings.py near the bottom, after the env reads. Don't import runpod at module top of settings.py — wrap in `try/except ImportError` so test runs without runpod don't fail.

Re-export from `services/app/analysis/services/__init__.py`:

```python
from analysis.services.runpod_dispatch import submit_job_to_runpod
```

- [ ] **Step 4: Run tests**

```bash
cd services/app && pytest analysis/tests/test_runpod_dispatch.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/analysis/services/runpod_dispatch.py services/app/config/settings.py
git add services/app/analysis/ services/app/config/settings.py
git commit -m "feat(analysis): submit_job_to_runpod service extracted from dispatcher"
```

---

## Phase B — Queue UI (per-engine detail pages)

### Task B1: Queue list view (Stockfish/Lc0 shared) — Pending section

**Files:**
- Create: `services/app/analysis/views_queue.py`
- Create: `services/app/templates/analysis/queue.html`
- Create: `services/app/templates/analysis/_queue_pending.html`
- Modify: `services/app/analysis/urls.py`
- Test: `services/app/analysis/tests/test_views_queue.py`

> Run `mcp__vexp__run_pipeline({task: "existing admin-only HTMX list views and bulk action patterns in the Django app"})` first to follow the established admin/HTMX pattern. Reuse `_admin_login_required` from `analysis/views.py`.

- [ ] **Step 1: Write failing test (admin-only, renders pending jobs)**

```python
# services/app/analysis/tests/test_views_queue.py
"""
Title: test_views_queue.py — Queue detail page tests
Description: Verifies /queue/<engine>/ renders pending AnalysisJobs for the
    engine, requires admin auth, and excludes other engines' jobs.
Changelog:
    2026-05-10: Initial — Task B1 of scrap-dispatchers plan.
"""
import pytest
from django.urls import reverse

from accounts.models import User
from analysis.models import AnalysisJob
from games.models import Game


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(email="admin@test", password="x", role="admin")


@pytest.fixture
def normal_user(db):
    return User.objects.create_user(email="u@test", password="x", role="member")


@pytest.mark.django_db
def test_requires_admin(client, normal_user):
    client.force_login(normal_user)
    resp = client.get(reverse("analysis:queue_stockfish"))
    assert resp.status_code in (302, 403)


@pytest.mark.django_db
def test_lists_pending_for_engine_only(client, admin_user):
    g1 = Game.objects.create(game_id="qb1-sf", pgn="*")
    g2 = Game.objects.create(game_id="qb1-lc", pgn="*")
    AnalysisJob.objects.create(game=g1, engine="stockfish",
                                status=AnalysisJob.STATUS_PENDING, depth=20)
    AnalysisJob.objects.create(game=g2, engine="lc0",
                                status=AnalysisJob.STATUS_PENDING, depth=25000)
    client.force_login(admin_user)
    resp = client.get(reverse("analysis:queue_stockfish"))
    assert resp.status_code == 200
    assert b"qb1-sf" in resp.content
    assert b"qb1-lc" not in resp.content
```

- [ ] **Step 2: Run test, verify it fails (URL not found)**

```bash
cd services/app && pytest analysis/tests/test_views_queue.py -v
```

- [ ] **Step 3: Implement views + templates + urls**

```python
# services/app/analysis/views_queue.py
"""
Title: views_queue.py — Per-engine queue detail pages with bulk RunPod submit
Description: Admin-only views for /queue/stockfish/ and /queue/lc0/. Renders
    Pending (with bulk-submit checkbox UI), Active (running+submitted, read-only),
    and Recent (last 50 completed/failed) sections.
Changelog:
    2026-05-10: Initial — Task B1 of scrap-dispatchers plan.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import AnalysisJob

_ENGINES = {"stockfish", "lc0"}


def _admin_required(view):
    """Require login + admin role (mirror of analysis.views helper)."""
    return login_required(user_passes_test(lambda u: u.role == "admin")(view))


def _queue_context(engine: str) -> dict:
    """Build context for one engine's queue detail page."""
    pending = (
        AnalysisJob.objects
        .filter(engine=engine, status=AnalysisJob.STATUS_PENDING)
        .select_related("game")
        .order_by("-priority", "created_at")
    )
    active = (
        AnalysisJob.objects
        .filter(engine=engine, status__in=[
            AnalysisJob.STATUS_RUNNING, AnalysisJob.STATUS_SUBMITTED,
        ])
        .select_related("game")
        .order_by("-started_at")
    )
    recent = (
        AnalysisJob.objects
        .filter(engine=engine, status__in=[
            AnalysisJob.STATUS_COMPLETED, AnalysisJob.STATUS_FAILED,
        ])
        .select_related("game")
        .order_by("-completed_at")[:50]
    )
    return {
        "engine": engine,
        "pending": pending,
        "active": active,
        "recent": recent,
    }


@_admin_required
@require_GET
def queue_stockfish(request: HttpRequest) -> HttpResponse:
    """Render /queue/stockfish/ detail page."""
    return render(request, "analysis/queue.html", _queue_context("stockfish"))


@_admin_required
@require_GET
def queue_lc0(request: HttpRequest) -> HttpResponse:
    """Render /queue/lc0/ detail page."""
    return render(request, "analysis/queue.html", _queue_context("lc0"))
```

```html
{# services/app/templates/analysis/queue.html #}
{% extends "base.html" %}

{% block title %}{{ engine|title }} Queue — Wood League Chess{% endblock %}

{% block content %}
<div class="page-hero">
  <div>
    <h1>{{ engine|title }} Queue</h1>
    <p class="page-hero-sub">Per-engine analysis queue and dispatch controls.</p>
  </div>
</div>

<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Pending ({{ pending|length }})</span>
    <span class="pg-caption">Select rows and submit to RunPod, or wait for a local worker to claim.</span>
  </div>
  {% include "analysis/_queue_pending.html" %}
</div>

<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Active ({{ active|length }})</span>
    <span class="pg-caption">Running + submitted</span>
  </div>
  {% include "analysis/_queue_active.html" %}
</div>

<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Recent</span>
    <span class="pg-caption">Last 50 completed or failed</span>
  </div>
  {% include "analysis/_queue_recent.html" %}
</div>
{% endblock %}
```

```html
{# services/app/templates/analysis/_queue_pending.html #}
{% if pending %}
<form id="bulk-submit-form"
      hx-post="{% url 'analysis:queue_submit' engine=engine %}"
      hx-target="#bulk-submit-form"
      hx-swap="outerHTML">
  {% csrf_token %}
  <table class="wc-table">
    <thead>
      <tr>
        <th><input type="checkbox" id="select-all"></th>
        <th>Game</th><th>Depth/Nodes</th><th>Created</th><th>Last Error</th>
      </tr>
    </thead>
    <tbody>
      {% for job in pending %}
      <tr>
        <td><input type="checkbox" name="job_ids" value="{{ job.id }}"></td>
        <td class="font-mono text-xs">{{ job.game.game_id|truncatechars:24 }}</td>
        <td class="font-mono text-xs">{{ job.depth }}</td>
        <td class="font-mono text-xs">{{ job.created_at|date:"d M H:i" }}</td>
        <td class="font-mono text-xs text-crimson">
          {{ job.last_error|default:""|truncatechars:60 }}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  <button type="submit" class="btn-primary mt-2">Submit selected to RunPod</button>
</form>
<script>
document.getElementById('select-all').addEventListener('change', function () {
  document.querySelectorAll('input[name=job_ids]').forEach(cb => cb.checked = this.checked);
});
</script>
{% else %}
<p class="font-mono text-sm text-slate">No pending jobs.</p>
{% endif %}
```

Add minimal `_queue_active.html` and `_queue_recent.html` partials. Keep these tight; copy the column conventions from existing `templates/analysis/status.html`.

Update `services/app/analysis/urls.py`:

```python
from . import views, views_queue

urlpatterns = [
    path("analysis-status/", views.status, name="status"),
    path("queue/stockfish/", views_queue.queue_stockfish, name="queue_stockfish"),
    path("queue/lc0/", views_queue.queue_lc0, name="queue_lc0"),
    # queue_submit added in Task B2
]
```

- [ ] **Step 4: Run tests**

```bash
cd services/app && pytest analysis/tests/test_views_queue.py -v
```
Expected: 2 passed (auth + listing).

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/analysis/views_queue.py
git add services/app/analysis/ services/app/templates/analysis/queue.html services/app/templates/analysis/_queue_pending.html services/app/templates/analysis/_queue_active.html services/app/templates/analysis/_queue_recent.html
git commit -m "feat(analysis): /queue/<engine>/ pages with pending+active+recent"
```

---

### Task B2: Bulk RunPod submit endpoint

**Files:**
- Modify: `services/app/analysis/views_queue.py` — add `queue_submit` view
- Modify: `services/app/analysis/urls.py` — add route
- Test: `services/app/analysis/tests/test_views_queue_submit.py`

- [ ] **Step 1: Write failing tests**

```python
# services/app/analysis/tests/test_views_queue_submit.py
"""
Title: test_views_queue_submit.py — Bulk RunPod submit endpoint tests
Description: Verifies happy path, partial failure, race-condition skip, and
    that non-pending jobs in the same engine are not affected.
Changelog:
    2026-05-10: Initial — Task B2 of scrap-dispatchers plan.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse

from accounts.models import User
from analysis.models import AnalysisJob
from games.models import Game


@pytest.fixture
def admin_client(db, client):
    u = User.objects.create_user(email="a@t", password="x", role="admin")
    client.force_login(u)
    return client


def _make_pending(n: int, engine: str = "stockfish") -> list[int]:
    ids = []
    for i in range(n):
        g = Game.objects.create(game_id=f"qb2-{engine}-{i}", pgn=f"{i}. e4 *")
        j = AnalysisJob.objects.create(
            game=g, engine=engine, status=AnalysisJob.STATUS_PENDING, depth=20
        )
        ids.append(j.id)
    return ids


@pytest.mark.django_db
def test_happy_path_three_submitted(admin_client):
    ids = _make_pending(3)
    with patch("analysis.views_queue.submit_job_to_runpod",
               side_effect=lambda job: f"rp-{job.id}"):
        resp = admin_client.post(
            reverse("analysis:queue_submit", args=["stockfish"]),
            {"job_ids": [str(i) for i in ids]},
        )
    assert resp.status_code == 200
    for jid in ids:
        j = AnalysisJob.objects.get(pk=jid)
        assert j.status == AnalysisJob.STATUS_SUBMITTED
        assert j.runpod_job_id == f"rp-{jid}"


@pytest.mark.django_db
def test_partial_failure_records_last_error(admin_client):
    ids = _make_pending(2)

    def fake(job):
        if job.id == ids[1]:
            raise RuntimeError("rp down")
        return f"rp-{job.id}"

    with patch("analysis.views_queue.submit_job_to_runpod", side_effect=fake):
        admin_client.post(
            reverse("analysis:queue_submit", args=["stockfish"]),
            {"job_ids": [str(i) for i in ids]},
        )

    ok = AnalysisJob.objects.get(pk=ids[0])
    bad = AnalysisJob.objects.get(pk=ids[1])
    assert ok.status == AnalysisJob.STATUS_SUBMITTED
    assert bad.status == AnalysisJob.STATUS_PENDING
    assert "rp down" in (bad.last_error or "")
    assert bad.last_error_at is not None


@pytest.mark.django_db
def test_already_submitted_skipped(admin_client):
    ids = _make_pending(1)
    AnalysisJob.objects.filter(pk=ids[0]).update(status=AnalysisJob.STATUS_SUBMITTED)
    with patch("analysis.views_queue.submit_job_to_runpod") as mock_sub:
        admin_client.post(
            reverse("analysis:queue_submit", args=["stockfish"]),
            {"job_ids": [str(ids[0])]},
        )
    mock_sub.assert_not_called()


@pytest.mark.django_db
def test_wrong_engine_filter_protects(admin_client):
    """Submitting to /queue/stockfish/ must not touch lc0 jobs."""
    sf_ids = _make_pending(1, engine="stockfish")
    lc_ids = _make_pending(1, engine="lc0")
    with patch("analysis.views_queue.submit_job_to_runpod",
               side_effect=lambda job: f"rp-{job.id}") as mock_sub:
        admin_client.post(
            reverse("analysis:queue_submit", args=["stockfish"]),
            {"job_ids": [str(sf_ids[0]), str(lc_ids[0])]},
        )
    # Only the stockfish one is submitted
    assert mock_sub.call_count == 1
    assert AnalysisJob.objects.get(pk=lc_ids[0]).status == AnalysisJob.STATUS_PENDING
```

- [ ] **Step 2: Run, verify failure**

```bash
cd services/app && pytest analysis/tests/test_views_queue_submit.py -v
```

- [ ] **Step 3: Implement view**

In `services/app/analysis/views_queue.py`:

```python
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.http import require_POST

from .services.runpod_dispatch import submit_job_to_runpod


@_admin_required
@require_POST
def queue_submit(request: HttpRequest, engine: str) -> HttpResponse:
    """Submit each requested pending job for `engine` to RunPod.

    Per-job transaction with SELECT FOR UPDATE SKIP LOCKED. Successes go to
    `submitted` with `runpod_job_id`. Failures keep `pending` and record
    `last_error` / `last_error_at`. Jobs not found or already-claimed are
    counted as skipped.
    """
    if engine not in _ENGINES:
        return HttpResponseBadRequest("invalid engine")
    raw_ids = request.POST.getlist("job_ids")
    job_ids: list[int] = []
    for raw in raw_ids:
        try:
            job_ids.append(int(raw))
        except ValueError:
            continue

    submitted = skipped = failed = 0
    errors: list[dict] = []

    for jid in job_ids:
        try:
            with transaction.atomic():
                job = (
                    AnalysisJob.objects
                    .select_for_update(skip_locked=True)
                    .filter(id=jid, engine=engine, status=AnalysisJob.STATUS_PENDING)
                    .select_related("game")
                    .first()
                )
                if job is None:
                    skipped += 1
                    continue
                try:
                    runpod_id = submit_job_to_runpod(job)
                except Exception as exc:  # noqa: BLE001 — record any failure for retry
                    job.last_error = str(exc)[:1000]
                    job.last_error_at = timezone.now()
                    job.save(update_fields=["last_error", "last_error_at"])
                    failed += 1
                    errors.append({"id": jid, "error": str(exc)[:200]})
                    continue
                job.status = AnalysisJob.STATUS_SUBMITTED
                job.runpod_job_id = runpod_id
                job.submitted_at = timezone.now()
                job.last_error = None
                job.last_error_at = None
                job.save(update_fields=[
                    "status", "runpod_job_id", "submitted_at",
                    "last_error", "last_error_at",
                ])
                submitted += 1
        except Exception as exc:  # noqa: BLE001 — defensive outer guard
            failed += 1
            errors.append({"id": jid, "error": str(exc)[:200]})

    return render(request, "analysis/_queue_submit_result.html", {
        "engine": engine,
        "submitted": submitted,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        **_queue_context(engine),
    })
```

Create `services/app/templates/analysis/_queue_submit_result.html`:

```html
<div id="bulk-submit-form">
  <p class="font-mono text-sm">
    Submitted {{ submitted }} · Skipped {{ skipped }} · Failed {{ failed }}
  </p>
  {% if errors %}
  <ul class="font-mono text-xs text-crimson">
    {% for e in errors %}<li>job {{ e.id }}: {{ e.error }}</li>{% endfor %}
  </ul>
  {% endif %}
  {% include "analysis/_queue_pending.html" %}
</div>
```

Add the URL route in `services/app/analysis/urls.py`:

```python
path("queue/<str:engine>/submit/", views_queue.queue_submit, name="queue_submit"),
```

- [ ] **Step 4: Run tests**

```bash
cd services/app && pytest analysis/tests/test_views_queue_submit.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/analysis/views_queue.py
git add services/app/analysis/ services/app/templates/analysis/_queue_submit_result.html
git commit -m "feat(analysis): bulk RunPod submit endpoint with per-job tx and partial-failure handling"
```

---

## Phase C — `/analysis/` overview rework

### Task C1: Reshape status view to overview cards

**Files:**
- Modify: `services/app/analysis/views.py` — `status()` and `_queue_context()`
- Modify: `services/app/templates/analysis/status.html` — replace 100-row table with engine cards
- Modify: `services/app/templates/analysis/_queue_partial.html` (if exists) — keep partial reflecting the new card layout
- Test: `services/app/analysis/tests/test_status_overview.py`

> Use `mcp__vexp__get_skeleton({files: ["services/app/templates/analysis/status.html", "services/app/analysis/views.py"], detail: "detailed"})` to confirm current structure before editing.

- [ ] **Step 1: Write failing test**

```python
# services/app/analysis/tests/test_status_overview.py
"""
Title: test_status_overview.py — /analysis/ overview cards tests
Description: Verifies the overview page renders one card per engine with
    pending/running/submitted/completed-today counts and links to queue pages.
Changelog:
    2026-05-10: Initial — Task C1 of scrap-dispatchers plan.
"""
import pytest
from django.urls import reverse

from accounts.models import User
from analysis.models import AnalysisJob
from games.models import Game


@pytest.fixture
def admin_client(db, client):
    u = User.objects.create_user(email="oa@t", password="x", role="admin")
    client.force_login(u)
    return client


@pytest.mark.django_db
def test_cards_render_with_links(admin_client):
    g = Game.objects.create(game_id="oc1", pgn="*")
    AnalysisJob.objects.create(game=g, engine="stockfish",
                                status=AnalysisJob.STATUS_PENDING)
    resp = admin_client.get(reverse("analysis:status"))
    assert resp.status_code == 200
    assert b"Stockfish" in resp.content
    assert b"Lc0" in resp.content
    assert b"/admin/queue/stockfish/" in resp.content
    assert b"/admin/queue/lc0/" in resp.content
    # The 100-row recent-jobs table is gone
    assert b"Recent Jobs" not in resp.content
```

- [ ] **Step 2: Run, verify failure**

```bash
cd services/app && pytest analysis/tests/test_status_overview.py -v
```

- [ ] **Step 3: Update view**

In `services/app/analysis/views.py`, replace `_queue_context` and `status` so the rendered context is { engine_rows, workers, total_pending } and the template renders cards. Drop `recent_jobs` from the context.

```python
def _queue_context() -> dict:
    """Build context for the analysis overview: per-engine summary + workers."""
    by_engine = services.queue_by_engine()
    engines = ["stockfish", "lc0"]
    statuses = ["pending", "submitted", "running", "completed"]

    rows = []
    for eng in engines:
        health, error = services.runpod_health(eng)
        row = {"name": eng, "runpod": health, "runpod_error": error}
        for s in statuses:
            row[s] = _engine_metric(by_engine, eng, s)
        rows.append(row)

    return {
        "engine_rows": rows,
        "workers": services.worker_heartbeats(),
    }


@_admin_login_required
@require_GET
def status(request: HttpRequest) -> HttpResponse:
    """Render the analysis overview: engine cards + worker status."""
    return render(request, "analysis/status.html", _queue_context())
```

- [ ] **Step 4: Update template**

Rewrite `services/app/templates/analysis/status.html`:

```html
{% extends "base.html" %}
{% load static %}

{% block title %}Analysis — Wood League Chess{% endblock %}

{% block content %}
<div class="page-hero">
  <div>
    <h1>Analysis</h1>
    <p class="page-hero-sub">Queue overview · click a card for engine detail.</p>
  </div>
</div>

<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Engines</span>
    <span class="pg-caption">Auto-refreshes every 30s</span>
  </div>
  <div id="engine-cards"
       hx-get="{% url 'analysis_partials:queue' %}"
       hx-trigger="load, every 30s"
       hx-swap="innerHTML">
    {% include "analysis/_overview_cards.html" %}
  </div>
</div>

<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Workers</span>
  </div>
  {% include "analysis/_workers_panel.html" %}
</div>
{% endblock %}
```

Create `services/app/templates/analysis/_overview_cards.html`:

```html
<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
  {% for row in engine_rows %}
  <a href="{% url 'analysis:queue_'|add:row.name %}" class="block card hover:shadow">
    <div class="flex items-baseline justify-between">
      <h2 class="text-lg">{{ row.name|title }}</h2>
      <span class="font-mono text-xs {% if row.runpod %}text-moss{% else %}text-crimson{% endif %}">
        RunPod: {% if row.runpod %}healthy{% else %}{{ row.runpod_error|default:"unknown" }}{% endif %}
      </span>
    </div>
    <div class="grid grid-cols-4 gap-2 mt-2 font-mono text-sm">
      <div>pending<br><span class="text-2xl">{{ row.pending }}</span></div>
      <div>running<br><span class="text-2xl">{{ row.running }}</span></div>
      <div>submitted<br><span class="text-2xl">{{ row.submitted }}</span></div>
      <div>completed<br><span class="text-2xl">{{ row.completed }}</span></div>
    </div>
  </a>
  {% endfor %}
</div>
```

Pull existing worker rendering into `services/app/templates/analysis/_workers_panel.html` (lift from the prior `_queue_partial.html` if it had one; else write a minimal table over `workers`).

Update `services/app/analysis/partial_urls.py` if it served the old `_queue_partial.html`; it should now return the new `_overview_cards.html`.

- [ ] **Step 5: Run tests**

```bash
cd services/app && pytest analysis/tests/test_status_overview.py analysis/tests/ -v
```
Expected: new test passes; no regressions in other analysis tests.

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll services/app/analysis/views.py
git add services/app/analysis/ services/app/templates/analysis/
git commit -m "refactor(analysis): /analysis/ becomes overview cards; recent-jobs moves to /queue/<engine>/"
```

---

## Phase D — Ingest in Django (cron)

### Task D1: `sync_games` — advisory lock + auto-enqueue

**Files:**
- Modify: `services/app/ingest/management/commands/sync_games.py`
- Test: `services/app/ingest/tests/test_sync_games_command.py`

> The current `sync_games` shells out to `app.ingest.run_sync` (SQLAlchemy). **Do not** rewrite the SQLAlchemy ingest — that's a separate effort. This task only adds: (1) a Postgres advisory lock at the start, (2) post-subprocess auto-enqueue using `enqueue_analysis_job` and `SiteSettings`, (3) `SystemEvent` rows. Use `mcp__vexp__run_pipeline({task: "SystemEvent model and existing usage in app"})` to confirm the SystemEvent fields.

- [ ] **Step 1: Write failing tests**

```python
# services/app/ingest/tests/test_sync_games_command.py
"""
Title: test_sync_games_command.py — Auto-enqueue + advisory-lock tests
Description: Verifies the management command enqueues stockfish jobs for
    newly-inserted games when the SiteSettings flag is on, and that a held
    advisory lock causes the command to exit zero without running.
Changelog:
    2026-05-10: Initial — Task D1 of scrap-dispatchers plan.
"""
from unittest.mock import patch

import pytest
from django.core.management import call_command

from analysis.models import AnalysisJob
from core.models import SiteSettings
from games.models import Game


@pytest.mark.django_db
def test_auto_enqueue_creates_stockfish_jobs_when_flag_on():
    SiteSettings.get_solo()  # flag default True

    def fake_run_sync(*args, **kwargs):
        Game.objects.create(game_id="d1-new-1", pgn="1. e4 *")
        Game.objects.create(game_id="d1-new-2", pgn="1. d4 *")
        class R: returncode = 0
        return R()

    with patch("ingest.management.commands.sync_games.subprocess.run",
               side_effect=fake_run_sync):
        call_command("sync_games", "alice")

    sf_jobs = AnalysisJob.objects.filter(engine="stockfish")
    assert sf_jobs.count() == 2
    assert AnalysisJob.objects.filter(engine="lc0").count() == 0


@pytest.mark.django_db
def test_held_advisory_lock_exits_zero(capsys):
    """If pg_try_advisory_lock returns false, command exits without syncing."""
    with patch(
        "ingest.management.commands.sync_games._try_acquire_lock",
        return_value=False,
    ), patch(
        "ingest.management.commands.sync_games.subprocess.run"
    ) as mock_run:
        call_command("sync_games", "alice")
    mock_run.assert_not_called()
```

- [ ] **Step 2: Run, verify failures**

```bash
cd services/app && pytest ingest/tests/test_sync_games_command.py -v
```

- [ ] **Step 3: Update `sync_games.py`**

```python
# services/app/ingest/management/commands/sync_games.py
"""
Title: sync_games.py — Django management command for Chess.com game sync
Description:
    Acquires a Postgres advisory lock (cron-overlap protection), runs the
    existing Chess.com sync subprocess, then auto-enqueues AnalysisJobs for
    newly-ingested games per SiteSettings toggles. Writes SystemEvent rows
    for ingest start/complete/failed.
Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-10: Add advisory lock + auto-enqueue + SystemEvent (Task D1).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from analysis.services.enqueue import enqueue_analysis_job
from core.models import SiteSettings
from games.models import Game
from players.models import Player

# Module-level constant; chosen once, never changes (32-bit int).
_INGEST_LOCK_ID = 0x7E571465

_SCRIPT = Path(__file__).resolve().parents[3] / "app" / "ingest" / "run_sync.py"


def _try_acquire_lock(lock_id: int = _INGEST_LOCK_ID) -> bool:
    """Acquire a session-scoped Postgres advisory lock. Returns True on success."""
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
        return bool(cur.fetchone()[0])


def _release_lock(lock_id: int = _INGEST_LOCK_ID) -> None:
    """Release the session-scoped advisory lock."""
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", [lock_id])


def _depth_default(engine: str) -> int:
    """Return default depth/nodes for new auto-enqueued jobs."""
    from django.conf import settings
    if engine == "stockfish":
        return int(getattr(settings, "ANALYSIS_DEPTH", 20))
    return int(getattr(settings, "LC0_NODES", 25000))


class Command(BaseCommand):
    """Sync Chess.com games and auto-enqueue analysis per SiteSettings toggles."""

    help = "Sync games from Chess.com for all (or specified) club members."

    def add_arguments(self, parser):
        """Register command-line arguments."""
        parser.add_argument("usernames", nargs="*",
                            help="Chess.com usernames to sync.")
        parser.add_argument("--days", type=int, default=None,
                            help="Only sync archives from the last N days.")

    def handle(self, *args, **options):
        """Execute sync (advisory-locked), then auto-enqueue per settings."""
        if not _try_acquire_lock():
            self.stdout.write("sync_games: advisory lock held; another run in progress, exiting.")
            return

        started_at = timezone.now()
        try:
            self._do_sync(options, started_at)
        finally:
            _release_lock()

    def _do_sync(self, options: dict, started_at) -> None:
        """Inner body — keeps lock release in handle()."""
        usernames = options["usernames"] or list(
            Player.objects.values_list("username", flat=True)
        )
        if not usernames:
            self.stderr.write("No club members found.")
            return

        self.stdout.write(f"Syncing {len(usernames)} member(s): {', '.join(usernames)}")

        # SystemEvent: started (use raw model if SystemEvent exists; otherwise log)
        try:
            from analysis.models import SystemEvent  # type: ignore
            SystemEvent.objects.create(event_type="ingest", status="started")
        except Exception:
            SystemEvent = None  # type: ignore

        sync_start = time.time()
        cmd = [sys.executable, str(_SCRIPT)] + usernames
        if options["days"]:
            cmd += ["--days", str(options["days"])]
        result = subprocess.run(cmd, capture_output=False)  # noqa: S603

        if result.returncode != 0:
            if SystemEvent is not None:
                SystemEvent.objects.create(
                    event_type="ingest", status="failed",
                    error_message=f"run_sync exit {result.returncode}",
                    duration_seconds=time.time() - sync_start,
                )
            self.stderr.write(f"run_sync exited {result.returncode}")
            return

        # Auto-enqueue: any Game inserted at or after `started_at`
        settings_row = SiteSettings.get_solo()
        sf_count = lc_count = 0
        new_games = Game.objects.filter(created_at__gte=started_at)  # see note below
        for game in new_games:
            if settings_row.auto_enqueue_stockfish:
                if enqueue_analysis_job(
                    game=game, engine="stockfish", depth=_depth_default("stockfish")
                ):
                    sf_count += 1
            if settings_row.auto_enqueue_lc0:
                if enqueue_analysis_job(
                    game=game, engine="lc0", depth=_depth_default("lc0")
                ):
                    lc_count += 1

        self.stdout.write(
            f"Auto-enqueued: stockfish={sf_count} lc0={lc_count}"
        )
        if SystemEvent is not None:
            SystemEvent.objects.create(
                event_type="ingest", status="completed",
                duration_seconds=time.time() - sync_start,
            )
```

> **Note on `Game.created_at`:** Verify with `mcp__vexp__get_skeleton({files: ["services/app/games/models.py"], detail: "detailed"})` whether `Game` has a `created_at` field. If not, either (a) add one in this task with a migration and `auto_now_add=True`, or (b) iterate all Games whose `analysis_jobs` are empty for the engine. The dedup in `enqueue_analysis_job` makes (b) safe but slow for large libraries; prefer (a). Adjust this task's commit to include the migration if needed.

- [ ] **Step 4: Run tests**

```bash
cd services/app && pytest ingest/tests/test_sync_games_command.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/ingest/management/commands/sync_games.py
git add services/app/ingest/
git commit -m "feat(ingest): sync_games auto-enqueues + advisory-locks against cron overlap"
```

---

### Task D2: Railway cron schedule for `sync_games`

**Files:**
- Modify: `services/app/railway.toml`

> Use context7 if needed: `mcp__plugin_context7_context7__query-docs({query: "Railway cron schedule configuration railway.toml syntax"})`. Confirm exact key names.

- [ ] **Step 1: Inspect existing railway.toml**

```bash
cat services/app/railway.toml
```

- [ ] **Step 2: Add a cron schedule entry**

Append (or merge with existing service config):

```toml
[[deploy.cron]]
schedule = "*/15 * * * *"
command = "python manage.py sync_games"
```

> If Railway's TOML schema differs (e.g. requires a separate cron service definition), follow Railway docs verified via context7. Adjust accordingly.

- [ ] **Step 3: Commit**

```bash
git add services/app/railway.toml
git commit -m "chore(railway): cron sync_games every 15 minutes"
```

---

## Phase E — Manual deploy step (no code)

This phase has **no tasks for the worker**. After Phases A–D ship and are verified in production:

- Operator stops the `services/dispatchers` Railway service.
- Operator confirms the new cron is firing (Railway logs).
- Operator clicks Submit-to-RunPod on a small batch via `/queue/stockfish/` and verifies it reaches RunPod.

Only after this is verified should Phase F begin.

---

## Phase F — Drop `dispatch_mode`

### Task F1: Remove `dispatch_mode` from service layer + API

**Files:**
- Modify: `services/app/analysis/services/jobs.py` — remove `dispatch_mode` param from `claim_jobs`, remove from `submit_job`
- Modify: `services/app/api/views.py:65` — drop `dispatch_mode=` kwarg
- Modify: `services/app/api/serializers.py` — drop `DISPATCH_CHOICES` and field
- Modify: `services/app/api/tests/test_endpoints.py` — drop `dispatch_mode=` arguments
- Modify: `packages/shared/wood_league_shared/worker_client.py` (and any other place) — remove `dispatch_mode` from `WorkerClient.checkout` if it's still in the surface

> Run `mcp__vexp__run_pipeline({task: "all references to dispatch_mode and DISPATCH_PULL/DISPATCH_RUNPOD across the repo"})` first to enumerate every site. The grep-style list at plan-write time was: `services/app/analysis/models.py`, `services/app/analysis/services/jobs.py`, `services/app/api/views.py`, `services/app/api/serializers.py`, `services/app/api/tests/test_endpoints.py`. Verify the list is still accurate and that no new references appeared.

- [ ] **Step 1: Drop param from `claim_jobs` and remove the dispatch_mode filter**

In `services/app/analysis/services/jobs.py`:
- Remove `dispatch_mode: str = AnalysisJob.DISPATCH_PULL` from `claim_jobs` signature.
- Remove `if dispatch_mode == AnalysisJob.DISPATCH_PULL:` guard on `recover_stale_jobs(engine)` (always run it).
- Remove `dispatch_mode=dispatch_mode` from both `.filter(...)` queries.
- Remove the `dispatch_mode=AnalysisJob.DISPATCH_PULL` kwarg from `recover_stale_jobs`.
- In `submit_job`, drop `dispatch_mode=AnalysisJob.DISPATCH_RUNPOD` from the `.get(...)` filter.

- [ ] **Step 2: Drop from API**

In `services/app/api/views.py:65`, drop `dispatch_mode=d.get('dispatch_mode', 'pull'),` from the call.

In `services/app/api/serializers.py`, delete `DISPATCH_CHOICES` and the `dispatch_mode = serializers.ChoiceField(...)` field.

- [ ] **Step 3: Update tests**

In `services/app/api/tests/test_endpoints.py`, remove every `dispatch_mode=...` kwarg from `AnalysisJob.objects.create(...)` calls and every JSON body that passes `dispatch_mode`.

- [ ] **Step 4: Run full app test suite**

```bash
cd services/app && pytest -x
```
Expected: all tests pass. Fix any remaining references the search missed.

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/analysis/services/jobs.py services/app/api/views.py services/app/api/serializers.py
git add -u services/app/ packages/shared/
git commit -m "refactor: drop dispatch_mode from job services, API, and tests"
```

---

### Task F2: Migration to drop the column

**Files:**
- Create: `services/app/analysis/migrations/0NNN_drop_dispatch_mode.py` (auto-generated)
- Modify: `services/app/analysis/models.py` — delete `dispatch_mode` field, remove from `Meta.indexes`, remove `DISPATCH_PULL`/`DISPATCH_RUNPOD` constants and `__str__` reference

- [ ] **Step 1: Edit model**

In `services/app/analysis/models.py`:
- Delete the `DISPATCH_PULL`, `DISPATCH_RUNPOD` constants.
- Delete the `dispatch_mode = models.CharField(...)` field.
- Remove `"dispatch_mode"` from the `models.Index(fields=["status", "engine", "dispatch_mode"])` (replace index with `fields=["status", "engine"]`).
- Update `__str__` to drop the `/{self.dispatch_mode}` segment.

- [ ] **Step 2: Generate migration**

```bash
cd services/app && python manage.py makemigrations analysis
```

- [ ] **Step 3: Run migration locally**

```bash
cd services/app && python manage.py migrate
```

- [ ] **Step 4: Run full test suite**

```bash
cd services/app && pytest -x
```
Expected: all green.

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/analysis/models.py
git add services/app/analysis/
git commit -m "refactor(analysis): drop dispatch_mode column from AnalysisJob"
```

---

## Phase G — Cleanup

### Task G1: Delete `services/dispatchers/`

- [ ] **Step 1: Verify no in-repo references**

Use `mcp__vexp__run_pipeline({task: "any code, config, CI, or docs referencing services/dispatchers, wood_league_dispatchers, or wood-league-dispatchers package"})`. If anything points to it, fix or remove that reference first.

- [ ] **Step 2: Delete the directory**

```bash
git rm -r services/dispatchers/
```

- [ ] **Step 3: Drop dispatcher env vars from any `.env.example` files**

Use vexp to find `.env.example` files in the repo. Remove the dispatcher-only vars listed in the spec (`SF_POLL_INTERVAL`, `LC0_POLL_INTERVAL`, `INGEST_POLL_INTERVAL`, `QUEUE_STOCKFISH_AFTER_INGEST`, `QUEUE_LC0_AFTER_INGEST`).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete services/dispatchers (replaced by Django queue UI + cron)"
```

---

### Task G2: Audit `wood_league_shared`

**Files:**
- Modify: `packages/shared/wood_league_shared/` (whatever is no longer imported)

- [ ] **Step 1: Enumerate consumers**

`mcp__vexp__run_pipeline({task: "every import of wood_league_shared submodules across the repo"})`. Expected after dispatcher deletion: only `services/local_worker/` and possibly `services/app/app/` (the SQLAlchemy fork) still import from `wood_league_shared`. Document the result in the commit body.

- [ ] **Step 2: If any submodule has zero remaining imports, delete it**

For example, if no consumer imports `wood_league_shared.ingest.sync_service` anymore, delete that file. Do **not** delete `wood_league_shared.worker_client` or `wood_league_shared.storage.models` if `local_worker` still imports them.

- [ ] **Step 3: Commit**

```bash
git add packages/shared/
git commit -m "chore(shared): drop unused submodules after dispatcher removal"
```

---

## Self-Review Notes

**Spec coverage check** (mapping spec sections → tasks):

| Spec section | Tasks |
|---|---|
| `AnalysisJob` drop dispatch_mode + add last_error fields | A2, F1, F2 |
| `SiteSettings` model | A1 |
| `sync_games` advisory lock + auto-enqueue + SystemEvent | D1 |
| `runpod_dispatch.submit_job_to_runpod` | A4 |
| `enqueue_analysis_job` (dedup matrix) | A3 |
| `/analysis/` overview rework | C1 |
| `/queue/<engine>/` Pending/Active/Recent | B1 |
| Bulk submit endpoint with per-job tx | B2 |
| Railway cron | D2 |
| Migration ordering (additive → drop column) | A → F (E manual) |
| Tests: dedup matrix, race, partial failure, cron overlap | A3, B2, D1 |
| Delete `services/dispatchers/` | G1 |
| `wood_league_shared` audit | G2 |

**Open items the executor must verify in flight (called out inline):**
- A1: confirm whether a `core` app already exists; if so, place `SiteSettings` there.
- A4: confirm `runpod.Endpoint.run()` return shape via context7 before assuming `.job_id`.
- D1: verify `Game.created_at` exists; if not, add it with a migration in this task.
- D2: verify Railway TOML cron syntax via context7 before merging.
- F1: re-enumerate `dispatch_mode` references; the list at plan-write time may have grown.
- G2: confirm `wood_league_shared` import surface via vexp before deleting submodules.
