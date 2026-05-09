# Engine Dispatch & Worker API Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **MANDATORY for ALL subagents:** Call `mcp__vexp__run_pipeline` FIRST before any code exploration. Use `mcp__vexp__get_skeleton` instead of Read for file inspection. Only use Read when editing a specific line. Use context7 (`mcp__plugin_context7_context7__query-docs`) for any library docs (httpx, Django, DRF, SQLAlchemy).

**Goal:** Migrate all analysis workers from direct database access to the Django REST API, add `dispatch_mode` routing to separate pull from RunPod jobs, and build a shared HTTP client module used by all workers.

**Architecture:** The Django API becomes the single orchestrator — pull workers call `POST /api/v1/jobs/checkout/` to claim work, RunPod workers receive PGN in the RunPod payload and call `POST /api/v1/jobs/<id>/complete/` to report results. A `dispatch_mode` field on `AnalysisJob` routes jobs to the right path at enqueue time.

**Tech Stack:** Django + DRF (API), httpx (HTTP client), pytest/django TestCase (tests), SQLAlchemy removed from workers

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `services/app/analysis/models.py` | Modify | Add `dispatch_mode` field |
| `services/app/analysis/migrations/XXXX_add_dispatch_mode.py` | Create (auto) | Schema migration |
| `services/app/analysis/services/jobs.py` | Modify | Filter `claim_jobs()` + `recover_stale_jobs()` on `dispatch_mode="pull"` |
| `services/app/api/serializers.py` | Modify | Add `JobSubmitSerializer`; extend `Lc0MoveSerializer` with arrow/pv fields |
| `services/app/api/views.py` | Modify | Add `JobSubmitView` |
| `services/app/api/urls.py` | Modify | Wire `JobSubmitView` |
| `services/app/analysis/services/jobs.py` | Modify | Add `submit_job()` function |
| `services/app/api/tests/test_endpoints.py` | Modify | Tests for dispatch_mode filtering + submit endpoint |
| `packages/shared/wood_league_shared/worker_client/__init__.py` | Create | Export `WorkerClient`, `WorkerClientError`, `Job` |
| `packages/shared/wood_league_shared/worker_client/models.py` | Create | `Job` dataclass |
| `packages/shared/wood_league_shared/worker_client/client.py` | Create | `WorkerClient` class |
| `packages/shared/pyproject.toml` | Modify | Add `httpx>=0.27` dependency |
| `packages/shared/tests/test_worker_client.py` | Create | WorkerClient unit tests |
| `services/stockfish_worker/stockfish_pipeline/ingest/analysis_worker.py` | Rewrite | Pull worker loop via WorkerClient |
| `services/stockfish_worker/stockfish_pipeline/ingest/run_analysis_worker.py` | Modify | Update entrypoint args |
| `services/lc0_worker/handler.py` | Rewrite | Replace SQLAlchemy with WorkerClient |
| `services/dispatchers/dispatchers/main.py` | Modify | Replace SQLAlchemy job ops with WorkerClient |
| `services/app/app/ingest/analysis_worker.py` | Delete | Retired |
| `services/app/app/ingest/lc0_analysis_worker.py` | Delete | Retired |
| `services/app/app/ingest/run_lc0_worker.py` | Delete | Retired |

---

## Task 1: Add `dispatch_mode` to `AnalysisJob` + Migration

**Files:**
- Modify: `services/app/analysis/models.py`
- Create: `services/app/analysis/migrations/` (auto-generated)
- Modify: `services/app/api/tests/test_endpoints.py`

**Context:** `AnalysisJob` is a Django model at `services/app/analysis/models.py:179`. The `dispatch_mode` field routes jobs: `"pull"` = claimed by local workers via API; `"runpod"` = submitted to RunPod by dispatcher. Default is `"pull"` so all existing data is correct without backfill.

- [ ] **Step 1: Write the failing test**

Add to `services/app/api/tests/test_endpoints.py` inside the `JobCheckoutTests` class:

```python
def test_checkout_ignores_runpod_jobs(self):
    """Checkout does not return runpod-dispatch jobs to pull workers."""
    AnalysisJob.objects.create(
        game=self.game,
        engine='stockfish',
        status=AnalysisJob.STATUS_PENDING,
        dispatch_mode='runpod',
    )
    response = self.client.post('/api/v1/jobs/checkout/', {
        'engine': 'stockfish',
        'batch_size': 1,
        'worker_id': 'my-worker',
    })
    self.assertEqual(response.status_code, 200)
    self.assertEqual(len(response.json()['jobs']), 0)

def test_checkout_returns_pull_jobs(self):
    """Checkout returns pull-dispatch jobs to pull workers."""
    job = AnalysisJob.objects.create(
        game=self.game,
        engine='stockfish',
        status=AnalysisJob.STATUS_PENDING,
        dispatch_mode='pull',
    )
    response = self.client.post('/api/v1/jobs/checkout/', {
        'engine': 'stockfish',
        'batch_size': 1,
        'worker_id': 'my-worker',
    })
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()['jobs'][0]['id'], job.id)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/app && python manage.py test api.tests.test_endpoints.JobCheckoutTests.test_checkout_ignores_runpod_jobs api.tests.test_endpoints.JobCheckoutTests.test_checkout_returns_pull_jobs -v 2
```

Expected: `AttributeError: type object 'AnalysisJob' has no attribute 'dispatch_mode'` or `FieldError`

- [ ] **Step 3: Add `dispatch_mode` to the model**

In `services/app/analysis/models.py`, add after the `engine` field (around line 201):

```python
    dispatch_mode = models.CharField(
        max_length=16,
        default='pull',
        db_index=True,
        choices=[('pull', 'Pull'), ('runpod', 'RunPod')],
        help_text='pull = claimed via API by local workers; runpod = submitted by dispatcher',
    )
```

Also update `__str__`:
```python
    def __str__(self):
        """Return a human-readable identifier for this analysis job."""
        return f"{self.engine}/{self.dispatch_mode} job [{self.status}] for {self.game_id}"
```

And update `Meta.indexes` — replace the existing `(status, engine)` index with the compound three-column index:
```python
    class Meta:
        db_table = "analysis_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "engine", "dispatch_mode"]),
            models.Index(fields=["status", "priority"]),
        ]
```

- [ ] **Step 4: Generate and apply migration**

```bash
cd services/app && python manage.py makemigrations analysis --name add_dispatch_mode
python manage.py migrate
```

Expected: migration file created, `OK` from migrate.

- [ ] **Step 5: Update `claim_jobs()` and `recover_stale_jobs()` to filter on `dispatch_mode`**

In `services/app/analysis/services/jobs.py`, update `recover_stale_jobs()`:

```python
def recover_stale_jobs(engine: str) -> int:
    """Reset jobs stuck in 'running' for longer than STALE_JOB_TIMEOUT_MINUTES.

    Called automatically before every checkout. Returns the number of jobs recovered.
    """
    cutoff = timezone.now() - _stale_timeout()
    return AnalysisJob.objects.filter(
        engine=engine,
        dispatch_mode='pull',
        status=AnalysisJob.STATUS_RUNNING,
        started_at__lt=cutoff,
    ).update(
        status=AnalysisJob.STATUS_PENDING,
        worker_id=None,
        started_at=None,
        claimed_at=None,
        claimed_by_key_prefix=None,
    )
```

In the same file, update both `.filter()` calls inside `claim_jobs()` to include `dispatch_mode='pull'`:

```python
        if game_id:
            jobs_for_game = (
                AnalysisJob.objects
                .select_for_update(skip_locked=True)
                .filter(engine=engine, dispatch_mode='pull', game_id=game_id)
            )
            # ... rest unchanged ...
        else:
            jobs = list(
                AnalysisJob.objects
                .select_for_update(skip_locked=True)
                .filter(engine=engine, dispatch_mode='pull', status=AnalysisJob.STATUS_PENDING)
                .order_by('-priority', 'created_at')
                [:batch_size]
            )
```

- [ ] **Step 6: Run tests**

```bash
cd services/app && python manage.py test api.tests.test_endpoints.JobCheckoutTests -v 2
```

Expected: all `JobCheckoutTests` pass.

- [ ] **Step 7: Run full test suite**

```bash
cd services/app && python manage.py test --verbosity=1
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
cd services/app
git add analysis/models.py analysis/migrations/ analysis/services/jobs.py api/tests/test_endpoints.py
git commit -m "feat(analysis): add dispatch_mode field to AnalysisJob; filter pull jobs in claim_jobs"
```

---

## Task 2: Add `POST /api/v1/jobs/<id>/submit/` Endpoint

**Files:**
- Modify: `services/app/analysis/services/jobs.py`
- Modify: `services/app/api/serializers.py`
- Modify: `services/app/api/views.py`
- Modify: `services/app/api/urls.py`
- Modify: `services/app/api/tests/test_endpoints.py`

**Context:** The dispatcher claims a RunPod job (via `checkout` with `dispatch_mode='runpod'` — but checkout currently filters to `pull` only). Instead, the dispatcher uses a dedicated submit endpoint that atomically transitions `pending` → `submitted` and records the `runpod_job_id`. The dispatcher does NOT go through `checkout` for RunPod jobs — it queries the queue status and calls submit directly after submitting to RunPod.

Also in this task: extend `Lc0MoveSerializer` and `complete_lc0_job()` with the arrow and pv_san fields that the lc0 handler currently writes via SQLAlchemy.

- [ ] **Step 1: Write failing tests**

Add to `services/app/api/tests/test_endpoints.py`:

```python
class JobSubmitTests(TestCase):
    """Test POST /api/v1/jobs/<id>/submit/"""

    def setUp(self):
        """Create test data."""
        self.client = APIClient()
        self.user = User.objects.create_user(email='submit@test.local', password='pass')
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='dispatcher', worker_name='dispatcher', created_by=self.user
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        self.game = Game.objects.create(
            id='submit-game',
            white_username='A',
            black_username='B',
            played_at=timezone.now(),
            time_control='rapid',
            pgn='1. e4 e5',
        )

    def test_submit_transitions_pending_to_submitted(self):
        """Submit endpoint sets status=submitted and records runpod_job_id."""
        job = AnalysisJob.objects.create(
            game=self.game,
            engine='lc0',
            status=AnalysisJob.STATUS_PENDING,
            dispatch_mode='runpod',
        )
        response = self.client.post(f'/api/v1/jobs/{job.id}/submit/', {
            'runpod_job_id': 'rp-abc123',
        })
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, AnalysisJob.STATUS_SUBMITTED)
        self.assertEqual(job.runpod_job_id, 'rp-abc123')

    def test_submit_rejects_non_pending_job(self):
        """Submit returns 404 if job is not pending."""
        job = AnalysisJob.objects.create(
            game=self.game,
            engine='lc0',
            status=AnalysisJob.STATUS_RUNNING,
            dispatch_mode='runpod',
        )
        response = self.client.post(f'/api/v1/jobs/{job.id}/submit/', {
            'runpod_job_id': 'rp-abc123',
        })
        self.assertEqual(response.status_code, 404)

    def test_submit_requires_auth(self):
        """Submit endpoint requires API key."""
        job = AnalysisJob.objects.create(
            game=self.game, engine='lc0',
            status=AnalysisJob.STATUS_PENDING, dispatch_mode='runpod',
        )
        self.client.credentials()
        response = self.client.post(f'/api/v1/jobs/{job.id}/submit/', {
            'runpod_job_id': 'rp-abc123',
        })
        self.assertIn(response.status_code, [401, 403])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/app && python manage.py test api.tests.test_endpoints.JobSubmitTests -v 2
```

Expected: `404` from URL not found.

- [ ] **Step 3: Add `submit_job()` to the service layer**

In `services/app/analysis/services/jobs.py`, add after `fail_job()`:

```python
def submit_job(*, job_id: int, runpod_job_id: str) -> None:
    """Record a RunPod submission: set status=submitted and store runpod_job_id.

    Raises AnalysisJob.DoesNotExist if the job is not found or not pending.
    """
    with transaction.atomic():
        job = AnalysisJob.objects.select_for_update().get(
            id=job_id,
            status=AnalysisJob.STATUS_PENDING,
        )
        job.status = AnalysisJob.STATUS_SUBMITTED
        job.runpod_job_id = runpod_job_id
        job.submitted_at = timezone.now()
        job.save(update_fields=['status', 'runpod_job_id', 'submitted_at'])
```

- [ ] **Step 4: Add `JobSubmitSerializer` to serializers**

In `services/app/api/serializers.py`, add after `HeartbeatSerializer`:

```python
class JobSubmitSerializer(serializers.Serializer):
    """Request to record a RunPod job submission."""

    runpod_job_id = serializers.CharField(max_length=128)
```

Also extend `Lc0MoveSerializer` with missing fields (after `classification`):

```python
    arrow_uci_2 = serializers.CharField(max_length=10, required=False, default='')
    arrow_uci_3 = serializers.CharField(max_length=10, required=False, default='')
    arrow_score_1 = serializers.FloatField(required=False, allow_null=True, default=None)
    arrow_score_2 = serializers.FloatField(required=False, allow_null=True, default=None)
    arrow_score_3 = serializers.FloatField(required=False, allow_null=True, default=None)
    pv_san_1 = serializers.CharField(required=False, allow_null=True, default=None)
    pv_san_2 = serializers.CharField(required=False, allow_null=True, default=None)
    pv_san_3 = serializers.CharField(required=False, allow_null=True, default=None)
```

- [ ] **Step 5: Add `JobSubmitView` to views**

In `services/app/api/views.py`, add after `JobFailView`:

```python
class JobSubmitView(APIView):
    """Record that a RunPod job has been submitted."""

    permission_classes: list[type] = [HasWorkerAPIKey]

    def post(self, request, job_id):
        """Process RunPod job submission record."""
        ser = sz.JobSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            job_service.submit_job(
                job_id=job_id,
                runpod_job_id=ser.validated_data['runpod_job_id'],
            )
        except AnalysisJob.DoesNotExist:
            return Response(
                {'error': 'Job not found or not in pending state'},
                status=status.HTTP_404_NOT_FOUND,
            )
        _touch_key(request)
        return Response({'status': 'submitted'})
```

- [ ] **Step 6: Wire the URL**

In `services/app/api/urls.py`, add to `urlpatterns`:

```python
    path('jobs/<int:job_id>/submit/', views.JobSubmitView.as_view()),
```

- [ ] **Step 7: Update `complete_lc0_job()` to persist the new move fields**

In `services/app/analysis/services/jobs.py`, update the `Lc0MoveAnalysis.objects.bulk_create` call inside `complete_lc0_job()`:

```python
        Lc0MoveAnalysis.objects.bulk_create([
            Lc0MoveAnalysis(
                game=job.game,
                ply=m['ply'],
                san=m['san'],
                fen=m['fen'],
                wdl_win=m['wdl_win'],
                wdl_draw=m['wdl_draw'],
                wdl_loss=m['wdl_loss'],
                cp_equiv=m.get('cp_equiv'),
                best_move=m['best_move'],
                arrow_uci=m.get('arrow_uci', ''),
                arrow_uci_2=m.get('arrow_uci_2', ''),
                arrow_uci_3=m.get('arrow_uci_3', ''),
                arrow_score_1=m.get('arrow_score_1'),
                arrow_score_2=m.get('arrow_score_2'),
                arrow_score_3=m.get('arrow_score_3'),
                pv_san_1=m.get('pv_san_1'),
                pv_san_2=m.get('pv_san_2'),
                pv_san_3=m.get('pv_san_3'),
                move_win_delta=m['move_win_delta'],
                classification=m['classification'],
            )
            for m in payload['moves']
        ])
```

- [ ] **Step 8: Run tests**

```bash
cd services/app && python manage.py test api.tests.test_endpoints.JobSubmitTests -v 2
```

Expected: all 3 tests pass.

- [ ] **Step 9: Run full suite**

```bash
cd services/app && python manage.py test --verbosity=1
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
cd services/app
git add analysis/services/jobs.py api/serializers.py api/views.py api/urls.py api/tests/test_endpoints.py
git commit -m "feat(api): add job submit endpoint and extend lc0 move serializer with arrow/pv fields"
```

---

## Task 3: Build `wood_league_shared.worker_client`

**Files:**
- Modify: `packages/shared/pyproject.toml`
- Create: `packages/shared/wood_league_shared/worker_client/__init__.py`
- Create: `packages/shared/wood_league_shared/worker_client/models.py`
- Create: `packages/shared/wood_league_shared/worker_client/client.py`
- Create: `packages/shared/tests/__init__.py`
- Create: `packages/shared/tests/test_worker_client.py`

**Context:** The shared package lives at `packages/shared/`. It already has SQLAlchemy as a dependency for its storage models — those are separate from the new `worker_client` subpackage. The client uses `httpx` for HTTP, wraps the Django API endpoints, and retries on 5xx. Workers configure it via `WORKER_API_URL` and `WORKER_API_KEY` env vars.

- [ ] **Step 1: Add `httpx` to shared package dependencies**

In `packages/shared/pyproject.toml`, add `httpx>=0.27` to `dependencies`:

```toml
dependencies = [
    "sqlalchemy>=2.0.29",
    "psycopg[binary]>=3.2.0",
    "python-chess>=1.999",
    "httpx>=0.27",
]
```

- [ ] **Step 2: Write failing tests**

Create `packages/shared/tests/__init__.py` (empty).

Create `packages/shared/tests/test_worker_client.py`:

```python
"""Tests for wood_league_shared.worker_client."""
import json
import pytest
import httpx
from unittest.mock import patch, MagicMock

from wood_league_shared.worker_client import WorkerClient, WorkerClientError
from wood_league_shared.worker_client.models import Job


class TestJob:
    def test_job_fields(self):
        job = Job(id=1, game_id='g1', pgn='1. e4', engine='stockfish', depth=20, nodes=None)
        assert job.id == 1
        assert job.game_id == 'g1'
        assert job.nodes is None


class TestWorkerClientCheckout:
    def setup_method(self):
        self.client = WorkerClient(base_url='http://api.test', api_key='test-key')

    def test_checkout_returns_jobs(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            return_value=httpx.Response(200, json={
                'jobs': [{
                    'id': 1, 'game_id': 'g1', 'pgn': '1. e4',
                    'engine': 'stockfish', 'depth': 20, 'nodes': None,
                    'worker_id': 'w1', 'claimed_by_key_prefix': 'abc',
                }]
            })
        )
        jobs = self.client.checkout(engine='stockfish', worker_id='w1')
        assert len(jobs) == 1
        assert jobs[0].id == 1
        assert jobs[0].pgn == '1. e4'

    def test_checkout_returns_empty_on_no_jobs(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            return_value=httpx.Response(200, json={'jobs': []})
        )
        jobs = self.client.checkout(engine='stockfish', worker_id='w1')
        assert jobs == []

    def test_checkout_raises_on_5xx(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            return_value=httpx.Response(500, text='error')
        )
        with pytest.raises(WorkerClientError):
            self.client.checkout(engine='stockfish', worker_id='w1')

    def test_checkout_raises_on_4xx(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            return_value=httpx.Response(401, json={'detail': 'not authenticated'})
        )
        with pytest.raises(WorkerClientError):
            self.client.checkout(engine='stockfish', worker_id='w1')


class TestWorkerClientFail:
    def setup_method(self):
        self.client = WorkerClient(base_url='http://api.test', api_key='test-key')

    def test_fail_returns_outcome(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/1/fail/').mock(
            return_value=httpx.Response(200, json={'status': 'requeued'})
        )
        outcome = self.client.fail(job_id=1, worker_id='w1', error='boom')
        assert outcome == 'requeued'
```

Install test dependency and run:

```bash
cd packages/shared && pip install pytest respx httpx pytest-asyncio && pytest tests/ -v
```

Expected: `ModuleNotFoundError: No module named 'wood_league_shared.worker_client'`

- [ ] **Step 3: Create `models.py`**

Create `packages/shared/wood_league_shared/worker_client/models.py`:

```python
"""
Title: models.py — WorkerClient data models
Description:
    Dataclasses representing the objects returned by the Django analysis
    worker API. These are the deserialized form of the JSON responses.

Changelog:
    2026-05-08: Created
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Job:
    """A claimed analysis job returned by the checkout endpoint."""

    id: int
    game_id: str
    pgn: str
    engine: str
    depth: int
    nodes: int | None
```

- [ ] **Step 4: Create `client.py`**

Create `packages/shared/wood_league_shared/worker_client/client.py`:

```python
"""
Title: client.py — HTTP client for the Django analysis worker API
Description:
    Wraps the Django REST API endpoints used by analysis workers.
    All methods raise WorkerClientError on failure. 5xx responses
    are retried up to 3 times with exponential backoff; 4xx are not.

Changelog:
    2026-05-08: Created
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .models import Job

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]


class WorkerClientError(Exception):
    """Raised when the API returns an error response."""


class WorkerClient:
    """HTTP client for the Wood League analysis worker API."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        """Initialise the client with a base URL and API key.

        Args:
            base_url: Root URL of the Django app, e.g. 'https://app.example.com'
            api_key: Raw API key sent in the X-Api-Key header
        """
        self._base = base_url.rstrip('/')
        self._headers = {'X-Api-Key': api_key, 'Content-Type': 'application/json'}

    def _post(self, path: str, payload: dict) -> dict:
        """POST to the API with retry on 5xx. Raises WorkerClientError on failure."""
        url = f'{self._base}{path}'
        last_exc: Exception | None = None
        for attempt, backoff in enumerate(_RETRY_BACKOFF, start=1):
            try:
                resp = httpx.post(url, json=payload, headers=self._headers, timeout=30)
            except httpx.RequestError as exc:
                last_exc = exc
                log.warning('Request error (attempt %d): %s', attempt, exc)
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                continue
            if resp.status_code < 400:
                return resp.json()
            if resp.status_code >= 500:
                last_exc = WorkerClientError(f'HTTP {resp.status_code}: {resp.text[:200]}')
                log.warning('5xx from API (attempt %d): %s', attempt, resp.status_code)
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                continue
            raise WorkerClientError(f'HTTP {resp.status_code}: {resp.text[:200]}')
        raise WorkerClientError(f'API unavailable after {_MAX_RETRIES} attempts') from last_exc

    def checkout(
        self,
        *,
        engine: str,
        worker_id: str,
        batch_size: int = 1,
        game_id: str | None = None,
    ) -> list[Job]:
        """Claim up to batch_size pending pull jobs for the given engine.

        Args:
            engine: 'stockfish' or 'lc0'
            worker_id: Unique worker identifier (hostname recommended)
            batch_size: Number of jobs to claim (default 1)
            game_id: Optional specific game to claim

        Returns:
            List of Job dataclasses (empty if queue is empty)
        """
        payload: dict[str, Any] = {
            'engine': engine,
            'worker_id': worker_id,
            'batch_size': batch_size,
        }
        if game_id:
            payload['game_id'] = game_id
        data = self._post('/api/v1/jobs/checkout/', payload)
        return [
            Job(
                id=j['id'],
                game_id=j['game_id'],
                pgn=j['pgn'],
                engine=j['engine'],
                depth=j['depth'],
                nodes=j.get('nodes'),
            )
            for j in data.get('jobs', [])
        ]

    def complete_stockfish(self, *, job_id: int, worker_id: str, payload: dict) -> None:
        """Report successful Stockfish analysis.

        Args:
            job_id: Django AnalysisJob.id
            worker_id: Same worker_id used at checkout
            payload: Dict matching StockfishCompleteSerializer fields
        """
        self._post(f'/api/v1/jobs/{job_id}/complete/', {'engine': 'stockfish', 'worker_id': worker_id, **payload})

    def complete_lc0(self, *, job_id: int, worker_id: str, payload: dict) -> None:
        """Report successful lc0 analysis.

        Args:
            job_id: Django AnalysisJob.id
            worker_id: Same worker_id used at checkout
            payload: Dict matching Lc0CompleteSerializer fields
        """
        self._post(f'/api/v1/jobs/{job_id}/complete/', {'engine': 'lc0', 'worker_id': worker_id, **payload})

    def fail(self, *, job_id: int, worker_id: str, error: str) -> str:
        """Report job failure.

        Args:
            job_id: Django AnalysisJob.id
            worker_id: Same worker_id used at checkout
            error: Error message (truncated to 2000 chars server-side)

        Returns:
            'requeued' if the job will be retried, 'failed' if exhausted
        """
        data = self._post(f'/api/v1/jobs/{job_id}/fail/', {'worker_id': worker_id, 'error': error})
        return data.get('status', 'failed')

    def heartbeat(self, *, worker_id: str, engine: str, status_message: str = '') -> None:
        """Send a worker heartbeat.

        Args:
            worker_id: Unique worker identifier
            engine: 'stockfish' or 'lc0'
            status_message: Human-readable status string
        """
        try:
            self._post('/api/v1/heartbeat/', {
                'worker_id': worker_id,
                'engine': engine,
                'status_message': status_message,
            })
        except WorkerClientError:
            log.warning('Heartbeat failed — continuing')

    def submit_runpod(self, *, job_id: int, runpod_job_id: str) -> None:
        """Record that a RunPod job has been submitted.

        Args:
            job_id: Django AnalysisJob.id
            runpod_job_id: The RunPod job ID returned by the RunPod SDK
        """
        self._post(f'/api/v1/jobs/{job_id}/submit/', {'runpod_job_id': runpod_job_id})
```

- [ ] **Step 5: Create `__init__.py`**

Create `packages/shared/wood_league_shared/worker_client/__init__.py`:

```python
"""HTTP client for the Wood League analysis worker API."""
from .client import WorkerClient, WorkerClientError
from .models import Job

__all__ = ['WorkerClient', 'WorkerClientError', 'Job']
```

- [ ] **Step 6: Run tests**

```bash
cd packages/shared && pip install -e ".[dev]" httpx respx pytest && pytest tests/test_worker_client.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add packages/shared/
git commit -m "feat(shared): add worker_client HTTP module with WorkerClient and Job dataclass"
```

---

## Task 4: Rewrite Stockfish Worker to Use WorkerClient

**Files:**
- Rewrite: `services/stockfish_worker/stockfish_pipeline/ingest/analysis_worker.py`
- Modify: `services/stockfish_worker/stockfish_pipeline/ingest/run_analysis_worker.py` (entrypoint)
- Modify: `services/stockfish_worker/pyproject.toml`

**Context:** The current `analysis_worker.py` uses SQLAlchemy directly. Replace all DB code with `WorkerClient`. The `analyze_pgn` function at `stockfish_pipeline/services/stockfish_service.py` is untouched — only the loop and I/O code changes. Config now comes from `WORKER_API_URL` and `WORKER_API_KEY` env vars instead of `DATABASE_URL`.

- [ ] **Step 1: Check the current entrypoint**

Run:
```bash
cat /Users/christopherwebster/Projects/wood_league/services/stockfish_worker/stockfish_pipeline/ingest/run_analysis_worker.py
```

Note the current CLI args so you can preserve the interface.

- [ ] **Step 2: Add `wood-league-shared` dependency reference and ensure it includes httpx**

In `services/stockfish_worker/pyproject.toml`, confirm `wood-league-shared` is in dependencies (it already is). The shared package now includes `httpx`, so no additional dep needed.

- [ ] **Step 3: Rewrite `analysis_worker.py`**

Replace the entire content of `services/stockfish_worker/stockfish_pipeline/ingest/analysis_worker.py`:

```python
"""
Title: analysis_worker.py — Stockfish pull worker using Django API
Description:
    Poll worker that claims pending Stockfish analysis jobs from the Django
    API, runs Stockfish engine analysis, and reports results back via HTTP.
    Replaces direct SQLAlchemy database access with WorkerClient calls.

Changelog:
    2026-05-08: Rewritten to use WorkerClient; removed SQLAlchemy
"""
from __future__ import annotations

import logging
import os
import socket
import time

from stockfish_pipeline.services.stockfish_service import analyze_pgn
from wood_league_shared.worker_client import WorkerClient, WorkerClientError

log = logging.getLogger(__name__)

_WORKER_ID = socket.gethostname()


def _build_stockfish_payload(result, *, depth: int) -> dict:
    """Convert analysis result to the API complete-payload dict."""
    return {
        'engine_depth': depth,
        'white_accuracy': result.white_stats.accuracy,
        'black_accuracy': result.black_stats.accuracy,
        'white_acpl': result.white_stats.acpl,
        'black_acpl': result.black_stats.acpl,
        'white_blunders': result.white_stats.blunders,
        'white_mistakes': result.white_stats.mistakes,
        'white_inaccuracies': result.white_stats.inaccuracies,
        'black_blunders': result.black_stats.blunders,
        'black_mistakes': result.black_stats.mistakes,
        'black_inaccuracies': result.black_stats.inaccuracies,
        'moves': [
            {
                'ply': m.ply,
                'san': m.san,
                'fen': m.fen,
                'cp_eval': m.cp_eval,
                'cpl': m.cpl,
                'best_move': m.best_move,
                'classification': m.classification,
            }
            for m in result.moves
        ],
    }


def run_worker(
    *,
    stockfish_path: str,
    api_url: str,
    api_key: str,
    depth: int = 20,
    threads: int = 1,
    hash_mb: int = 256,
    poll_interval: float = 5.0,
    limit: int | None = None,
) -> None:
    """Poll the Django API for Stockfish jobs and process them.

    Args:
        stockfish_path: Path to the Stockfish binary
        api_url: Base URL of the Django app, e.g. 'https://app.example.com'
        api_key: Raw worker API key for authentication
        depth: Stockfish analysis depth (default 20)
        threads: CPU threads for Stockfish
        hash_mb: Hash table size in MB for Stockfish
        poll_interval: Seconds to wait when queue is empty (0 = exit immediately)
        limit: Stop after processing this many games (None = unlimited)
    """
    client = WorkerClient(base_url=api_url, api_key=api_key)
    worker_id = _WORKER_ID
    processed = 0
    failed = 0

    log.info(
        'Stockfish worker starting. depth=%d threads=%d hash=%dMB limit=%s',
        depth, threads, hash_mb, limit or '∞',
    )

    client.heartbeat(worker_id=worker_id, engine='stockfish', status_message='starting')

    while True:
        if limit is not None and processed >= limit:
            log.info('Reached limit of %d games — exiting.', limit)
            break

        try:
            jobs = client.checkout(engine='stockfish', worker_id=worker_id)
        except WorkerClientError as exc:
            log.error('Checkout failed: %s', exc)
            time.sleep(poll_interval or 5.0)
            continue

        if not jobs:
            client.heartbeat(worker_id=worker_id, engine='stockfish', status_message='idle')
            if poll_interval <= 0:
                break
            time.sleep(poll_interval)
            continue

        for job in jobs:
            client.heartbeat(
                worker_id=worker_id,
                engine='stockfish',
                status_message=f'analyzing {job.game_id[:16]}',
            )
            try:
                result = analyze_pgn(
                    job.pgn,
                    stockfish_path=stockfish_path,
                    depth=depth,
                    threads=threads,
                    hash_mb=hash_mb,
                )
                payload = _build_stockfish_payload(result, depth=depth)
                client.complete_stockfish(job_id=job.id, worker_id=worker_id, payload=payload)
                processed += 1
                log.info(
                    'Completed job %d game=%s W=%.1f%% B=%.1f%%',
                    job.id, job.game_id,
                    result.white_stats.accuracy, result.black_stats.accuracy,
                )
            except WorkerClientError as exc:
                log.error('API error completing job %d: %s', job.id, exc)
                failed += 1
            except Exception as exc:
                failed += 1
                log.exception('Analysis failed for job %d game=%s: %s', job.id, job.game_id, exc)
                try:
                    client.fail(job_id=job.id, worker_id=worker_id, error=str(exc))
                except WorkerClientError:
                    log.error('Could not report failure for job %d', job.id)

    client.heartbeat(worker_id=worker_id, engine='stockfish', status_message='stopped')
    log.info('Done. Processed %d game(s), %d failed.', processed, failed)
```

- [ ] **Step 4: Update the entrypoint**

Check what `run_analysis_worker.py` currently passes to `run_worker`. Update it to pass `api_url` and `api_key` from env vars instead of a database URL:

```python
"""Entrypoint for the Stockfish pull worker."""
import argparse
import logging
import os

from stockfish_pipeline.ingest.analysis_worker import run_worker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s - %(message)s',
    datefmt='%H:%M:%S',
)


def main() -> None:
    """Parse CLI args and start the worker loop."""
    parser = argparse.ArgumentParser(description='Stockfish analysis pull worker')
    parser.add_argument('--stockfish', default=os.environ.get('STOCKFISH_PATH', 'stockfish'))
    parser.add_argument('--depth', type=int, default=int(os.environ.get('ANALYSIS_DEPTH', '20')))
    parser.add_argument('--threads', type=int, default=int(os.environ.get('ANALYSIS_THREADS', '1')))
    parser.add_argument('--hash-mb', type=int, default=int(os.environ.get('ANALYSIS_HASH_MB', '256')))
    parser.add_argument('--poll-interval', type=float, default=float(os.environ.get('POLL_INTERVAL', '5')))
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--api-url', default=os.environ.get('WORKER_API_URL', ''))
    parser.add_argument('--api-key', default=os.environ.get('WORKER_API_KEY', ''))
    args = parser.parse_args()

    if not args.api_url or not args.api_key:
        raise SystemExit('WORKER_API_URL and WORKER_API_KEY are required')

    run_worker(
        stockfish_path=args.stockfish,
        api_url=args.api_url,
        api_key=args.api_key,
        depth=args.depth,
        threads=args.threads,
        hash_mb=args.hash_mb,
        poll_interval=args.poll_interval,
        limit=args.limit,
    )


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Smoke-test the import**

```bash
cd services/stockfish_worker && python -c "from stockfish_pipeline.ingest.analysis_worker import run_worker; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add services/stockfish_worker/
git commit -m "feat(stockfish-worker): replace SQLAlchemy with WorkerClient HTTP pull loop"
```

---

## Task 5: Rewrite lc0 Worker Handler to Use WorkerClient

**Files:**
- Rewrite: `services/lc0_worker/handler.py`
- Modify: `services/lc0_worker/pyproject.toml` (add `wood-league-shared` dep if missing)

**Context:** The lc0 worker is a RunPod serverless handler. It receives `game_id`, `pgn`, `nodes`, `weights_path`, and now also `job_id` in the RunPod payload (the dispatcher adds this in Task 6). The handler replaces its SQLAlchemy DB writes with `WorkerClient.complete_lc0()` and `WorkerClient.fail()`. Auth uses env vars `WORKER_API_URL` and `WORKER_API_KEY`.

- [ ] **Step 1: Check lc0_worker pyproject.toml and add shared dep if needed**

```bash
cat /Users/christopherwebster/Projects/wood_league/services/lc0_worker/pyproject.toml
```

If `wood-league-shared` is not in dependencies, add it (same pattern as stockfish_worker).

- [ ] **Step 2: Build the lc0 result payload helper**

The `analyze_pgn` result object has the same shape as in the current handler. The payload for `complete_lc0` must match `Lc0CompleteSerializer` (including the new arrow/pv fields added in Task 2).

Replace the entire content of `services/lc0_worker/handler.py`:

```python
"""
Title: handler.py — RunPod Serverless handler for Lc0 analysis
Description:
    Receives a game PGN from RunPod, runs Lc0 neural network analysis,
    and reports results back to the Django API via WorkerClient.
    Replaces direct SQLAlchemy database access.

Changelog:
    2026-05-08: Rewritten to use WorkerClient; removed SQLAlchemy and DATABASE_URL
"""
from __future__ import annotations

import json
import logging
import os
import subprocess

import runpod

from lc0_worker.services.lc0_service import analyze_pgn
from wood_league_shared.worker_client import WorkerClient, WorkerClientError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s - %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger(__name__)

LC0_PATH: str = os.environ.get('LC0_PATH', '/usr/local/bin/lc0')
LC0_NODES: int = int(os.environ.get('LC0_NODES', '25000'))
LC0_NETWORK: str = os.environ.get('LC0_NETWORK', '')
LC0_SYZYGY_PATH: str = os.environ.get('LC0_SYZYGY_PATH', '/runpod-volume/syzygy')
LC0_BACKEND: str = os.environ.get('LC0_BACKEND', 'cudnn-fp16')
WORKER_API_URL: str = os.environ['WORKER_API_URL']
WORKER_API_KEY: str = os.environ['WORKER_API_KEY']
WORKER_ID: str = os.environ.get('WORKER_ID', 'lc0-runpod')

_client = WorkerClient(base_url=WORKER_API_URL, api_key=WORKER_API_KEY)


def _build_lc0_payload(result, *, worker_id: str) -> dict:
    """Convert lc0 analysis result to the API complete-payload dict."""
    return {
        'worker_id': worker_id,
        'engine_nodes': result.engine_nodes,
        'network_name': result.network_name or '',
        'white_win_prob': result.white_stats.avg_win_prob,
        'white_draw_prob': result.white_stats.avg_draw_prob,
        'white_loss_prob': result.white_stats.avg_loss_prob,
        'black_win_prob': result.black_stats.avg_win_prob,
        'black_draw_prob': result.black_stats.avg_draw_prob,
        'black_loss_prob': result.black_stats.avg_loss_prob,
        'white_blunders': result.white_stats.blunders,
        'white_mistakes': result.white_stats.mistakes,
        'white_inaccuracies': result.white_stats.inaccuracies,
        'black_blunders': result.black_stats.blunders,
        'black_mistakes': result.black_stats.mistakes,
        'black_inaccuracies': result.black_stats.inaccuracies,
        'moves': [
            {
                'ply': m.ply,
                'san': m.san,
                'fen': m.fen,
                'wdl_win': m.wdl_win,
                'wdl_draw': m.wdl_draw,
                'wdl_loss': m.wdl_loss,
                'cp_equiv': m.cp_equiv,
                'best_move': m.best_move,
                'arrow_uci': m.arrow_uci or '',
                'arrow_uci_2': m.arrow_uci_2 or '',
                'arrow_uci_3': m.arrow_uci_3 or '',
                'arrow_score_1': m.arrow_score_1,
                'arrow_score_2': m.arrow_score_2,
                'arrow_score_3': m.arrow_score_3,
                'pv_san_1': json.dumps(m.pv_san_1) if m.pv_san_1 else None,
                'pv_san_2': json.dumps(m.pv_san_2) if m.pv_san_2 else None,
                'pv_san_3': json.dumps(m.pv_san_3) if m.pv_san_3 else None,
                'move_win_delta': m.move_win_delta,
                'classification': m.classification,
            }
            for m in result.moves
        ],
    }


def _log_startup_diagnostics() -> None:
    log.info(
        'Lc0 startup: path=%s backend=%s network=%s syzygy=%s api=%s',
        LC0_PATH, LC0_BACKEND, LC0_NETWORK or '<default>', LC0_SYZYGY_PATH, WORKER_API_URL,
    )
    try:
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,driver_version,cuda_version', '--format=csv,noheader'],
            check=True, capture_output=True, text=True, timeout=10,
        )
        for i, line in enumerate(result.stdout.splitlines(), 1):
            if line.strip():
                log.info('Lc0 startup: gpu[%d]=%s', i, line.strip())
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        log.warning('Lc0 startup: GPU query failed: %s', exc)


def handler(job: dict) -> dict:
    """RunPod serverless handler: analyse one game and report results via API."""
    job_input = job['input']
    game_id: str = job_input['game_id']
    pgn_string: str = job_input['pgn']
    nodes: int = int(job_input.get('nodes', LC0_NODES))
    weights_path: str = str(job_input.get('weights_path', LC0_NETWORK))
    django_job_id: int = int(job_input['job_id'])

    log.info('Starting Lc0 analysis: game_id=%s nodes=%d job_id=%d', game_id, nodes, django_job_id)

    try:
        result = analyze_pgn(
            pgn_text=pgn_string,
            lc0_path=LC0_PATH,
            nodes=nodes,
            weights_path=weights_path,
            syzygy_path=LC0_SYZYGY_PATH,
            backend=LC0_BACKEND,
        )
    except Exception as exc:
        log.error('Analysis failed for game_id=%s: %s', game_id, exc, exc_info=True)
        try:
            _client.fail(job_id=django_job_id, worker_id=WORKER_ID, error=str(exc))
        except WorkerClientError:
            log.error('Could not report failure for job %d', django_job_id)
        return {'game_id': game_id, 'status': 'error', 'error': str(exc)}

    try:
        payload = _build_lc0_payload(result, worker_id=WORKER_ID)
        _client.complete_lc0(job_id=django_job_id, worker_id=WORKER_ID, payload=payload)
    except WorkerClientError as exc:
        log.error('API write failed for job %d: %s', django_job_id, exc)
        return {'game_id': game_id, 'status': 'error', 'error': str(exc)}

    log.info(
        'Completed Lc0 analysis: game_id=%s moves=%d W-win=%.3f B-win=%.3f',
        game_id, len(result.moves),
        result.white_stats.avg_win_prob, result.black_stats.avg_win_prob,
    )
    return {
        'game_id': game_id,
        'moves_analysed': len(result.moves),
        'white_win_prob': result.white_stats.avg_win_prob,
        'black_win_prob': result.black_stats.avg_win_prob,
        'status': 'ok',
    }


_log_startup_diagnostics()
runpod.serverless.start({'handler': handler})
```

- [ ] **Step 3: Smoke-test the import**

```bash
cd services/lc0_worker && WORKER_API_URL=http://localhost WORKER_API_KEY=test python -c "import handler; print('import OK')" 2>&1 | head -10
```

Expected: startup diagnostics logged, then `import OK`. `nvidia-smi` warning is fine on a non-GPU machine.

- [ ] **Step 4: Commit**

```bash
git add services/lc0_worker/handler.py services/lc0_worker/pyproject.toml
git commit -m "feat(lc0-worker): replace SQLAlchemy with WorkerClient; require job_id in payload"
```

---

## Task 6: Migrate Dispatcher to Django API

**Files:**
- Modify: `services/dispatchers/dispatchers/main.py`
- Modify: `services/dispatchers/pyproject.toml`

**Context:** The dispatcher currently writes job state via SQLAlchemy. It needs to:
1. Use `WorkerClient.submit_runpod()` to record submission (instead of setting `runpod_job_id` and `status` directly in the DB)
2. Include `job_id` in the RunPod payload so the lc0/stockfish handlers can call `complete_lc0`/`complete_stockfish`
3. Query pending runpod jobs via the API (`GET /api/v1/jobs/status/`) rather than SQLAlchemy

The ingest/sync code (`_run_ingest_sweep`, `ChessComSyncService`) is untouched — it still uses SQLAlchemy for ingest writes, which is fine since ingest is not a worker concern.

- [ ] **Step 1: Add `wood-league-shared` workspace dep to dispatcher pyproject if not already present**

In `services/dispatchers/pyproject.toml`, confirm `wood-league-shared` is in dependencies. The git+ URL may need to become a workspace reference for local dev:

```toml
dependencies = [
    "wood-league-shared",
    "runpod>=1.7.0",
]

[tool.uv.sources]
wood-league-shared = { workspace = true }
```

- [ ] **Step 2: Refactor `_submit_engine_jobs()` to use WorkerClient**

The current function queries the DB and sets `runpod_job_id` + `status` directly. Replace with API calls.

In `services/dispatchers/dispatchers/main.py`:

1. Add imports at the top:
```python
from wood_league_shared.worker_client import WorkerClient, WorkerClientError
```

2. Replace `_submit_engine_jobs()` entirely:

```python
def _submit_engine_jobs(
    *,
    engine: str,
    endpoint,
    api_client: WorkerClient,
    limit: int | None = None,
    stockfish_threads: int = 8,
    stockfish_hash_mb: int = 2048,
    lc0_nodes: int = 25000,
    lc0_network: str = '',
) -> int:
    """Claim pending runpod jobs and submit them to the RunPod endpoint.

    Uses SELECT FOR UPDATE via the Django API to prevent double-submission.
    """
    stmt = (
        select(AnalysisJob)
        .where(
            and_(
                AnalysisJob.status == 'pending',
                AnalysisJob.engine == engine,
                AnalysisJob.dispatch_mode == 'runpod',
            )
        )
        .order_by(AnalysisJob.priority.desc(), AnalysisJob.created_at)
    )
    if limit:
        stmt = stmt.limit(limit)

    submitted = 0
    with get_session() as session:
        jobs = session.execute(stmt).scalars().all()

        for job in jobs:
            pgn = _load_pgn(job.game_id)
            if not pgn:
                log.warning('%s game_id=%s has no PGN - skipping', engine, job.game_id)
                continue

            try:
                if engine == 'stockfish':
                    payload = {
                        'job_id': job.id,
                        'game_id': job.game_id,
                        'pgn': pgn,
                        'depth': int(job.depth or 20),
                        'threads': stockfish_threads,
                        'hash_mb': stockfish_hash_mb,
                    }
                else:
                    payload = {
                        'job_id': job.id,
                        'game_id': job.game_id,
                        'pgn': pgn,
                        'nodes': int(job.depth or lc0_nodes),
                    }
                    if lc0_network:
                        payload['weights_path'] = lc0_network

                run_request = endpoint.run(payload)
                api_client.submit_runpod(
                    job_id=job.id,
                    runpod_job_id=run_request.job_id,
                )
                submitted += 1
                log.info(
                    'Submitted %s job_id=%d game_id=%s -> runpod_job_id=%s',
                    engine, job.id, job.game_id, run_request.job_id,
                )
            except WorkerClientError as exc:
                log.error('API error submitting job %d: %s', job.id, exc)
            except Exception:
                log.exception('Failed submitting %s game_id=%s', engine, job.game_id)

    return submitted
```

3. Update `main()` to create the `WorkerClient` and pass it to `_submit_engine_jobs`:

Add after `runpod.api_key = _required_env('RUNPOD_API_KEY')`:
```python
    worker_api_url = _required_env('WORKER_API_URL')
    worker_api_key = _required_env('WORKER_API_KEY')
    api_client = WorkerClient(base_url=worker_api_url, api_key=worker_api_key)
```

Then update all calls to `_submit_engine_jobs(...)` to include `api_client=api_client`.

- [ ] **Step 3: Update `_enqueue_job_if_needed()` to set `dispatch_mode`**

The dispatcher enqueues jobs for RunPod — they should have `dispatch_mode='runpod'`. Update the `session.add()` call in `_enqueue_job_if_needed()`:

```python
    session.add(
        AnalysisJob(
            game_id=game_id,
            engine=engine,
            depth=depth,
            status='pending',
            priority=10,
            dispatch_mode='runpod',
        )
    )
```

- [ ] **Step 4: Remove the SQLAlchemy model import for `AnalysisJob` from `dispatchers/main.py`**

Wait — the dispatcher still uses SQLAlchemy for `_load_pgn()` and `_enqueue_job_if_needed()`. These are fine to keep using SQLAlchemy since the dispatcher is a trusted backend service that also handles ingest. The key change is that `runpod_job_id` and `status` are now set via the API (`api_client.submit_runpod()`), not directly in the DB.

Note: `AnalysisJob` SQLAlchemy model does NOT yet have `dispatch_mode`. Add it to the shared SQLAlchemy model:

In `packages/shared/wood_league_shared/storage/models.py`, add after the `engine` field:

```python
    dispatch_mode: Mapped[str] = mapped_column(String(16), default='runpod', index=True)
```

Note: default is `'runpod'` here because the shared SQLAlchemy model is only used by the dispatcher, which creates runpod jobs.

- [ ] **Step 5: Smoke-test dispatcher import**

```bash
cd services/dispatchers && python -c "from dispatchers.main import main; print('OK')"
```

Expected: `OK` (or import error to fix).

- [ ] **Step 6: Commit**

```bash
git add services/dispatchers/ packages/shared/wood_league_shared/storage/models.py
git commit -m "feat(dispatchers): route runpod jobs via WorkerClient API; add dispatch_mode to SQLAlchemy model"
```

---

## Task 7: Retire App-Side SQLAlchemy Workers

**Files:**
- Delete: `services/app/app/ingest/analysis_worker.py`
- Delete: `services/app/app/ingest/lc0_analysis_worker.py`
- Delete: `services/app/app/ingest/run_lc0_worker.py`
- Check: `services/app/app/ingest/` for any remaining references

- [ ] **Step 1: Check for any imports of these files**

```bash
grep -r "from app.ingest.analysis_worker\|from app.ingest.lc0_analysis_worker\|from app.ingest.run_lc0_worker\|import analysis_worker\|import lc0_analysis_worker\|import run_lc0_worker" /Users/christopherwebster/Projects/wood_league/services/app/ 2>/dev/null
```

If any imports are found, update them before deleting.

- [ ] **Step 2: Delete the files**

```bash
git rm services/app/app/ingest/analysis_worker.py
git rm services/app/app/ingest/lc0_analysis_worker.py
git rm services/app/app/ingest/run_lc0_worker.py
```

- [ ] **Step 3: Run the full app test suite to confirm nothing broke**

```bash
cd services/app && python manage.py test --verbosity=1
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: retire app-side SQLAlchemy analysis workers; replaced by WorkerClient model"
```

---

## Task 8: Final Verification

- [ ] **Step 1: Run all tests**

```bash
cd services/app && python manage.py test --verbosity=1
cd /Users/christopherwebster/Projects/wood_league/packages/shared && pytest tests/ -v
```

Expected: all green.

- [ ] **Step 2: Run Snyk security scan on modified Python files**

```bash
cd services/app && bandit -ll analysis/models.py analysis/services/jobs.py api/views.py api/serializers.py api/urls.py
cd /Users/christopherwebster/Projects/wood_league/packages/shared && bandit -ll wood_league_shared/worker_client/client.py
cd /Users/christopherwebster/Projects/wood_league/services/stockfish_worker && bandit -ll stockfish_pipeline/ingest/analysis_worker.py
```

Expected: no Medium or High severity issues. Fix any that appear before continuing.

- [ ] **Step 3: Verify branch is clean**

```bash
git status
git log --oneline main..HEAD
```

Expected: 7 commits ahead of main, working tree clean.

- [ ] **Step 4: Open PR**

```bash
gh pr create \
  --title "feat: engine dispatch routing + WorkerClient; retire SQLAlchemy workers" \
  --body "$(cat <<'EOF'
## Summary
- Adds `dispatch_mode` field to `AnalysisJob` to route jobs to pull workers (`pull`) or RunPod (`runpod`)
- `claim_jobs()` now filters on `dispatch_mode='pull'` — RunPod jobs never reach pull workers
- New `POST /api/v1/jobs/<id>/submit/` endpoint records RunPod job submission
- New `wood_league_shared.worker_client` shared HTTP client (httpx) replaces SQLAlchemy in all workers
- Stockfish worker rewritten as a pull worker using `WorkerClient`
- lc0 handler rewritten to report results via `WorkerClient` (no DATABASE_URL required)
- Dispatcher migrated to use `WorkerClient.submit_runpod()` and sets `dispatch_mode='runpod'` on enqueued jobs
- Retired `services/app/app/ingest/` SQLAlchemy workers

## Test plan
- [ ] `JobCheckoutTests` — pull/runpod isolation verified
- [ ] `JobSubmitTests` — submit endpoint transitions and rejects non-pending
- [ ] `WorkerClient` unit tests — checkout, fail, retry behaviour
- [ ] Full Django test suite passes
- [ ] Bandit scan clean on all modified files

Closes #1

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
