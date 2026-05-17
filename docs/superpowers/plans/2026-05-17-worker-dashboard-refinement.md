# Worker Dashboard Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the worker dashboard to drop wildly-stale workers, highlight genuinely-live workers, and show per-worker cards with per-engine timing, last-10 games, and a batch-progress bar (GitHub issue #128).

**Architecture:** Server derives per-engine timing (time/ply, time/game) and the last-10-games list from existing completed `AnalysisJob` rows — no worker change needed for those. Batch position (`N/M`) and session start come from new **structured heartbeat fields** added to `HeartbeatSerializer` + `WorkerHeartbeat` (worker reports `batch_total`, `batch_processed`, `session_started_at`). The workers HTMX partial filters/annotates and renders a redesigned card grid. HTMX polling is unchanged.

**Tech Stack:** Django 5, DRF, HTMX (existing `hx-trigger="every 5s"` on `#dash-workers`, no new HTMX behaviour), Du Bois CSS palette in `services/app/static/css/main.css`, pytest.

**Model routing (per user request + global CLAUDE.md):**
- Backend Python (helpers, view, model, serializer, worker, tests): **Sonnet**
- Template + CSS task (Task 9): the implementing agent **MUST invoke the `frontend-design:frontend-design` skill** before writing HTML/CSS
- HTMX: no new behaviour required; **do not** add HTMX. (If a future change needs HTMX docs, use context7 `mcp__plugin_context7_context7__resolve-library-id` → `query-docs` for `htmx`.) **Do not** grep/glob — use `mcp__vexp__run_pipeline` if more context is needed.

**Key decisions (locked with user):**
1. Stale-drop cutoff = `STALE_DROP_SECONDS = 1800` (30 min; single tunable constant).
2. Live highlight window = `LIVE_WINDOW_SECONDS = 300`; two visible states: **live** (green) vs **reporting** (neutral).
3. One card per `worker_id`; per-engine rows derived server-side.
4. **time/ply** = pure engine speed, derived: `Σ duration_seconds ÷ Σ analyzed plies`, **per engine** (`MoveAnalysis` for stockfish, `Lc0MoveAnalysis` for lc0).
5. **batch billable time/game** (option a) = `(last_seen − session_started_at) ÷ games_processed`, per-worker; folds in in-session infra overhead, not pre-process build/teardown.
6. Batch cap M via **structured heartbeat field** (not status_message parsing).
7. Both metrics carry **UI tooltips** stating their definitions.

**Worker change ⇒ release:** Tasks 5/6/8 change `services/local_worker/`. Per project CLAUDE.md, bump `services/local_worker/pyproject.toml` `version` (0.9.12 → **0.9.13**) and remind the user to `git tag worker-v0.9.13 && git push origin worker-v0.9.13` after merge.

**Setup for every backend task:** activate the venv first — `source .venv/bin/activate` (from repo root `/Users/christopherwebster/Projects/wood_league`). Run app tests from `services/app`. After editing any `.py`, run `bandit -ll <file>` and fix Medium/High (per `services/app/CLAUDE.md`).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `services/app/analysis/dashboard_helpers.py` | Live-state classification + per-engine metrics + recent-games + billable/game | Modify (add constants + 4 helpers) |
| `services/app/analysis/views_dashboard.py` | `dashboard_workers` partial: filter stale, annotate live, build card dicts | Modify (`dashboard_workers` body) |
| `services/app/analysis/models.py` | `WorkerHeartbeat`: 3 new fields | Modify |
| `services/app/analysis/migrations/00NN_*.py` | DB migration for new fields | Create (generated) |
| `services/app/api/serializers.py` | `HeartbeatSerializer`: 3 optional fields | Modify |
| `services/app/api/views.py` | `HeartbeatView`: persist new fields | Modify |
| `services/local_worker/local_worker/worker_client/client.py` | `heartbeat()`: send new optional fields | Modify |
| `services/local_worker/local_worker/loop.py` | Compute session start; pass batch counters to heartbeat | Modify |
| `services/local_worker/pyproject.toml` | Version bump 0.9.12 → 0.9.13 | Modify |
| `services/app/templates/analysis/_dash_workers.html` | Redesigned card: LIVE badge, per-engine rows, progress bar, recent games, tooltips | Modify |
| `services/app/static/css/main.css` | `.dash-worker-card--live`, badge, progress bar, engine rows, recent list | Modify |
| `services/app/analysis/tests/test_dashboard_helpers.py` | Helper unit tests | Modify |
| `services/app/analysis/tests/test_dashboard_view.py` | `dashboard_workers` filtering/shape tests | Modify |
| `services/app/api/tests/test_serializers.py` | Heartbeat serializer backward-compat + new fields | Modify |
| `services/app/api/tests/test_endpoints.py` | `HeartbeatView` persists new fields | Modify |
| `services/local_worker/tests/test_loop.py` (or existing loop test) | Heartbeat sends batch fields | Modify/Create |

---

## Task 1: Live-state constants + classifier helper

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py` (`__all__` ~L28; constants ~L46; new helper near `_liveness_for`)
- Test: `services/app/analysis/tests/test_dashboard_helpers.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/analysis/tests/test_dashboard_helpers.py`:

```python
from datetime import timedelta

from analysis.dashboard_helpers import (
    LIVE_WINDOW_SECONDS,
    STALE_DROP_SECONDS,
    _worker_live_state,
)


def test_live_window_and_stale_drop_constants():
    assert LIVE_WINDOW_SECONDS == 300
    assert STALE_DROP_SECONDS == 1800


def test_worker_live_state_live_within_window():
    assert _worker_live_state(timedelta(seconds=0)) == "live"
    assert _worker_live_state(timedelta(seconds=299)) == "live"


def test_worker_live_state_reporting_between_window_and_drop():
    assert _worker_live_state(timedelta(seconds=300)) == "reporting"
    assert _worker_live_state(timedelta(seconds=1799)) == "reporting"


def test_worker_live_state_none_when_stale_or_missing():
    assert _worker_live_state(timedelta(seconds=1800)) is None
    assert _worker_live_state(None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_helpers.py -k "live_state or stale_drop_constants" -v`
Expected: FAIL — `ImportError: cannot import name 'LIVE_WINDOW_SECONDS'`

- [ ] **Step 3: Add constants + helper**

In `services/app/analysis/dashboard_helpers.py`, add to the `__all__` list (near L28):

```python
    "LIVE_WINDOW_SECONDS",
    "STALE_DROP_SECONDS",
    "_worker_live_state",
```

Below the existing `LIVENESS_WARNING_SECONDS = 120` line (~L47), add:

```python
# Workers-dashboard windows (issue #128). Distinct from the banner's
# 60s/120s health buckets above — these only gate the workers card grid.
LIVE_WINDOW_SECONDS = 300       # heartbeat within this → "live" highlight
STALE_DROP_SECONDS = 1800       # heartbeat older than this → not rendered
```

Immediately after the `_liveness_for` function, add:

```python
def _worker_live_state(delta: timedelta | None) -> str | None:
    """Classify a worker's heartbeat recency for the workers dashboard.

    Distinct from :func:`_liveness_for` (which drives the banner's
    60s/120s health buckets). Here we only need three outcomes:
    genuinely live, reporting-but-not-live, or too stale to render.

    Args:
        delta: ``now - last_seen``, or ``None`` if no heartbeat exists.

    Returns:
        ``"live"`` when within ``LIVE_WINDOW_SECONDS``; ``"reporting"``
        when older but within ``STALE_DROP_SECONDS``; ``None`` when the
        worker is too stale to show (caller should drop it) or ``delta``
        is ``None``.
    """
    if delta is None:
        return None
    seconds = delta.total_seconds()
    if seconds < LIVE_WINDOW_SECONDS:
        return "live"
    if seconds < STALE_DROP_SECONDS:
        return "reporting"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_helpers.py -k "live_state or stale_drop_constants" -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league && bandit -ll services/app/analysis/dashboard_helpers.py
git add services/app/analysis/dashboard_helpers.py services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(dashboard): add live-window/stale-drop constants + _worker_live_state (#128)"
```

Expected: bandit "No issues identified."

---

## Task 2: Per-engine timing metrics helper

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py` (add `_worker_engine_metrics`; ensure `from django.db.models import Count` import present)
- Test: `services/app/analysis/tests/test_dashboard_helpers.py`

**Model relations (verified):** `GameAnalysis.game` related_name `analysis`, `MoveAnalysis.analysis` related_name `moves`; `Lc0GameAnalysis.game` related_name `lc0_analysis`, `Lc0MoveAnalysis.analysis` related_name `moves`. `AnalysisJob.worker_id` equals `WorkerHeartbeat.worker_id` (same `_worker_id(settings)` used by both completion and heartbeat calls).

- [ ] **Step 1: Write the failing test**

Add to `test_dashboard_helpers.py`:

```python
import pytest
from django.utils import timezone

from analysis.dashboard_helpers import _worker_engine_metrics


@pytest.mark.django_db
def test_worker_engine_metrics_per_engine_time_per_ply_and_game():
    from analysis.models import (
        AnalysisJob, GameAnalysis, Lc0GameAnalysis,
        Lc0MoveAnalysis, MoveAnalysis,
    )
    from games.models import Game

    game_a = Game.objects.create(slug="g-a")
    game_b = Game.objects.create(slug="g-b")

    # Stockfish: game_a 10s / 20 plies, game_b 30s / 40 plies
    for g, dur in ((game_a, 10.0), (game_b, 30.0)):
        AnalysisJob.objects.create(
            game=g, engine="stockfish", status=AnalysisJob.STATUS_COMPLETED,
            worker_id="w1", duration_seconds=dur, completed_at=timezone.now(),
        )
    sa_a = GameAnalysis.objects.create(game=game_a)
    sa_b = GameAnalysis.objects.create(game=game_b)
    for i in range(20):
        MoveAnalysis.objects.create(analysis=sa_a, ply=i, san="e4", fen="x", cp_eval=0.0)
    for i in range(40):
        MoveAnalysis.objects.create(analysis=sa_b, ply=i, san="e4", fen="x", cp_eval=0.0)

    # lc0: game_a 5s / 10 plies
    AnalysisJob.objects.create(
        game=game_a, engine="lc0", status=AnalysisJob.STATUS_COMPLETED,
        worker_id="w1", duration_seconds=5.0, completed_at=timezone.now(),
    )
    la_a = Lc0GameAnalysis.objects.create(game=game_a)
    for i in range(10):
        Lc0MoveAnalysis.objects.create(analysis=la_a, ply=i, san="e4", fen="x")

    rows = _worker_engine_metrics("w1")
    by_engine = {r["engine"]: r for r in rows}

    # stockfish: total 40s / 60 plies = 0.667 s/ply; avg game = 20.0s
    assert by_engine["stockfish"]["avg_seconds_per_ply"] == pytest.approx(0.667, abs=0.001)
    assert by_engine["stockfish"]["avg_seconds_per_game"] == pytest.approx(20.0)
    assert by_engine["stockfish"]["completed"] == 2
    # lc0: 5s / 10 plies = 0.5 s/ply; avg game 5.0s
    assert by_engine["lc0"]["avg_seconds_per_ply"] == pytest.approx(0.5)
    assert by_engine["lc0"]["avg_seconds_per_game"] == pytest.approx(5.0)


@pytest.mark.django_db
def test_worker_engine_metrics_skips_engines_with_no_jobs():
    rows = _worker_engine_metrics("nobody")
    assert rows == []


@pytest.mark.django_db
def test_worker_engine_metrics_ply_none_when_no_analysis_rows():
    from analysis.models import AnalysisJob
    from games.models import Game

    g = Game.objects.create(slug="g-x")
    AnalysisJob.objects.create(
        game=g, engine="stockfish", status=AnalysisJob.STATUS_COMPLETED,
        worker_id="w2", duration_seconds=12.0, completed_at=timezone.now(),
    )
    rows = _worker_engine_metrics("w2")
    assert rows[0]["avg_seconds_per_ply"] is None
    assert rows[0]["avg_seconds_per_game"] == pytest.approx(12.0)
```

> Note: if `Game.objects.create(slug=...)` requires more required fields in this codebase, the implementing agent must add the minimal required kwargs (inspect `games.models.Game` via `mcp__vexp__get_skeleton`), not stub them out.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_helpers.py -k worker_engine_metrics -v`
Expected: FAIL — `ImportError: cannot import name '_worker_engine_metrics'`

- [ ] **Step 3: Add the helper**

In `dashboard_helpers.py`: ensure the top imports include `from django.db.models import Count` (add it if the existing `from django.db.models import ...` line lacks `Count`). Add `"_worker_engine_metrics"` to `__all__`. Append the function:

```python
def _worker_engine_metrics(worker_id: str, sample: int = 50) -> list[dict[str, Any]]:
    """Per-engine timing metrics for one worker, from completed jobs.

    For each engine the worker has completed jobs in, computes the mean
    wall-clock seconds per game and the mean seconds per *analyzed ply*
    (total engine duration ÷ total plies the engine evaluated). Time/ply
    is the length-normalised "pure engine speed" signal: dividing summed
    duration by summed plies makes long and short games comparable.

    Ply counts come from engine-specific analysis rows: ``MoveAnalysis``
    for stockfish, ``Lc0MoveAnalysis`` for lc0.

    Args:
        worker_id: The worker whose jobs to aggregate.
        sample: Max recent completed jobs per engine to average over.

    Returns:
        One dict per engine that has completed jobs, keys: ``engine``,
        ``avg_seconds_per_game`` (float), ``avg_seconds_per_ply``
        (float | None), ``completed`` (int). Engines with no jobs are
        omitted. Order: lc0 then stockfish.
    """
    from analysis.models import AnalysisJob, Lc0MoveAnalysis, MoveAnalysis

    rows: list[dict[str, Any]] = []
    for engine in ("lc0", "stockfish"):
        jobs = list(
            AnalysisJob.objects.filter(
                worker_id=worker_id,
                engine=engine,
                status=AnalysisJob.STATUS_COMPLETED,
                duration_seconds__isnull=False,
            )
            .order_by("-completed_at")
            .values("game_id", "duration_seconds")[:sample]
        )
        if not jobs:
            continue
        durations = [j["duration_seconds"] for j in jobs]
        game_ids = [j["game_id"] for j in jobs]
        total_duration = sum(durations)
        avg_game = total_duration / len(durations)

        move_model = Lc0MoveAnalysis if engine == "lc0" else MoveAnalysis
        ply_rows = (
            move_model.objects
            .filter(analysis__game_id__in=game_ids)
            .values("analysis__game_id")
            .annotate(plies=Count("id"))
        )
        plies_by_game = {r["analysis__game_id"]: r["plies"] for r in ply_rows}
        total_plies = sum(plies_by_game.get(gid, 0) for gid in game_ids)
        avg_ply = (total_duration / total_plies) if total_plies else None

        rows.append({
            "engine": engine,
            "avg_seconds_per_game": round(avg_game, 1),
            "avg_seconds_per_ply": (
                round(avg_ply, 3) if avg_ply is not None else None
            ),
            "completed": len(durations),
        })
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_helpers.py -k worker_engine_metrics -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league && bandit -ll services/app/analysis/dashboard_helpers.py
git add services/app/analysis/dashboard_helpers.py services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(dashboard): per-engine time/ply + time/game helper (#128)"
```

---

## Task 3: Recent-games + billable-per-game helpers

**Files:**
- Modify: `services/app/analysis/dashboard_helpers.py` (add `_worker_recent_games`, `_batch_billable_per_game`)
- Test: `services/app/analysis/tests/test_dashboard_helpers.py`

- [ ] **Step 1: Write the failing test**

Add to `test_dashboard_helpers.py`:

```python
from datetime import timedelta

from analysis.dashboard_helpers import (
    _batch_billable_per_game,
    _worker_recent_games,
)


@pytest.mark.django_db
def test_worker_recent_games_newest_first_limited():
    from analysis.models import AnalysisJob
    from games.models import Game

    now = timezone.now()
    for i in range(12):
        g = Game.objects.create(slug=f"rg-{i}")
        AnalysisJob.objects.create(
            game=g, engine="stockfish", status=AnalysisJob.STATUS_COMPLETED,
            worker_id="wr", duration_seconds=float(i),
            completed_at=now - timedelta(minutes=i),
        )
    rows = _worker_recent_games("wr", limit=10)
    assert len(rows) == 10
    # newest (i=0, minutes=0) first
    assert rows[0]["duration_seconds"] == 0.0
    assert rows[0]["game_label"].startswith("#")
    assert "engine" in rows[0] and "completed_at" in rows[0]


def test_batch_billable_per_game_basic():
    start = timezone.now()
    last = start + timedelta(seconds=600)
    assert _batch_billable_per_game(start, last, 4) == pytest.approx(150.0)


def test_batch_billable_per_game_none_paths():
    now = timezone.now()
    assert _batch_billable_per_game(None, now, 4) is None
    assert _batch_billable_per_game(now, None, 4) is None
    assert _batch_billable_per_game(now, now + timedelta(seconds=10), 0) is None
    assert _batch_billable_per_game(now, now, 4) is None  # zero span
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_helpers.py -k "recent_games or billable" -v`
Expected: FAIL — `ImportError: cannot import name '_worker_recent_games'`

- [ ] **Step 3: Add the helpers**

Add `"_worker_recent_games"` and `"_batch_billable_per_game"` to `__all__`. Append:

```python
def _worker_recent_games(worker_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Most recently completed games for one worker, across engines.

    Args:
        worker_id: The worker whose completed jobs to list.
        limit: Maximum rows to return (default 10, newest first).

    Returns:
        List of dicts, keys: ``game_label`` (``"#<id>"``), ``game_url``
        (str | None — game analysis page when slug resolvable),
        ``engine``, ``duration_seconds`` (float | None), ``completed_at``
        (datetime).
    """
    from analysis.models import AnalysisJob

    jobs = (
        AnalysisJob.objects
        .filter(
            worker_id=worker_id,
            status=AnalysisJob.STATUS_COMPLETED,
            completed_at__isnull=False,
        )
        .select_related("game")
        .order_by("-completed_at")[:limit]
    )
    out: list[dict[str, Any]] = []
    for job in jobs:
        game = job.game
        url = (
            reverse("games:analysis", kwargs={"slug": game.slug})
            if game and game.slug else None
        )
        out.append({
            "game_label": f"#{job.game_id}",
            "game_url": url,
            "engine": job.engine,
            "duration_seconds": (
                round(job.duration_seconds, 1)
                if job.duration_seconds is not None else None
            ),
            "completed_at": job.completed_at,
        })
    return out


def _batch_billable_per_game(
    session_started_at: Any, last_seen: Any, games_processed: int
) -> float | None:
    """Billable wall-clock seconds per game for a worker's batch.

    Computes ``(last_seen - session_started_at) / games_processed``.
    Unlike per-engine time/game (pure engine duration), this folds in
    in-session infrastructure overhead — job checkout, model/network
    load, result upload, and idle gaps between jobs — i.e. the time the
    instance is billed for while running. It excludes pre-process image
    build and post-run teardown, which happen outside the worker.

    Args:
        session_started_at: Worker run start (TZ-aware) or ``None``.
        last_seen: Most recent heartbeat time (TZ-aware) or ``None``.
        games_processed: Games completed this session.

    Returns:
        Seconds per game (1 dp), or ``None`` when inputs are missing,
        ``games_processed`` <= 0, or the span is non-positive.
    """
    if session_started_at is None or last_seen is None or games_processed <= 0:
        return None
    span = (last_seen - session_started_at).total_seconds()
    if span <= 0:
        return None
    return round(span / games_processed, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_helpers.py -k "recent_games or billable" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league && bandit -ll services/app/analysis/dashboard_helpers.py
git add services/app/analysis/dashboard_helpers.py services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(dashboard): recent-games + billable-per-game helpers (#128)"
```

---

## Task 4: WorkerHeartbeat structured fields + migration

**Files:**
- Modify: `services/app/analysis/models.py` (`WorkerHeartbeat`, after `stockfish_binary`)
- Create: `services/app/analysis/migrations/00NN_workerheartbeat_batch_fields.py` (generated)
- Test: `services/app/analysis/tests/test_dashboard_helpers.py` (model smoke)

- [ ] **Step 1: Write the failing test**

Add to `test_dashboard_helpers.py`:

```python
@pytest.mark.django_db
def test_workerheartbeat_has_batch_fields_with_defaults():
    from analysis.models import WorkerHeartbeat

    wh = WorkerHeartbeat.objects.create(worker_id="wbf")
    assert wh.batch_total is None
    assert wh.batch_processed == 0
    assert wh.session_started_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_helpers.py -k batch_fields -v`
Expected: FAIL — `AttributeError: 'WorkerHeartbeat' object has no attribute 'batch_total'`

- [ ] **Step 3: Add fields**

In `services/app/analysis/models.py`, in `WorkerHeartbeat`, immediately after the `stockfish_binary = models.CharField(...)` field:

```python
    batch_total = models.IntegerField(
        null=True, blank=True,
        help_text="Worker max_jobs run cap (M in N/M). Null = unlimited.",
    )
    batch_processed = models.IntegerField(
        default=0,
        help_text="Jobs completed so far this worker session (N in N/M).",
    )
    session_started_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Wall-clock start of the current worker run/session.",
    )
```

- [ ] **Step 4: Generate + apply migration**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
python manage.py makemigrations analysis --name workerheartbeat_batch_fields
python manage.py migrate analysis
```

Expected: a new migration file under `services/app/analysis/migrations/`; `migrate` reports OK.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_helpers.py -k batch_fields -v`
Expected: PASS

- [ ] **Step 6: Bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league && bandit -ll services/app/analysis/models.py
git add services/app/analysis/models.py services/app/analysis/migrations/ services/app/analysis/tests/test_dashboard_helpers.py
git commit -m "feat(model): WorkerHeartbeat batch_total/batch_processed/session_started_at (#128)"
```

---

## Task 5: Heartbeat serializer + view persist new fields (backward-compatible)

**Files:**
- Modify: `services/app/api/serializers.py` (`HeartbeatSerializer`, ~L147)
- Modify: `services/app/api/views.py` (`HeartbeatView.post`, ~L195)
- Test: `services/app/api/tests/test_serializers.py`, `services/app/api/tests/test_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Add to `services/app/api/tests/test_serializers.py`:

```python
def test_heartbeat_serializer_accepts_legacy_payload_without_batch_fields():
    from api.serializers import HeartbeatSerializer

    ser = HeartbeatSerializer(data={
        "worker_id": "w1", "engine": "lc0", "status_message": "processed=3",
    })
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["batch_total"] is None
    assert ser.validated_data["batch_processed"] == 0
    assert ser.validated_data["session_started_at"] is None


def test_heartbeat_serializer_accepts_batch_fields():
    from api.serializers import HeartbeatSerializer

    ser = HeartbeatSerializer(data={
        "worker_id": "w1", "engine": "lc0", "status_message": "processed=3",
        "batch_total": 6, "batch_processed": 3,
        "session_started_at": "2026-05-17T10:00:00Z",
    })
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["batch_total"] == 6
    assert ser.validated_data["batch_processed"] == 3
    assert ser.validated_data["session_started_at"] is not None
```

Add to `services/app/api/tests/test_endpoints.py` (follow that file's existing auth/client fixture pattern — locate the existing heartbeat test for the helper/fixture names and mirror them):

```python
@pytest.mark.django_db
def test_heartbeat_view_persists_batch_fields(self):
    # Mirror the auth headers / URL used by the existing heartbeat test
    # in this file. Replace `self._auth()` / url below with that pattern.
    resp = self.client.post(
        "/api/v1/heartbeat/",
        {
            "worker_id": "wbatch", "engine": "lc0",
            "status_message": "processed=2", "batch_total": 6,
            "batch_processed": 2, "session_started_at": "2026-05-17T10:00:00Z",
        },
        format="json", **self._auth(),
    )
    assert resp.status_code == 200, resp.content
    from analysis.models import WorkerHeartbeat
    wh = WorkerHeartbeat.objects.get(worker_id="wbatch")
    assert wh.batch_total == 6
    assert wh.batch_processed == 2
    assert wh.session_started_at is not None
```

> The implementing agent must adapt `self.client` / `self._auth()` / class structure to the conventions already in `test_endpoints.py` (read the existing heartbeat test first via `mcp__vexp__get_skeleton`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && python -m pytest api/tests/test_serializers.py -k heartbeat api/tests/test_endpoints.py -k heartbeat_view_persists_batch -v`
Expected: FAIL — `KeyError: 'batch_total'` / missing fields.

- [ ] **Step 3: Extend the serializer**

In `services/app/api/serializers.py`, inside `HeartbeatSerializer` after `status_message`:

```python
    batch_total = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    batch_processed = serializers.IntegerField(required=False, default=0)
    session_started_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None
    )
```

- [ ] **Step 4: Persist in the view**

In `services/app/api/views.py`, `HeartbeatView.post`, change the `update_or_create` `defaults=dict(...)` to:

```python
        WorkerHeartbeat.objects.update_or_create(
            worker_id=d['worker_id'],
            defaults=dict(
                engine=d['engine'],
                status_message=d['status_message'],
                batch_total=d['batch_total'],
                batch_processed=d['batch_processed'],
                session_started_at=d['session_started_at'],
                last_seen=timezone.now(),
            ),
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/app && python -m pytest api/tests/test_serializers.py -k heartbeat api/tests/test_endpoints.py -k heartbeat -v`
Expected: PASS (existing heartbeat tests still green + new ones pass)

- [ ] **Step 6: Bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league && bandit -ll services/app/api/serializers.py services/app/api/views.py
git add services/app/api/serializers.py services/app/api/views.py services/app/api/tests/
git commit -m "feat(api): heartbeat accepts+persists batch_total/processed/session_started_at (#128)"
```

---

## Task 6: Worker reports batch position + session start

**Files:**
- Modify: `services/local_worker/local_worker/worker_client/client.py` (`heartbeat`, ~L168)
- Modify: `services/local_worker/local_worker/loop.py` (imports; `run` session start ~L333; `_send_heartbeat` ~L341)
- Modify: `services/local_worker/pyproject.toml` (version 0.9.12 → 0.9.13)
- Test: existing worker loop/client test module (find with `mcp__vexp__get_skeleton` on `services/local_worker/tests/`)

- [ ] **Step 1: Write the failing test**

In the worker test suite (e.g. `services/local_worker/tests/test_loop.py` — create if absent, mirroring `_shared.py` fakes used by sibling tests), add a test asserting the heartbeat client forwards the new kwargs into the POST body:

```python
def test_heartbeat_includes_batch_fields(monkeypatch):
    from local_worker.worker_client.client import WorkerClient

    captured = {}

    def fake_post(self, path, payload):
        captured["path"] = path
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(WorkerClient, "_post", fake_post)
    c = WorkerClient(base_url="http://x", api_key="k")
    c.heartbeat(
        worker_id="w1", engine="lc0", status_message="processed=2",
        batch_total=6, batch_processed=2,
        session_started_at="2026-05-17T10:00:00+00:00",
    )
    assert captured["path"] == "/api/v1/heartbeat/"
    assert captured["payload"]["batch_total"] == 6
    assert captured["payload"]["batch_processed"] == 2
    assert captured["payload"]["session_started_at"] == "2026-05-17T10:00:00+00:00"


def test_heartbeat_legacy_call_omits_batch_fields(monkeypatch):
    from local_worker.worker_client.client import WorkerClient

    captured = {}
    monkeypatch.setattr(
        WorkerClient, "_post",
        lambda self, path, payload: captured.setdefault("payload", payload) or {},
    )
    c = WorkerClient(base_url="http://x", api_key="k")
    c.heartbeat(worker_id="w1", engine="lc0", status_message="processed=2")
    assert "batch_total" not in captured["payload"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && python -m pytest tests/test_loop.py -k heartbeat -v`
Expected: FAIL — `TypeError: heartbeat() got an unexpected keyword argument 'batch_total'`

- [ ] **Step 3: Extend the client `heartbeat`**

In `services/local_worker/local_worker/worker_client/client.py`, replace the `heartbeat` method (~L168) with:

```python
    def heartbeat(
        self, *, worker_id: str, engine: str, status_message: str = '',
        batch_total: int | None = None, batch_processed: int = 0,
        session_started_at: str | None = None,
    ) -> None:
        """Send a worker heartbeat to indicate the worker is alive.

        Args:
            worker_id: Unique worker identifier.
            engine: 'stockfish' or 'lc0'.
            status_message: Human-readable status string.
            batch_total: max_jobs run cap (M in N/M); ``None`` = unlimited.
            batch_processed: Jobs completed so far this session (N).
            session_started_at: ISO-8601 wall-clock start of this run, for
                the dashboard's billable time/game metric.

        Backward compatible: the batch fields are only added to the
        payload when supplied, so older servers ignore them and newer
        callers that omit them behave as before.
        """
        payload = {
            'worker_id': worker_id,
            'engine': engine,
            'status_message': status_message,
        }
        if batch_total is not None:
            payload['batch_total'] = batch_total
        if batch_processed:
            payload['batch_processed'] = batch_processed
        if session_started_at is not None:
            payload['session_started_at'] = session_started_at
        try:
            self._post('/api/v1/heartbeat/', payload)
        except WorkerClientError:
            log.warning('Heartbeat failed — continuing')
```

- [ ] **Step 4: Wire session start + counters in the loop**

In `services/local_worker/local_worker/loop.py`:

Add to the imports block (after `import time`):

```python
from datetime import datetime, timezone as _dt_timezone
```

In `run(...)`, just after `start_time = time.monotonic()` (~L333), add:

```python
    session_started_at = datetime.now(_dt_timezone.utc).isoformat()
```

Replace the `client.heartbeat(...)` call inside `_send_heartbeat` with:

```python
                client.heartbeat(
                    worker_id=worker_id,
                    engine=engine,
                    status_message=build_heartbeat_status(stats),
                    batch_total=max_jobs,
                    batch_processed=processed,
                    session_started_at=session_started_at,
                )
```

(`max_jobs`, `processed`, and `session_started_at` are read from the enclosing `run` scope; `_send_heartbeat` only reads them, so no `nonlocal` is needed.)

- [ ] **Step 5: Bump worker version**

In `services/local_worker/pyproject.toml`, change `version = "0.9.12"` to `version = "0.9.13"`. If `loop.py` / `client.py` carry a changelog header block, add a line: `2026-05-17 (#128): heartbeat carries batch_total/batch_processed/session_started_at.`

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd services/local_worker && python -m pytest tests/test_loop.py -k heartbeat -v`
Expected: PASS

Then run the worker loop regression subset: `cd services/local_worker && python -m pytest tests/ -k "loop or heartbeat or client" -q`
Expected: PASS (no regressions in existing loop/client tests).

- [ ] **Step 7: Bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league && bandit -ll services/local_worker/local_worker/worker_client/client.py services/local_worker/local_worker/loop.py
git add services/local_worker/
git commit -m "feat(worker): heartbeat reports batch_total/processed/session_started_at; bump 0.9.13 (#128)"
```

> **Release reminder (surface to user at end):** after merge, `git tag worker-v0.9.13 && git push origin worker-v0.9.13` to publish `wood-league-worker` 0.9.13 to PyPI.

---

## Task 7: Rebuild `dashboard_workers` — filter stale, annotate live, build cards

**Files:**
- Modify: `services/app/analysis/views_dashboard.py` (`dashboard_workers` body)
- Test: `services/app/analysis/tests/test_dashboard_view.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/analysis/tests/test_dashboard_view.py` (mirror the file's existing client/staff-login fixture; inspect an existing dashboard test first):

```python
@pytest.mark.django_db
def test_dashboard_workers_drops_stale_flags_live_and_builds_cards(client, django_user_model):
    from datetime import timedelta
    from django.urls import reverse
    from django.utils import timezone
    from analysis.models import AnalysisJob, WorkerHeartbeat
    from games.models import Game

    staff = django_user_model.objects.create_user(
        username="s", password="p", is_staff=True, is_superuser=True
    )
    client.force_login(staff)
    now = timezone.now()

    live = WorkerHeartbeat.objects.create(
        worker_id="live-1", engine="lc0", batch_total=6, batch_processed=2,
        session_started_at=now - timedelta(seconds=600),
    )
    WorkerHeartbeat.objects.filter(pk=live.pk).update(last_seen=now - timedelta(seconds=30))

    reporting = WorkerHeartbeat.objects.create(worker_id="rep-1", engine="lc0")
    WorkerHeartbeat.objects.filter(pk=reporting.pk).update(
        last_seen=now - timedelta(seconds=600)
    )

    dead = WorkerHeartbeat.objects.create(worker_id="dead-1", engine="lc0")
    WorkerHeartbeat.objects.filter(pk=dead.pk).update(
        last_seen=now - timedelta(seconds=4000)
    )

    g = Game.objects.create(slug="dv-1")
    AnalysisJob.objects.create(
        game=g, engine="lc0", status=AnalysisJob.STATUS_COMPLETED,
        worker_id="live-1", duration_seconds=12.0, completed_at=now,
    )

    resp = client.get(reverse("analysis:dash_workers"))
    assert resp.status_code == 200
    cards = resp.context["cards"]
    ids = {c["worker_id"]: c for c in cards}

    assert "dead-1" not in ids                       # stale-dropped
    assert ids["live-1"]["live_state"] == "live"
    assert ids["rep-1"]["live_state"] == "reporting"
    lc = ids["live-1"]
    assert lc["batch_total"] == 6 and lc["batch_processed"] == 2
    assert lc["batch_percent"] == pytest.approx(33.33, abs=0.1)
    assert any(r["engine"] == "lc0" for r in lc["engine_rows"])
    assert lc["billable_per_game"] is not None
    assert isinstance(lc["recent_games"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_view.py -k drops_stale_flags_live -v`
Expected: FAIL — `KeyError: 'live_state'` (old card shape).

- [ ] **Step 3: Rewrite `dashboard_workers`**

In `services/app/analysis/views_dashboard.py`, replace the entire `dashboard_workers` function body with:

```python
def dashboard_workers(request: HttpRequest) -> HttpResponse:
    """Render the workers partial — one card per live/reporting worker.

    Workers whose last heartbeat is older than ``STALE_DROP_SECONDS`` are
    dropped entirely. Survivors are flagged ``"live"`` (heartbeat within
    ``LIVE_WINDOW_SECONDS``) or ``"reporting"``. Each card carries
    per-engine timing (time/ply, time/game) derived from completed
    ``AnalysisJob`` rows, a batch-progress fraction (N/M from the
    heartbeat), a billable time/game figure, and the worker's 10 most
    recently completed games.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_workers.html``.
    """
    from analysis.models import WorkerHeartbeat
    from analysis.dashboard_helpers import (
        _batch_billable_per_game,
        _worker_engine_metrics,
        _worker_live_state,
        _worker_recent_games,
    )

    now = timezone.now()
    cards: list[dict[str, Any]] = []
    for w in WorkerHeartbeat.objects.order_by("-last_seen"):
        last_seen = _aware(w.last_seen)
        delta_seen = now - last_seen if last_seen else None
        live_state = _worker_live_state(delta_seen)
        if live_state is None:
            continue  # stale-dropped or never seen

        session_started_at = _aware(w.session_started_at)
        billable = _batch_billable_per_game(
            session_started_at, last_seen, w.batch_processed
        )

        batch_total = w.batch_total
        batch_processed = w.batch_processed or 0
        if batch_total and batch_total > 0:
            batch_percent = round(
                min(batch_processed / batch_total, 1.0) * 100, 2
            )
        else:
            batch_percent = None

        cards.append({
            "worker_id": w.worker_id,
            "engine": w.engine,
            "status_message": w.status_message,
            "live_state": live_state,
            "seconds_since_seen": (
                int(delta_seen.total_seconds()) if delta_seen else None
            ),
            "engine_rows": _worker_engine_metrics(w.worker_id),
            "batch_total": batch_total,
            "batch_processed": batch_processed,
            "batch_percent": batch_percent,
            "billable_per_game": billable,
            "recent_games": _worker_recent_games(w.worker_id, limit=10),
        })
    return render(request, "analysis/_dash_workers.html", {"cards": cards})
```

> Remove any now-unused imports the old body relied on (`_format_memory_mb`, `_format_uptime`, `_game_link_for`, `_liveness_for`) **only if** no other function in the file uses them — verify with `mcp__vexp__get_skeleton` on `views_dashboard.py` before deleting (the banner uses `_liveness_for`; keep imports scoped inside their own functions as the codebase already does).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_view.py -k drops_stale_flags_live -v`
Expected: PASS

- [ ] **Step 5: Full dashboard regression**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_view.py analysis/tests/test_dashboard_helpers.py -q`
Expected: PASS (all dashboard tests green)

- [ ] **Step 6: Bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league && bandit -ll services/app/analysis/views_dashboard.py
git add services/app/analysis/views_dashboard.py services/app/analysis/tests/test_dashboard_view.py
git commit -m "feat(dashboard): filter stale workers, flag live, build per-engine cards (#128)"
```

---

## Task 8: Redesign the worker card template + CSS

**REQUIRED:** Before writing any HTML/CSS in this task, the implementing agent **MUST invoke the `frontend-design:frontend-design` skill** and follow it. Reuse the existing Du Bois palette and `.dash-worker-*` / `.pg-*` conventions in `services/app/static/css/main.css` (lines ~716–870 are the existing dashboard block) — **no new ad-hoc color values**, use the `var(--color-forest|gold|crimson|peat|ebony|cream|slate)` variables already defined. No new CSS framework, no JS.

**Files:**
- Modify: `services/app/templates/analysis/_dash_workers.html`
- Modify: `services/app/static/css/main.css` (append to the existing "Dashboard: worker grid + cards" block)

**Card context shape (from Task 7):** each `card` has `worker_id`, `engine`, `status_message`, `live_state` (`"live"` | `"reporting"`), `seconds_since_seen` (int|None), `engine_rows` (list of `{engine, avg_seconds_per_game, avg_seconds_per_ply|None, completed}`), `batch_total` (int|None), `batch_processed` (int), `batch_percent` (float|None), `billable_per_game` (float|None), `recent_games` (list of `{game_label, game_url|None, engine, duration_seconds|None, completed_at}`).

- [ ] **Step 1: Invoke the frontend-design skill**

Invoke `frontend-design:frontend-design`. State the goal: "Redesign a Django worker-status card (HTMX-polled partial) within an existing Du Bois-palette design system; reuse existing CSS variables and `.dash-worker-card` conventions; add a LIVE badge, per-engine metric rows, a batch-progress bar, a recent-games list, and metric tooltips."

- [ ] **Step 2: Rewrite `_dash_workers.html`**

Replace `services/app/templates/analysis/_dash_workers.html` with (keep the `{% comment %}` header convention, add a `2026-05-17 (#128)` changelog line; tooltips use the native `title` attribute so no JS is needed):

```django
{% comment %}
  Title: _dash_workers.html — Worker heartbeat cards
  Description: Grid of cards (one per live/reporting WorkerHeartbeat).
      Card shows a LIVE badge (green) when live, per-engine timing rows
      (time/ply = pure engine speed; time/game = engine wall-clock),
      a batch-progress bar (N/M), billable time/game (in-session infra
      time), and the 10 most recently completed games. Stale workers
      are filtered out server-side.
  Context: ``cards`` — list of dicts from ``dashboard_workers``.
  Changelog:
      2026-05-14 (#106): Initial real implementation + visual polish.
      2026-05-17 (#128): Live/reporting states, per-engine rows,
          batch progress bar, recent games, metric tooltips.
{% endcomment %}
<div class="pg-section">
  <div class="pg-head">
    <span class="pg-title">Workers ({{ cards|length }})</span>
    <span class="pg-caption">live = heartbeat &lt; 5m · refresh 5s</span>
  </div>

  {% if cards %}
    <div class="dash-worker-grid">
      {% for card in cards %}
        <div class="dash-worker-card dash-worker-card--{{ card.live_state }}">
          <div class="dash-worker-card__head">
            <span class="dash-dot dash-dot--{% if card.live_state == 'live' %}healthy{% else %}warning{% endif %}" aria-hidden="true"></span>
            <strong title="{{ card.worker_id }}">{{ card.worker_id }}</strong>
            {% if card.live_state == 'live' %}
              <span class="dash-badge-live">LIVE</span>
            {% else %}
              <span class="dash-badge-reporting">REPORTING</span>
            {% endif %}
            <span class="dash-worker-card__seen">
              {% if card.seconds_since_seen is not None %}{{ card.seconds_since_seen }}s ago{% else %}—{% endif %}
            </span>
          </div>

          {% if card.batch_total %}
          <div class="dash-worker-card__row">
            <span class="pg-caption" title="Jobs completed this run / the worker's max_jobs cap (WLW_MAX_JOBS).">
              batch {{ card.batch_processed }}/{{ card.batch_total }}
            </span>
          </div>
          <div class="dash-progress" role="progressbar"
               aria-valuenow="{{ card.batch_processed }}"
               aria-valuemin="0" aria-valuemax="{{ card.batch_total }}">
            <div class="dash-progress__bar" style="width: {{ card.batch_percent }}%;"></div>
          </div>
          {% else %}
          <div class="dash-worker-card__row">
            <span class="pg-caption" title="Worker has no max_jobs cap (drains the queue).">
              batch {{ card.batch_processed }} · uncapped
            </span>
          </div>
          {% endif %}

          <div class="dash-worker-card__row">
            <span class="pg-caption"
                  title="Wall-clock seconds per game across the whole run, including job checkout, model load, result upload and idle gaps — the in-session time the instance is billed for. Excludes pre-run image build and post-run teardown.">
              billable/game
            </span>
            <span>{% if card.billable_per_game is not None %}{{ card.billable_per_game }}s{% else %}—{% endif %}</span>
          </div>

          {% if card.engine_rows %}
            <table class="dash-engine-table">
              <thead>
                <tr>
                  <th>engine</th>
                  <th title="Pure engine speed: total engine duration ÷ total plies analyzed. Length-normalised so long and short games compare fairly.">s/ply</th>
                  <th title="Mean engine duration per game (not length-normalised; varies with game length).">s/game</th>
                  <th title="Completed jobs sampled for these averages (most recent up to 50).">n</th>
                </tr>
              </thead>
              <tbody>
                {% for row in card.engine_rows %}
                  <tr>
                    <td>{{ row.engine }}</td>
                    <td>{% if row.avg_seconds_per_ply is not None %}{{ row.avg_seconds_per_ply }}{% else %}—{% endif %}</td>
                    <td>{{ row.avg_seconds_per_game }}</td>
                    <td>{{ row.completed }}</td>
                  </tr>
                {% endfor %}
              </tbody>
            </table>
          {% else %}
            <div class="dash-worker-card__row"><span class="pg-caption">no completed jobs yet</span></div>
          {% endif %}

          <div class="dash-worker-card__foot">
            <span class="pg-caption">last 10 games</span>
            {% if card.recent_games %}
              <ul class="dash-recent-list">
                {% for g in card.recent_games %}
                  <li>
                    {% if g.game_url %}<a href="{{ g.game_url }}">{{ g.game_label }}</a>{% else %}{{ g.game_label }}{% endif %}
                    <span class="dash-recent-list__meta">{{ g.engine }} · {% if g.duration_seconds is not None %}{{ g.duration_seconds }}s{% else %}—{% endif %}</span>
                  </li>
                {% endfor %}
              </ul>
            {% else %}
              <span class="pg-caption">—</span>
            {% endif %}
          </div>
        </div>
      {% endfor %}
    </div>
  {% else %}
    <p class="dash-empty">No live or recently-reporting workers.</p>
  {% endif %}
</div>
```

- [ ] **Step 3: Append CSS**

In `services/app/static/css/main.css`, within the existing "Dashboard: worker grid + cards" block, **add** (do not remove existing `.dash-worker-card--healthy/warning/stale` — other states may still be referenced elsewhere):

```css
  .dash-worker-card--live {
    border-top-color: var(--color-forest);
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-forest) 30%, transparent);
    background: color-mix(in srgb, var(--color-forest) 4%, var(--color-cream));
  }
  .dash-worker-card--reporting {
    border-top-color: var(--color-slate);
  }

  .dash-badge-live,
  .dash-badge-reporting {
    font-family: var(--font-mono);
    font-size: 0.55rem;
    letter-spacing: 0.12em;
    padding: 0.08rem 0.4rem;
    border-radius: 0;
    white-space: nowrap;
  }
  .dash-badge-live {
    color: var(--color-cream);
    background: var(--color-forest);
  }
  .dash-badge-reporting {
    color: var(--color-peat);
    background: color-mix(in srgb, var(--color-slate) 22%, transparent);
  }

  .dash-progress {
    height: 0.5rem;
    background: color-mix(in srgb, var(--color-ebony) 12%, transparent);
    overflow: hidden;
  }
  .dash-progress__bar {
    height: 100%;
    background: var(--color-forest);
    transition: width 0.4s ease;
  }

  .dash-engine-table {
    width: 100%;
    border-collapse: collapse;
    font-family: var(--font-mono);
    font-size: 0.68rem;
    color: var(--color-ebony);
  }
  .dash-engine-table th {
    text-align: left;
    font-weight: 600;
    color: var(--color-peat);
    border-bottom: 1px solid color-mix(in srgb, var(--color-ebony) 14%, transparent);
    padding: 0.15rem 0.3rem;
    cursor: help;
  }
  .dash-engine-table td {
    padding: 0.15rem 0.3rem;
    border-bottom: 1px dotted color-mix(in srgb, var(--color-ebony) 10%, transparent);
  }

  .dash-recent-list {
    list-style: none;
    margin: 0.25rem 0 0;
    padding: 0;
    font-family: var(--font-mono);
    font-size: 0.62rem;
    line-height: 1.6;
  }
  .dash-recent-list li {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .dash-recent-list__meta { color: var(--color-peat); }
```

The `cursor: help;` plus native `title` attributes give the required metric tooltips with no JS.

- [ ] **Step 4: Visual smoke check**

Run: `cd services/app && python -m pytest analysis/tests/test_dashboard_view.py -k workers -v`
Expected: PASS (template renders without `TemplateSyntaxError`).

Then start the dev server and eyeball the dashboard (manual): `cd services/app && python manage.py runserver` → visit `/analysis/dashboard/` (or the dashboard URL). Confirm LIVE badge, progress bar, per-engine table, tooltips on hover, recent-games list. Stop the server.

- [ ] **Step 5: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/templates/analysis/_dash_workers.html services/app/static/css/main.css
git commit -m "feat(dashboard): redesigned worker card — LIVE badge, per-engine rows, progress bar, tooltips (#128)"
```

---

## Task 9: Full verification + acceptance-criteria sign-off

**Files:** none (verification only)

- [ ] **Step 1: Run the full affected test suites**

```bash
cd /Users/christopherwebster/Projects/wood_league && source .venv/bin/activate
cd services/app && python -m pytest analysis/ api/ -q
cd ../local_worker && python -m pytest tests/ -q
```

Expected: all PASS. If any fail, fix before proceeding (use `superpowers:systematic-debugging`).

- [ ] **Step 2: Bandit on every edited Python file**

```bash
cd /Users/christopherwebster/Projects/wood_league
bandit -ll services/app/analysis/dashboard_helpers.py services/app/analysis/views_dashboard.py services/app/analysis/models.py services/app/api/serializers.py services/app/api/views.py services/local_worker/local_worker/worker_client/client.py services/local_worker/local_worker/loop.py
```

Expected: "No issues identified" (fix any Medium/High before sign-off).

- [ ] **Step 3: Acceptance-criteria checklist (issue #128)**

Verify each, citing the task that delivers it:
- [ ] Workers far outside the live window are not shown → Task 7 (`STALE_DROP_SECONDS` filter), test `..._drops_stale_flags_live...`
- [ ] Workers with heartbeat within 300s clearly highlighted as live, distinct from reporting → Task 1 (`_worker_live_state`) + Task 8 (`.dash-worker-card--live`, LIVE badge)
- [ ] Each card has avg time/ply, avg time/game, last 10 completed games, identity/status → Task 2/3 + Task 8 template
- [ ] Each card shows batch progress N/M as a progress bar → Tasks 4/5/6 (data) + Task 8 (`.dash-progress`)
- [ ] Dashboard continues to auto-refresh via existing HTMX polling → unchanged `#dash-workers hx-trigger="every 5s"` in `dashboard.html` (not modified)
- [ ] Metric definitions exposed as tooltips → Task 8 (`title` attrs + `cursor: help`)

- [ ] **Step 4: Run the security scan (per global CLAUDE.md / project hook)**

```bash
cd /Users/christopherwebster/Projects/wood_league && ./security-scan.sh
```

Expected: clean (or pre-existing-only findings; do not introduce new ones).

- [ ] **Step 5: Surface the release reminder**

Report to the user: *"`services/local_worker` changed — version bumped to 0.9.13. To publish to PyPI: `git tag worker-v0.9.13 && git push origin worker-v0.9.13` (after this branch merges to main)."*

- [ ] **Step 6: Finalize**

Use `superpowers:finishing-a-development-branch` to choose merge/PR. Link the PR to issue #128 (`Closes #128`).

---

## Self-Review (completed by plan author)

**Spec coverage:** All 4 requested changes + all 5 acceptance criteria map to tasks (cross-checked in Task 9 Step 3). Tooltip definitions (user addition) → Task 8. Per-engine handling (user clarification) → Task 2 (`_worker_engine_metrics` iterates lc0/stockfish; template renders one row per engine). Billable time/game = option (a) → Task 3 `_batch_billable_per_game`.

**Placeholder scan:** No TBD/TODO/"handle edge cases" — every code step shows full code; the only deferred specifics are explicit instructions to mirror existing test fixtures (`test_endpoints.py` auth, `Game` required fields), with the method to resolve them named (read existing test / `get_skeleton`).

**Type consistency:** Card dict keys produced in Task 7 (`worker_id`, `live_state`, `engine_rows`, `batch_total`, `batch_processed`, `batch_percent`, `billable_per_game`, `recent_games`, `seconds_since_seen`, `engine`, `status_message`) match exactly what Task 8's template consumes and Task 7's test asserts. Helper names (`_worker_live_state`, `_worker_engine_metrics`, `_worker_recent_games`, `_batch_billable_per_game`) consistent across Tasks 1–3, 7. Engine-row keys (`engine`, `avg_seconds_per_ply`, `avg_seconds_per_game`, `completed`) consistent Task 2 ↔ Task 8. Serializer/model field names (`batch_total`, `batch_processed`, `session_started_at`) consistent Tasks 4/5/6/7.
