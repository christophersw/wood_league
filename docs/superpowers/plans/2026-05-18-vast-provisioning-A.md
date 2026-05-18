# vast.ai Reconcile Cron Orchestrator (Sub-project A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single idempotent Django management command (`reconcile_vast_analysis`), run every 45 min by a Railway cron service, that launches a vast.ai analysis worker when a run is scheduled and reliably destroys it when its batch drains or a hard deadline passes — no GPU box can leak.

**Architecture:** Two new `analysis`-app tables (`AnalysisSchedule` = opaque run intent; `AnalysisInstance` = live truth + teardown backstop). The command does **reap-then-launch**, holds no long-lived process, and re-derives all state from the tables every tick. Drained is detected via the launched worker's `WorkerHeartbeat` going stale (no campaign field exists). vast lifecycle goes through a thin REST client mirroring `app/runpod_client.py`.

**Tech Stack:** Django, `httpx`, Postgres, Django management command, Railway cron. Spec: `docs/superpowers/specs/2026-05-18-vast-provisioning-design.md`.

---

## Conventions for every task

- **venv + test command** (run from repo root unless noted):
  ```bash
  cd /Users/christopherwebster/Projects/wood_league/services/app && \
  source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && \
  python -m pytest <test path> -v
  ```
  `conftest.py` auto-sets `DJANGO_SETTINGS_MODULE=config.settings` and loads `.env.test`. Tests use Django `TestCase` + `override_settings` + `unittest.mock.patch` (mirror `analysis/tests/test_runpod_admin.py`).
- **New test files** go in `analysis/tests/test_*.py` (the `analysis/tests/` package — NOT `analysis/tests.py`, which is dead/shadowed).
- **File headers:** every new `.py` starts with a `"""Title: … / Description: … / Changelog: …"""` block (project code standard; see existing files).
- **bandit:** after editing any `.py`, run `bandit -ll <file>` and fix Medium/High before commit (per `services/app/CLAUDE.md`).
- **Commit** after each task with the message shown.

---

## File Structure

- **Create** `services/app/analysis/services/vast_dispatch.py` — thin vast.ai REST client (search/create/destroy/list). One responsibility: talk to vast, never raise except a typed `NoVastOfferError`.
- **Create** `services/app/analysis/management/commands/reconcile_vast_analysis.py` — the reconcile command (reap-then-launch). Helpers split into module-level functions so each is independently testable.
- **Modify** `services/app/analysis/models.py` — add `AnalysisSchedule`, `AnalysisInstance`.
- **Create** `services/app/analysis/migrations/0009_analysisschedule_analysisinstance.py` — generated migration.
- **Modify** `services/app/analysis/admin.py` — register the two models.
- **Modify** `services/app/config/settings.py` — add `VAST_*` settings.
- **Modify** `services/app/app/config.py` — mirror `vast_*` pydantic fields (consistency with `runpod_*`).
- **Create** tests: `test_vast_dispatch.py`, `test_models_vast.py`, `test_admin_vast.py`, `test_reconcile_vast_gating.py`, `test_reconcile_vast_reap.py`, `test_reconcile_vast_launch.py`, `test_reconcile_vast_integration.py`.
- **Modify** `docs/superpowers/plans/` deployment note (Task 9) + `services/app/CLAUDE.md`? No — deployment note lives in the spec/plan only.

---

### Task 1: VAST_* settings

**Files:**
- Modify: `services/app/config/settings.py` (after the RUNPOD block, ~line 233)
- Modify: `services/app/app/config.py` (Settings class + changelog)
- Test: `services/app/analysis/tests/test_reconcile_vast_gating.py` (settings-default assertions only in this task)

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_reconcile_vast_gating.py`:

```python
"""
Title: test_reconcile_vast_gating.py — VAST_* settings + command gating
Description:
    Task 1 covers settings defaults. Later tasks add command-gating tests
    to this file (VAST_ENABLED False → no-op).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from django.conf import settings
from django.test import TestCase


class VastSettingsDefaultsTests(TestCase):
    """VAST_* settings exist with safe defaults."""

    def test_vast_enabled_defaults_false(self):
        """VAST_ENABLED must default False (cost-safe; invisible when off)."""
        self.assertFalse(settings.VAST_ENABLED)

    def test_vast_numeric_defaults(self):
        """Numeric guards have the spec defaults."""
        self.assertEqual(settings.VAST_MAX_JOBS, 100)
        self.assertGreater(settings.VAST_HARD_DEADLINE_HOURS, 0)
        self.assertGreater(settings.VAST_LAUNCH_GRACE_MINUTES, 0)
        self.assertGreater(settings.VAST_WORKER_STALE_MINUTES, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_reconcile_vast_gating.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'VAST_ENABLED'`.

- [ ] **Step 3: Add settings**

In `services/app/config/settings.py`, immediately after the line `RUNPOD_ENABLED = os.environ.get("RUNPOD_ENABLED", "").lower() in {"1", "true", "yes", "on"}`:

```python
# vast.ai cron-provisioning (issue #155 Sub-project A). VAST_ENABLED gates
# the reconcile command exactly like RUNPOD_ENABLED gates the start-pod
# endpoint: when off, the command no-ops. VAST_API_KEY never leaves the
# app (never placed on a rented box).
VAST_ENABLED = os.environ.get("VAST_ENABLED", "").lower() in {"1", "true", "yes", "on"}
VAST_API_KEY = os.environ.get("VAST_API_KEY", "")
VAST_TEMPLATE_HASH = os.environ.get("VAST_TEMPLATE_HASH", "")
VAST_CAMPAIGN_ID = os.environ.get("VAST_CAMPAIGN_ID", "")
VAST_OFFER_GPU_NAME = os.environ.get("VAST_OFFER_GPU_NAME", "L40S")
VAST_OFFER_MAX_DPH = float(os.environ.get("VAST_OFFER_MAX_DPH", "1.50"))
VAST_MAX_JOBS = int(os.environ.get("VAST_MAX_JOBS", "100"))
VAST_HARD_DEADLINE_HOURS = float(os.environ.get("VAST_HARD_DEADLINE_HOURS", "6"))
VAST_LAUNCH_GRACE_MINUTES = int(os.environ.get("VAST_LAUNCH_GRACE_MINUTES", "20"))
VAST_WORKER_STALE_MINUTES = int(os.environ.get("VAST_WORKER_STALE_MINUTES", "15"))
```

In `services/app/app/config.py`, add to the `Settings` class fields (after the `runpod_enabled` field) and a changelog line:

```python
    vast_enabled: bool = False
    vast_api_key: str = ""
    vast_template_hash: str = ""
    vast_campaign_id: str = ""
    vast_offer_gpu_name: str = "L40S"
    vast_offer_max_dph: float = 1.50
    vast_max_jobs: int = 100
    vast_hard_deadline_hours: float = 6.0
    vast_launch_grace_minutes: int = 20
    vast_worker_stale_minutes: int = 15
```

Add to the module docstring Changelog: `    2026-05-18: Added VAST_* settings (issue #155 Sub-project A).`

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest analysis/tests/test_reconcile_vast_gating.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/config/settings.py services/app/app/config.py services/app/analysis/tests/test_reconcile_vast_gating.py
git commit -m "feat(#155): VAST_* settings with cost-safe defaults (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: AnalysisSchedule + AnalysisInstance models

**Files:**
- Modify: `services/app/analysis/models.py` (append after `WorkerHeartbeat`)
- Create: migration `services/app/analysis/migrations/0009_analysisschedule_analysisinstance.py` (via `makemigrations`)
- Test: `services/app/analysis/tests/test_models_vast.py`

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_models_vast.py`:

```python
"""
Title: test_models_vast.py — AnalysisSchedule / AnalysisInstance models
Description:
    Status defaults, max_jobs fallback, FK behaviour, and the
    effective_max_jobs helper for issue #155 Sub-project A.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from django.test import TestCase, override_settings

from analysis.models import AnalysisInstance, AnalysisSchedule


class AnalysisScheduleModelTests(TestCase):
    """AnalysisSchedule defaults and max_jobs fallback."""

    def test_new_schedule_is_pending(self):
        """A freshly created schedule starts pending."""
        sched = AnalysisSchedule.objects.create()
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_PENDING)

    @override_settings(VAST_MAX_JOBS=100)
    def test_effective_max_jobs_falls_back_to_setting(self):
        """Null max_jobs uses settings.VAST_MAX_JOBS."""
        sched = AnalysisSchedule.objects.create(max_jobs=None)
        self.assertEqual(sched.effective_max_jobs(), 100)

    def test_effective_max_jobs_uses_explicit_value(self):
        """An explicit max_jobs overrides the setting."""
        sched = AnalysisSchedule.objects.create(max_jobs=42)
        self.assertEqual(sched.effective_max_jobs(), 42)


class AnalysisInstanceModelTests(TestCase):
    """AnalysisInstance defaults and schedule linkage."""

    def test_new_instance_is_launching(self):
        """A freshly created instance starts launching with no vast id."""
        sched = AnalysisSchedule.objects.create()
        inst = AnalysisInstance.objects.create(schedule=sched)
        self.assertEqual(inst.status, AnalysisInstance.STATUS_LAUNCHING)
        self.assertIsNone(inst.vast_instance_id)
        self.assertEqual(inst.launch_worker_ids, [])

    def test_is_live_true_for_launching_and_running(self):
        """is_live is True only for non-terminal states."""
        sched = AnalysisSchedule.objects.create()
        inst = AnalysisInstance.objects.create(schedule=sched)
        self.assertTrue(inst.is_live)
        inst.status = AnalysisInstance.STATUS_DESTROYED
        self.assertFalse(inst.is_live)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_models_vast.py -v`
Expected: FAIL — `ImportError: cannot import name 'AnalysisSchedule'`.

- [ ] **Step 3: Add the models**

Append to `services/app/analysis/models.py` (end of file):

```python
class AnalysisSchedule(models.Model):
    """An opaque request to run one capped analysis batch (issue #155).

    This row IS the manual trigger: an admin (or any app-side actor)
    inserts a pending row; the reconcile cron picks it up. The cron does
    not care how it was created.
    """

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16, default=STATUS_PENDING,
        choices=STATUS_CHOICES, db_index=True,
    )
    max_jobs = models.IntegerField(
        null=True, blank=True,
        help_text="Per-run job cap; null → settings.VAST_MAX_JOBS.",
    )
    note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "analysis_schedules"
        ordering = ["created_at"]
        verbose_name = "Analysis Schedule"
        verbose_name_plural = "Analysis Schedules"

    def __str__(self):
        """Return a human-readable identifier for this schedule."""
        return f"AnalysisSchedule #{self.pk} [{self.status}]"

    def effective_max_jobs(self) -> int:
        """Return the job cap to use: explicit max_jobs or the setting.

        Returns:
            int: ``self.max_jobs`` when set, else
                ``django.conf.settings.VAST_MAX_JOBS``.
        """
        from django.conf import settings as _s
        return self.max_jobs if self.max_jobs is not None else _s.VAST_MAX_JOBS


class AnalysisInstance(models.Model):
    """A vast.ai instance launched for one AnalysisSchedule (issue #155).

    Live truth + crash-safe teardown backstop. The reconcile cron
    re-derives everything from this table each tick.
    """

    STATUS_LAUNCHING = "launching"
    STATUS_RUNNING = "running"
    STATUS_DESTROYED = "destroyed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_LAUNCHING, "Launching"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DESTROYED, "Destroyed"),
        (STATUS_FAILED, "Failed"),
    ]
    _LIVE_STATES = (STATUS_LAUNCHING, STATUS_RUNNING)

    schedule = models.ForeignKey(
        AnalysisSchedule, on_delete=models.CASCADE,
        related_name="instances",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16, default=STATUS_LAUNCHING,
        choices=STATUS_CHOICES, db_index=True,
    )
    vast_instance_id = models.CharField(
        max_length=32, null=True, blank=True,
        help_text="vast 'new_contract' id; null until create succeeds.",
    )
    launched_at = models.DateTimeField(null=True, blank=True)
    hard_deadline = models.DateTimeField(null=True, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)
    offer_dph = models.FloatField(
        null=True, blank=True,
        help_text="$/hr actually accepted, for cost visibility.",
    )
    launch_worker_ids = models.JSONField(
        default=list, blank=True,
        help_text="WorkerHeartbeat.worker_id set known at launch "
                  "(for drained-by-stale-heartbeat correlation).",
    )
    worker_id = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="The WorkerHeartbeat bound to this instance once a "
                  "post-launch worker appears; null until correlated.",
    )

    class Meta:
        db_table = "analysis_instances"
        ordering = ["-created_at"]
        verbose_name = "Analysis Instance"
        verbose_name_plural = "Analysis Instances"

    def __str__(self):
        """Return a human-readable identifier for this instance."""
        return f"AnalysisInstance #{self.pk} [{self.status}]"

    @property
    def is_live(self) -> bool:
        """True when this instance is launching or running (non-terminal)."""
        return self.status in self._LIVE_STATES
```

- [ ] **Step 4: Make the migration**

Run:
```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && \
source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && \
python manage.py makemigrations analysis
```
Expected: creates `analysis/migrations/0009_analysisschedule_analysisinstance.py` (two `CreateModel` operations).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_models_vast.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: bandit + commit**

```bash
bandit -ll analysis/models.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/models.py services/app/analysis/migrations/0009_analysisschedule_analysisinstance.py services/app/analysis/tests/test_models_vast.py
git commit -m "feat(#155): AnalysisSchedule + AnalysisInstance models (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Register both models in Django admin

**Files:**
- Modify: `services/app/analysis/admin.py`
- Test: `services/app/analysis/tests/test_admin_vast.py`

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_admin_vast.py`:

```python
"""
Title: test_admin_vast.py — admin registration for vast scheduling models
Description:
    AnalysisSchedule (operator-insertable trigger) and AnalysisInstance
    (read-mostly live/teardown view) must be registered in Django admin.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from django.contrib import admin
from django.test import TestCase

from analysis.models import AnalysisInstance, AnalysisSchedule


class VastAdminRegistrationTests(TestCase):
    """The two scheduling models are registered in admin."""

    def test_schedule_registered(self):
        """AnalysisSchedule appears in the admin registry."""
        self.assertIn(AnalysisSchedule, admin.site._registry)

    def test_instance_registered(self):
        """AnalysisInstance appears in the admin registry."""
        self.assertIn(AnalysisInstance, admin.site._registry)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_admin_vast.py -v`
Expected: FAIL — `AssertionError: ... not found in admin.site._registry`.

- [ ] **Step 3: Register the models**

Replace the body of `services/app/analysis/admin.py` (keep the header docstring; append a changelog line `    2026-05-18: Register AnalysisSchedule/AnalysisInstance (#155).`) so the file reads:

```python
from django.contrib import admin

from .models import AnalysisInstance, AnalysisSchedule


@admin.register(AnalysisSchedule)
class AnalysisScheduleAdmin(admin.ModelAdmin):
    """Operator window + insert point for run-intent rows."""

    list_display = ("id", "status", "max_jobs", "created_at")
    list_filter = ("status",)
    readonly_fields = ("created_at",)


@admin.register(AnalysisInstance)
class AnalysisInstanceAdmin(admin.ModelAdmin):
    """Read-mostly live/teardown view of launched vast instances."""

    list_display = (
        "id", "schedule", "status", "vast_instance_id",
        "offer_dph", "launched_at", "hard_deadline", "destroyed_at",
    )
    list_filter = ("status",)
    readonly_fields = (
        "schedule", "created_at", "vast_instance_id", "launched_at",
        "hard_deadline", "destroyed_at", "offer_dph",
        "launch_worker_ids", "worker_id",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest analysis/tests/test_admin_vast.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && bandit -ll analysis/admin.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/admin.py services/app/analysis/tests/test_admin_vast.py
git commit -m "feat(#155): register vast scheduling models in admin (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: vast.ai REST client (`vast_dispatch.py`)

**Files:**
- Create: `services/app/analysis/services/vast_dispatch.py`
- Test: `services/app/analysis/tests/test_vast_dispatch.py`

Real vast.ai REST API (verified via context7 / docs.vast.ai):
- Search offers: `POST https://console.vast.ai/api/v0/bundles/`, Bearer auth, JSON body of filters; response `{"offers": [{"id", "gpu_name", "dph_total", ...}]}`.
- Create from template: `PUT https://console.vast.ai/api/v0/asks/{offer_id}/`, body `{"template_hash_id", "label", "env": {...dict, merges with template env, request overrides}}`; response `{"new_contract": <int>}`.
- Destroy: `DELETE https://console.vast.ai/api/v0/instances/{id}/`; response `{"success": bool, "msg": str}`; 404 = already gone.
- List: `GET https://console.vast.ai/api/v0/instances/`; response `{"instances": [{"id", "label", "actual_status", ...}]}`.

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_vast_dispatch.py`:

```python
"""
Title: test_vast_dispatch.py — thin vast.ai REST client
Description:
    Offer filtering/sort + price ceiling, create env-merge payload,
    destroy idempotency on 404, list parsing, key-never-logged, and
    NoVastOfferError when nothing qualifies. httpx is mocked.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase

from analysis.services import vast_dispatch


class SearchOffersTests(TestCase):
    """search_cheapest_offer filters by price and picks the cheapest."""

    def _resp(self, payload, status=200):
        return MagicMock(status_code=status, json=MagicMock(return_value=payload))

    def test_picks_cheapest_under_ceiling(self):
        """Cheapest offer at/under the ceiling is chosen."""
        payload = {"offers": [
            {"id": 11, "gpu_name": "L40S", "dph_total": 1.20},
            {"id": 22, "gpu_name": "L40S", "dph_total": 0.90},
            {"id": 33, "gpu_name": "L40S", "dph_total": 2.50},
        ]}
        with patch("analysis.services.vast_dispatch.httpx.post",
                   return_value=self._resp(payload)):
            offer = vast_dispatch.search_cheapest_offer(
                api_key="k", gpu_name="L40S", max_dph=1.50)
        self.assertEqual(offer["id"], 22)
        self.assertEqual(offer["dph_total"], 0.90)

    def test_raises_when_none_under_ceiling(self):
        """All offers above the ceiling → NoVastOfferError."""
        payload = {"offers": [{"id": 1, "gpu_name": "L40S", "dph_total": 9.0}]}
        with patch("analysis.services.vast_dispatch.httpx.post",
                   return_value=self._resp(payload)):
            with self.assertRaises(vast_dispatch.NoVastOfferError):
                vast_dispatch.search_cheapest_offer(
                    api_key="k", gpu_name="L40S", max_dph=1.50)

    def test_raises_on_empty(self):
        """Empty offer list → NoVastOfferError."""
        with patch("analysis.services.vast_dispatch.httpx.post",
                   return_value=self._resp({"offers": []})):
            with self.assertRaises(vast_dispatch.NoVastOfferError):
                vast_dispatch.search_cheapest_offer(
                    api_key="k", gpu_name="L40S", max_dph=1.50)


class CreateInstanceTests(TestCase):
    """create_instance sends template_hash_id, label and merged env."""

    def test_create_payload_and_returns_contract_id(self):
        """Body carries template/label/env; returns new_contract as str."""
        resp = MagicMock(status_code=200,
                          json=MagicMock(return_value={"new_contract": 98765}))
        with patch("analysis.services.vast_dispatch.httpx.put",
                   return_value=resp) as mock_put:
            result = vast_dispatch.create_instance(
                api_key="k", offer_id=22, template_hash="HASH",
                label="wl-sched-7",
                env={"WL_CAMPAIGN_ID": "c1", "WLW_MAX_JOBS": "100",
                     "WL_SCHEDULE_ID": "7"})
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["vast_instance_id"], "98765")
        _, kwargs = mock_put.call_args
        self.assertEqual(kwargs["json"]["template_hash_id"], "HASH")
        self.assertEqual(kwargs["json"]["label"], "wl-sched-7")
        self.assertEqual(kwargs["json"]["env"]["WL_SCHEDULE_ID"], "7")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer k")

    def test_create_non_2xx_returns_not_ok(self):
        """A non-2xx create response yields ok=False, no raise."""
        resp = MagicMock(status_code=400, text="bad offer",
                         json=MagicMock(return_value={}))
        with patch("analysis.services.vast_dispatch.httpx.put", return_value=resp):
            result = vast_dispatch.create_instance(
                api_key="k", offer_id=1, template_hash="H",
                label="l", env={})
        self.assertFalse(result["ok"])


class DestroyInstanceTests(TestCase):
    """destroy_instance is idempotent and never raises."""

    def test_2xx_success(self):
        resp = MagicMock(status_code=200,
                         json=MagicMock(return_value={"success": True}))
        with patch("analysis.services.vast_dispatch.httpx.delete",
                   return_value=resp):
            result = vast_dispatch.destroy_instance(api_key="k",
                                                    vast_instance_id="123")
        self.assertTrue(result["ok"])

    def test_404_treated_as_success(self):
        """A 404 (already gone) is idempotent success."""
        resp = MagicMock(status_code=404, text="not found",
                         json=MagicMock(return_value={}))
        with patch("analysis.services.vast_dispatch.httpx.delete",
                   return_value=resp):
            result = vast_dispatch.destroy_instance(api_key="k",
                                                    vast_instance_id="123")
        self.assertTrue(result["ok"])

    def test_network_error_not_ok_no_raise(self):
        import httpx
        with patch("analysis.services.vast_dispatch.httpx.delete",
                   side_effect=httpx.ConnectError("boom")):
            result = vast_dispatch.destroy_instance(api_key="k",
                                                    vast_instance_id="123")
        self.assertFalse(result["ok"])

    def test_api_key_never_logged(self):
        """The api key must never appear in log output."""
        import httpx
        with self.assertLogs("analysis.services.vast_dispatch",
                              level="WARNING") as cm:
            with patch("analysis.services.vast_dispatch.httpx.delete",
                       side_effect=httpx.ConnectError("boom")):
                vast_dispatch.destroy_instance(api_key="SECRETKEY",
                                               vast_instance_id="123")
        self.assertNotIn("SECRETKEY", "\n".join(cm.output))


class ListInstancesTests(TestCase):
    """list_instances returns the parsed instances array."""

    def test_returns_instances(self):
        resp = MagicMock(status_code=200, json=MagicMock(
            return_value={"instances": [
                {"id": 1, "label": "wl-sched-7", "actual_status": "running"}]}))
        with patch("analysis.services.vast_dispatch.httpx.get",
                   return_value=resp):
            out = vast_dispatch.list_instances(api_key="k")
        self.assertEqual(out[0]["label"], "wl-sched-7")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_vast_dispatch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analysis.services.vast_dispatch'`.

- [ ] **Step 3: Implement the client**

Create `services/app/analysis/services/vast_dispatch.py`:

```python
"""
Title: vast_dispatch.py — thin REST client for vast.ai instance lifecycle
Description:
    Single-purpose helper the reconcile cron uses to search offers,
    create an instance from a template hash, destroy an instance, and
    list instances. Mirrors app/runpod_client.py: network/HTTP errors
    become structured dicts, never raised — EXCEPT search, which raises
    NoVastOfferError when nothing qualifies (a real decision the caller
    must branch on). The VAST_API_KEY is never logged.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)

_BASE = "https://console.vast.ai/api/v0"
_BUNDLES_URL = f"{_BASE}/bundles/"
_ASK_URL = f"{_BASE}/asks/{{offer_id}}/"
_INSTANCE_URL = f"{_BASE}/instances/{{instance_id}}/"
_INSTANCES_URL = f"{_BASE}/instances/"
_BODY_TRUNCATE_CHARS = 500


class NoVastOfferError(RuntimeError):
    """Raised when no vast offer matches the GPU + price ceiling."""


def _truncate(body: Any) -> str:
    """Return str(body) trimmed to a safe log length (never the api key)."""
    text = "" if body is None else str(body)
    if len(text) <= _BODY_TRUNCATE_CHARS:
        return text
    return text[:_BODY_TRUNCATE_CHARS] + "...[truncated]"


def _headers(api_key: str) -> dict:
    """Return auth + json headers. The key is used here, never logged."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def search_cheapest_offer(
    *, api_key: str, gpu_name: str, max_dph: float, timeout: float = 20.0,
) -> dict:
    """Return the cheapest on-demand offer for ``gpu_name`` at/under ``max_dph``.

    Args:
        api_key: vast API key (Bearer). Never logged.
        gpu_name: vast GPU model name, e.g. ``"L40S"``.
        max_dph: maximum acceptable $/hr (``dph_total``) ceiling.
        timeout: HTTP timeout in seconds.

    Returns:
        dict: the chosen offer dict (has at least ``id`` and ``dph_total``).

    Raises:
        NoVastOfferError: on a non-2xx response, a network error, an empty
            result, or when every offer exceeds ``max_dph``.
    """
    body = {
        "limit": 64,
        "type": "ondemand",
        "rentable": {"eq": True},
        "gpu_name": {"eq": gpu_name},
        "order": [["dph_total", "asc"]],
    }
    try:
        resp = httpx.post(_BUNDLES_URL, headers=_headers(api_key),
                          json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        _LOGGER.warning("vast search network error gpu=%s err=%s",
                        gpu_name, _truncate(exc))
        raise NoVastOfferError("vast search network error") from exc
    if not 200 <= resp.status_code < 300:
        _LOGGER.warning("vast search non-2xx gpu=%s status=%s body=%s",
                        gpu_name, resp.status_code, _truncate(resp.text))
        raise NoVastOfferError(f"vast search status {resp.status_code}")
    offers = (resp.json() or {}).get("offers") or []
    affordable = sorted(
        (o for o in offers if o.get("dph_total") is not None
         and float(o["dph_total"]) <= max_dph),
        key=lambda o: float(o["dph_total"]),
    )
    if not affordable:
        _LOGGER.warning("vast search no offer gpu=%s max_dph=%s offers=%d",
                        gpu_name, max_dph, len(offers))
        raise NoVastOfferError(
            f"no {gpu_name} offer at/under {max_dph} $/hr")
    return affordable[0]


def create_instance(
    *, api_key: str, offer_id: int, template_hash: str, label: str,
    env: dict, timeout: float = 30.0,
) -> dict:
    """Create an instance from a template hash on the given offer.

    ``env`` is sent as a JSON object: vast merges it with the template's
    env, request keys overriding template keys (verified behaviour).

    Args:
        api_key: vast API key (Bearer). Never logged.
        offer_id: offer id from :func:`search_cheapest_offer`.
        template_hash: ``VAST_TEMPLATE_HASH`` (version-pinned config).
        label: instance label (used for orphan discovery).
        env: per-run env dict (WL_CAMPAIGN_ID, WLW_MAX_JOBS, WL_SCHEDULE_ID).
        timeout: HTTP timeout in seconds.

    Returns:
        dict: ``{"ok", "status_code", "message", "vast_instance_id"}``.
            ``vast_instance_id`` is the str of vast ``new_contract`` on
            success, else None. Never raises.
    """
    url = _ASK_URL.format(offer_id=offer_id)
    payload = {"template_hash_id": template_hash, "label": label, "env": env}
    try:
        resp = httpx.put(url, headers=_headers(api_key), json=payload,
                         timeout=timeout)
    except httpx.HTTPError as exc:
        _LOGGER.warning("vast create network error offer=%s err=%s",
                        offer_id, _truncate(exc))
        return {"ok": False, "status_code": 0,
                "message": _truncate(exc), "vast_instance_id": None}
    if 200 <= resp.status_code < 300:
        contract = (resp.json() or {}).get("new_contract")
        if contract is None:
            _LOGGER.warning("vast create 2xx but no new_contract offer=%s",
                            offer_id)
            return {"ok": False, "status_code": resp.status_code,
                    "message": "no new_contract in response",
                    "vast_instance_id": None}
        return {"ok": True, "status_code": resp.status_code,
                "message": "created", "vast_instance_id": str(contract)}
    body = _truncate(resp.text)
    _LOGGER.warning("vast create non-2xx offer=%s status=%s body=%s",
                    offer_id, resp.status_code, body)
    return {"ok": False, "status_code": resp.status_code,
            "message": body or "vast create error", "vast_instance_id": None}


def destroy_instance(
    *, api_key: str, vast_instance_id: str, timeout: float = 20.0,
) -> dict:
    """Destroy an instance. Idempotent: 404 (already gone) is success.

    Args:
        api_key: vast API key (Bearer). Never logged.
        vast_instance_id: the vast contract/instance id.
        timeout: HTTP timeout in seconds.

    Returns:
        dict: ``{"ok", "status_code", "message"}``. Never raises.
    """
    url = _INSTANCE_URL.format(instance_id=vast_instance_id)
    try:
        resp = httpx.delete(url, headers=_headers(api_key), timeout=timeout)
    except httpx.HTTPError as exc:
        _LOGGER.warning("vast destroy network error inst=%s err=%s",
                        vast_instance_id, _truncate(exc))
        return {"ok": False, "status_code": 0, "message": _truncate(exc)}
    if 200 <= resp.status_code < 300 or resp.status_code == 404:
        return {"ok": True, "status_code": resp.status_code,
                "message": "destroyed"}
    body = _truncate(resp.text)
    _LOGGER.warning("vast destroy non-2xx inst=%s status=%s body=%s",
                    vast_instance_id, resp.status_code, body)
    return {"ok": False, "status_code": resp.status_code,
            "message": body or "vast destroy error"}


def list_instances(*, api_key: str, timeout: float = 20.0) -> list[dict]:
    """List the authenticated account's instances.

    Args:
        api_key: vast API key (Bearer). Never logged.
        timeout: HTTP timeout in seconds.

    Returns:
        list[dict]: the ``instances`` array, or [] on any error.
    """
    try:
        resp = httpx.get(_INSTANCES_URL, headers=_headers(api_key),
                        timeout=timeout)
    except httpx.HTTPError as exc:
        _LOGGER.warning("vast list network error err=%s", _truncate(exc))
        return []
    if not 200 <= resp.status_code < 300:
        _LOGGER.warning("vast list non-2xx status=%s body=%s",
                        resp.status_code, _truncate(resp.text))
        return []
    return (resp.json() or {}).get("instances") or []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_vast_dispatch.py -v`
Expected: PASS (all classes).

- [ ] **Step 5: bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && bandit -ll analysis/services/vast_dispatch.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/services/vast_dispatch.py services/app/analysis/tests/test_vast_dispatch.py
git commit -m "feat(#155): vast.ai REST client (search/create/destroy/list) (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Reconcile command — skeleton + VAST_ENABLED gating

**Files:**
- Create: `services/app/analysis/management/commands/reconcile_vast_analysis.py`
- Test: append to `services/app/analysis/tests/test_reconcile_vast_gating.py`

- [ ] **Step 1: Write the failing test**

Append to `services/app/analysis/tests/test_reconcile_vast_gating.py`:

```python
from io import StringIO

from django.core.management import call_command


class ReconcileGatingTests(TestCase):
    """The command is a safe no-op unless VAST_ENABLED is true."""

    @override_settings(VAST_ENABLED=False)
    def test_disabled_is_noop(self):
        """VAST_ENABLED False → logs one line, touches nothing, exits 0."""
        out = StringIO()
        call_command("reconcile_vast_analysis", stdout=out)
        self.assertIn("disabled", out.getvalue().lower())

    @override_settings(VAST_ENABLED=True, VAST_API_KEY="")
    def test_enabled_without_key_is_noop(self):
        """Missing VAST_API_KEY → no-op (validate env before launch)."""
        out = StringIO()
        call_command("reconcile_vast_analysis", stdout=out)
        self.assertIn("not configured", out.getvalue().lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_reconcile_vast_gating.py::ReconcileGatingTests -v`
Expected: FAIL — `CommandError: Unknown command: 'reconcile_vast_analysis'`.

- [ ] **Step 3: Implement the skeleton + gating**

Create `services/app/analysis/management/commands/reconcile_vast_analysis.py`:

```python
"""
Title: reconcile_vast_analysis.py — idempotent vast.ai reconcile cron
Description:
    Run every 45 min by a Railway cron service. Holds no long-lived
    process and no in-memory state: each run re-derives "what should be
    true" from AnalysisSchedule + AnalysisInstance and converges.
    Order each run: (1) REAP — destroy any instance past hard_deadline
    or whose worker heartbeat went stale (batch drained); recover stuck
    schedules; destroy orphans by label. (2) LAUNCH — if no instance is
    live and a pending schedule exists, provision one.
    Gated by settings.VAST_ENABLED (no-op when off), exactly like
    RUNPOD_ENABLED gates the start-pod endpoint.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Idempotent reap-then-launch reconcile for vast.ai analysis runs."""

    help = (
        "Reconcile vast.ai analysis instances: destroy finished/overdue "
        "boxes, then launch one if a run is scheduled. Idempotent; safe "
        "to run on a 45-minute cron. No-op unless VAST_ENABLED."
    )

    def handle(self, *args, **options):
        """Entry point. No-op when disabled or unconfigured.

        Side effects:
            When enabled+configured: runs reap then launch (Tasks 6, 7).
        """
        if not getattr(settings, "VAST_ENABLED", False):
            self.stdout.write("vast reconcile disabled (VAST_ENABLED off)")
            return
        if not getattr(settings, "VAST_API_KEY", ""):
            self.stdout.write(
                "vast reconcile: VAST_API_KEY not configured — skipping")
            return
        api_key = settings.VAST_API_KEY
        reaped = _reap(api_key)
        launched = _launch(api_key)
        self.stdout.write(
            f"vast reconcile done: reaped={reaped} launched={launched}")


def _reap(api_key: str) -> int:
    """Destroy finished/overdue instances. Implemented in Task 6.

    Returns:
        int: number of instances destroyed this run.
    """
    return 0


def _launch(api_key: str) -> int:
    """Launch one instance if scheduled and none live. Implemented in Task 7.

    Returns:
        int: 1 if an instance was launched, else 0.
    """
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_reconcile_vast_gating.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && bandit -ll analysis/management/commands/reconcile_vast_analysis.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/management/commands/reconcile_vast_analysis.py services/app/analysis/tests/test_reconcile_vast_gating.py
git commit -m "feat(#155): reconcile_vast_analysis command skeleton + gating (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Reap pass — hard deadline, stale-heartbeat drained, recovery, orphans

**Files:**
- Modify: `services/app/analysis/management/commands/reconcile_vast_analysis.py` (replace `_reap`)
- Test: `services/app/analysis/tests/test_reconcile_vast_reap.py`

Reap logic (spec "Drained detection" + "Reap first"):
1. **Bind worker:** for the single live instance with `worker_id is None`, find the first `WorkerHeartbeat` whose `worker_id` is NOT in `launch_worker_ids` and whose `last_seen >= launched_at`; set `instance.worker_id`.
2. For each non-terminal `AnalysisInstance`:
   - past `hard_deadline` → destroy.
   - else **drained**: bound worker's `last_seen` older than `VAST_WORKER_STALE_MINUTES`, OR bound heartbeat has `batch_total` not null and `batch_processed >= batch_total` → destroy.
   - else no worker bound AND `now - launched_at > VAST_WORKER_STALE_MINUTES` → worker never registered → destroy + mark schedule failed.
   - On vast-destroy ok → status `destroyed`, stamp `destroyed_at`. On not-ok → leave non-terminal (next tick retries).
3. **Orphan-by-label:** `vast_dispatch.list_instances`; for any instance whose `label` matches `wl-sched-<id>` where that `AnalysisInstance` is terminal/absent → destroy it.
4. **Schedule recovery:** any `AnalysisSchedule` in `running` whose latest `AnalysisInstance` is terminal → `done` if that instance is `destroyed`, else `failed`.

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_reconcile_vast_reap.py`:

```python
"""
Title: test_reconcile_vast_reap.py — reconcile reap pass
Description:
    hard_deadline destroy; stale-heartbeat drained destroy; worker
    binding; never-registered failure; destroy-retry on failure;
    schedule recovery; orphan-by-label. vast_dispatch is mocked.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from analysis.models import (
    AnalysisInstance, AnalysisSchedule, WorkerHeartbeat,
)
from analysis.management.commands.reconcile_vast_analysis import _reap

OK = {"ok": True, "status_code": 200, "message": "destroyed"}
FAIL = {"ok": False, "status_code": 0, "message": "boom"}


@override_settings(VAST_API_KEY="k", VAST_WORKER_STALE_MINUTES=15)
class ReapTests(TestCase):
    """Reap destroys finished/overdue instances and recovers schedules."""

    def _live_instance(self, **kw):
        sched = AnalysisSchedule.objects.create(
            status=AnalysisSchedule.STATUS_RUNNING)
        defaults = dict(
            schedule=sched, status=AnalysisInstance.STATUS_RUNNING,
            vast_instance_id="555",
            launched_at=timezone.now() - timedelta(hours=1),
            hard_deadline=timezone.now() + timedelta(hours=5),
            launch_worker_ids=[],
        )
        defaults.update(kw)
        return AnalysisInstance.objects.create(**defaults)

    def test_past_hard_deadline_destroyed(self):
        """An instance past hard_deadline is destroyed unconditionally."""
        inst = self._live_instance(
            hard_deadline=timezone.now() - timedelta(minutes=1))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            n = _reap("k")
        inst.refresh_from_db()
        self.assertEqual(n, 1)
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertIsNotNone(inst.destroyed_at)

    def test_stale_heartbeat_drained_destroyed(self):
        """Bound worker heartbeat stale → drained → destroyed; sched done."""
        inst = self._live_instance()
        WorkerHeartbeat.objects.create(worker_id="w-new")
        WorkerHeartbeat.objects.filter(worker_id="w-new").update(
            last_seen=timezone.now() - timedelta(minutes=30))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertEqual(inst.worker_id, "w-new")
        self.assertEqual(inst.schedule.status, AnalysisSchedule.STATUS_DONE)

    def test_pre_launch_worker_not_bound(self):
        """A heartbeat present at launch is NOT bound (not this run)."""
        inst = self._live_instance(launch_worker_ids=["w-old"])
        WorkerHeartbeat.objects.create(worker_id="w-old")
        WorkerHeartbeat.objects.filter(worker_id="w-old").update(
            last_seen=timezone.now() - timedelta(minutes=30))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertIsNone(inst.worker_id)
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)

    def test_worker_never_registered_fails(self):
        """No worker bound and past stale window from launch → failed."""
        inst = self._live_instance(
            launched_at=timezone.now() - timedelta(minutes=30))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertEqual(inst.schedule.status, AnalysisSchedule.STATUS_FAILED)

    def test_destroy_failure_leaves_non_terminal_for_retry(self):
        """A failed vast destroy keeps the row live for the next tick."""
        inst = self._live_instance(
            hard_deadline=timezone.now() - timedelta(minutes=1))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=FAIL), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)

    def test_orphan_by_label_destroyed(self):
        """A live vast instance whose AnalysisInstance is terminal is killed."""
        sched = AnalysisSchedule.objects.create(
            status=AnalysisSchedule.STATUS_DONE)
        AnalysisInstance.objects.create(
            schedule=sched, status=AnalysisInstance.STATUS_DESTROYED,
            vast_instance_id="900")
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK) as d, \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances",
                   return_value=[{"id": 900, "label": f"wl-sched-{sched.id}",
                                  "actual_status": "running"}]):
            _reap("k")
        d.assert_any_call(api_key="k", vast_instance_id="900")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_reconcile_vast_reap.py -v`
Expected: FAIL — `_reap` returns 0 / no behaviour (stub from Task 5).

- [ ] **Step 3: Implement `_reap`**

In `services/app/analysis/management/commands/reconcile_vast_analysis.py`, add imports at the top (after the existing imports) and replace the `_reap` stub:

```python
from datetime import timedelta

from django.utils import timezone

from analysis.models import (
    AnalysisInstance, AnalysisSchedule, WorkerHeartbeat,
)
from analysis.services import vast_dispatch

_LABEL_PREFIX = "wl-sched-"


def _label_for(schedule_id: int) -> str:
    """Return the vast instance label for a schedule (orphan discovery)."""
    return f"{_LABEL_PREFIX}{schedule_id}"


def _bind_worker(inst: AnalysisInstance) -> None:
    """Bind the first post-launch WorkerHeartbeat to this instance.

    Only a worker that heartbeated at/after launch and was NOT present
    at launch is this run's worker (≤1-instance invariant makes this
    unambiguous). Mutates and saves ``inst.worker_id`` when found.
    """
    if inst.worker_id or not inst.launched_at:
        return
    known = set(inst.launch_worker_ids or [])
    hb = (
        WorkerHeartbeat.objects
        .exclude(worker_id__in=known)
        .filter(last_seen__gte=inst.launched_at)
        .order_by("last_seen")
        .first()
    )
    if hb is not None:
        inst.worker_id = hb.worker_id
        inst.save(update_fields=["worker_id"])


def _is_drained(inst: AnalysisInstance, stale_cutoff) -> bool:
    """Return True when the instance's batch is drained.

    Drained = bound worker heartbeat is stale (worker exited) OR the
    bound heartbeat reports its job cap done.
    """
    if not inst.worker_id:
        return False
    hb = WorkerHeartbeat.objects.filter(worker_id=inst.worker_id).first()
    if hb is None:
        return False
    if hb.last_seen < stale_cutoff:
        return True
    return (hb.batch_total is not None
            and hb.batch_processed >= hb.batch_total)


def _destroy(inst: AnalysisInstance, api_key: str) -> bool:
    """Destroy the vast box for ``inst``. Return True iff destroyed.

    On success: status=destroyed + destroyed_at stamped. On failure:
    row left non-terminal so the next tick retries.
    """
    if not inst.vast_instance_id:
        # Nothing was ever created — mark terminal without a vast call.
        inst.status = AnalysisInstance.STATUS_FAILED
        inst.save(update_fields=["status"])
        return False
    result = vast_dispatch.destroy_instance(
        api_key=api_key, vast_instance_id=inst.vast_instance_id)
    if not result["ok"]:
        return False
    inst.status = AnalysisInstance.STATUS_DESTROYED
    inst.destroyed_at = timezone.now()
    inst.save(update_fields=["status", "destroyed_at"])
    return True


def _recover_schedules() -> None:
    """Settle any `running` schedule whose latest instance is terminal."""
    for sched in AnalysisSchedule.objects.filter(
            status=AnalysisSchedule.STATUS_RUNNING):
        last = sched.instances.order_by("-created_at").first()
        if last is None or last.is_live:
            continue
        sched.status = (
            AnalysisSchedule.STATUS_DONE
            if last.status == AnalysisInstance.STATUS_DESTROYED
            else AnalysisSchedule.STATUS_FAILED
        )
        sched.save(update_fields=["status"])


def _reap(api_key: str) -> int:
    """Destroy finished/overdue instances; recover schedules; kill orphans.

    Returns:
        int: number of instances destroyed this run.
    """
    now = timezone.now()
    stale_cutoff = now - timedelta(
        minutes=settings.VAST_WORKER_STALE_MINUTES)
    destroyed = 0

    for inst in AnalysisInstance.objects.filter(
            status__in=AnalysisInstance._LIVE_STATES):
        _bind_worker(inst)
        overdue = inst.hard_deadline is not None and now >= inst.hard_deadline
        drained = _is_drained(inst, stale_cutoff)
        never_registered = (
            not inst.worker_id and inst.launched_at is not None
            and inst.launched_at < stale_cutoff
        )
        if not (overdue or drained or never_registered):
            continue
        if _destroy(inst, api_key):
            destroyed += 1
            if never_registered and not overdue and not drained:
                inst.schedule.status = AnalysisSchedule.STATUS_FAILED
                inst.schedule.save(update_fields=["status"])

    _recover_schedules()

    # Orphan-by-label: kill any live vast instance whose AnalysisInstance
    # is terminal/absent (covers a lost create-time DB write).
    terminal_or_absent = []
    for vinst in vast_dispatch.list_instances(api_key=api_key):
        label = vinst.get("label") or ""
        if not label.startswith(_LABEL_PREFIX):
            continue
        try:
            sched_id = int(label[len(_LABEL_PREFIX):])
        except ValueError:
            continue
        rec = (
            AnalysisInstance.objects
            .filter(schedule_id=sched_id,
                    vast_instance_id=str(vinst.get("id")))
            .first()
        )
        if rec is None or not rec.is_live:
            terminal_or_absent.append(str(vinst.get("id")))
    for vid in terminal_or_absent:
        if vast_dispatch.destroy_instance(
                api_key=api_key, vast_instance_id=vid)["ok"]:
            destroyed += 1

    return destroyed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_reconcile_vast_reap.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && bandit -ll analysis/management/commands/reconcile_vast_analysis.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/management/commands/reconcile_vast_analysis.py services/app/analysis/tests/test_reconcile_vast_reap.py
git commit -m "feat(#155): reconcile reap pass — deadline/drained/orphan/recovery (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Launch pass — FIFO, ≤1 instance, launching-row-first, create

**Files:**
- Modify: `services/app/analysis/management/commands/reconcile_vast_analysis.py` (replace `_launch`)
- Test: `services/app/analysis/tests/test_reconcile_vast_launch.py`

Launch logic (spec "Launch second"):
- Abort if any `AnalysisInstance` is live (`_LIVE_STATES`).
- Pick the oldest `pending` `AnalysisSchedule` (FIFO by `created_at`); none → return 0.
- Snapshot existing `WorkerHeartbeat.worker_id`s.
- Create `AnalysisInstance(status=launching, launch_worker_ids=snapshot, launched_at=now)` BEFORE the vast call.
- `search_cheapest_offer`; on `NoVastOfferError` → leave schedule pending, mark the launching row `failed`, return 0 (reconsidered next tick).
- `create_instance(label=wl-sched-<id>, env={WL_CAMPAIGN_ID, WLW_MAX_JOBS, WL_SCHEDULE_ID})`.
- Success → set `vast_instance_id`, `offer_dph`, `status=running`, `hard_deadline=now+VAST_HARD_DEADLINE_HOURS`, schedule `running`, return 1.
- Failure → instance `failed`, schedule `failed`, return 0.

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_reconcile_vast_launch.py`:

```python
"""
Title: test_reconcile_vast_launch.py — reconcile launch pass
Description:
    FIFO pending pick; ≤1-instance guard; launching-row-before-create;
    no-offer path; create success/failure; worker-id snapshot; env +
    label payload. vast_dispatch is mocked.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from analysis.models import (
    AnalysisInstance, AnalysisSchedule, WorkerHeartbeat,
)
from analysis.services.vast_dispatch import NoVastOfferError
from analysis.management.commands.reconcile_vast_analysis import _launch

OFFER = {"id": 22, "gpu_name": "L40S", "dph_total": 0.90}
CREATE_OK = {"ok": True, "status_code": 200, "message": "created",
             "vast_instance_id": "98765"}
CREATE_FAIL = {"ok": False, "status_code": 400, "message": "bad",
               "vast_instance_id": None}

_P = "analysis.management.commands.reconcile_vast_analysis.vast_dispatch."


@override_settings(VAST_API_KEY="k", VAST_TEMPLATE_HASH="HASH",
                   VAST_CAMPAIGN_ID="camp1", VAST_MAX_JOBS=100,
                   VAST_OFFER_GPU_NAME="L40S", VAST_OFFER_MAX_DPH=1.5,
                   VAST_HARD_DEADLINE_HOURS=6)
class LaunchTests(TestCase):
    """Launch provisions exactly one instance for the oldest pending row."""

    def test_no_pending_is_noop(self):
        """No pending schedule → nothing launched."""
        self.assertEqual(_launch("k"), 0)
        self.assertEqual(AnalysisInstance.objects.count(), 0)

    def test_live_instance_blocks_launch(self):
        """An existing live instance prevents a second launch."""
        s = AnalysisSchedule.objects.create()
        AnalysisInstance.objects.create(
            schedule=s, status=AnalysisInstance.STATUS_RUNNING)
        AnalysisSchedule.objects.create()  # a fresh pending one
        self.assertEqual(_launch("k"), 0)
        self.assertEqual(
            AnalysisInstance.objects.filter(
                status=AnalysisInstance.STATUS_LAUNCHING).count(), 0)

    def test_success_launches_and_sets_fields(self):
        """Happy path: instance running, schedule running, fields set."""
        sched = AnalysisSchedule.objects.create()
        WorkerHeartbeat.objects.create(worker_id="pre-existing")
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance",
                   return_value=CREATE_OK) as create:
            n = _launch("k")
        sched.refresh_from_db()
        inst = AnalysisInstance.objects.get()
        self.assertEqual(n, 1)
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)
        self.assertEqual(inst.vast_instance_id, "98765")
        self.assertEqual(inst.offer_dph, 0.90)
        self.assertIsNotNone(inst.hard_deadline)
        self.assertEqual(inst.launch_worker_ids, ["pre-existing"])
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_RUNNING)
        _, kw = create.call_args
        self.assertEqual(kw["label"], f"wl-sched-{sched.id}")
        self.assertEqual(kw["env"]["WL_CAMPAIGN_ID"], "camp1")
        self.assertEqual(kw["env"]["WLW_MAX_JOBS"], "100")
        self.assertEqual(kw["env"]["WL_SCHEDULE_ID"], str(sched.id))

    def test_fifo_oldest_pending_first(self):
        """The oldest pending schedule is the one launched."""
        old = AnalysisSchedule.objects.create()
        AnalysisSchedule.objects.create()
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_OK):
            _launch("k")
        old.refresh_from_db()
        self.assertEqual(old.status, AnalysisSchedule.STATUS_RUNNING)

    def test_no_offer_marks_instance_failed_schedule_stays_pending(self):
        """NoVastOfferError → launching row failed, schedule still pending."""
        sched = AnalysisSchedule.objects.create()
        with patch(_P + "search_cheapest_offer",
                   side_effect=NoVastOfferError("none")):
            n = _launch("k")
        sched.refresh_from_db()
        self.assertEqual(n, 0)
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_PENDING)
        self.assertEqual(
            AnalysisInstance.objects.get().status,
            AnalysisInstance.STATUS_FAILED)

    def test_create_failure_marks_both_failed(self):
        """vast create failure → instance failed, schedule failed."""
        sched = AnalysisSchedule.objects.create()
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_FAIL):
            n = _launch("k")
        sched.refresh_from_db()
        self.assertEqual(n, 0)
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_FAILED)
        self.assertEqual(
            AnalysisInstance.objects.get().status,
            AnalysisInstance.STATUS_FAILED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_reconcile_vast_launch.py -v`
Expected: FAIL — `_launch` stub returns 0, creates nothing.

- [ ] **Step 3: Implement `_launch`**

In `reconcile_vast_analysis.py` replace the `_launch` stub:

```python
def _launch(api_key: str) -> int:
    """Launch one vast instance for the oldest pending schedule.

    No-op when an instance is already live (≤1-instance invariant) or
    no schedule is pending.

    Returns:
        int: 1 if an instance was launched, else 0.
    """
    if AnalysisInstance.objects.filter(
            status__in=AnalysisInstance._LIVE_STATES).exists():
        return 0
    sched = (
        AnalysisSchedule.objects
        .filter(status=AnalysisSchedule.STATUS_PENDING)
        .order_by("created_at")
        .first()
    )
    if sched is None:
        return 0

    now = timezone.now()
    snapshot = list(
        WorkerHeartbeat.objects.values_list("worker_id", flat=True))
    inst = AnalysisInstance.objects.create(
        schedule=sched,
        status=AnalysisInstance.STATUS_LAUNCHING,
        launched_at=now,
        launch_worker_ids=snapshot,
    )

    try:
        offer = vast_dispatch.search_cheapest_offer(
            api_key=api_key,
            gpu_name=settings.VAST_OFFER_GPU_NAME,
            max_dph=settings.VAST_OFFER_MAX_DPH,
        )
    except vast_dispatch.NoVastOfferError:
        # No capacity under the ceiling now — fail this launch attempt
        # but leave the schedule pending so the next tick retries.
        inst.status = AnalysisInstance.STATUS_FAILED
        inst.save(update_fields=["status"])
        return 0

    env = {
        "WL_CAMPAIGN_ID": settings.VAST_CAMPAIGN_ID,
        "WLW_MAX_JOBS": str(sched.effective_max_jobs()),
        "WL_SCHEDULE_ID": str(sched.id),
    }
    result = vast_dispatch.create_instance(
        api_key=api_key,
        offer_id=offer["id"],
        template_hash=settings.VAST_TEMPLATE_HASH,
        label=_label_for(sched.id),
        env=env,
    )
    if not result["ok"]:
        inst.status = AnalysisInstance.STATUS_FAILED
        inst.save(update_fields=["status"])
        sched.status = AnalysisSchedule.STATUS_FAILED
        sched.save(update_fields=["status"])
        return 0

    inst.vast_instance_id = result["vast_instance_id"]
    inst.offer_dph = float(offer.get("dph_total")) \
        if offer.get("dph_total") is not None else None
    inst.status = AnalysisInstance.STATUS_RUNNING
    inst.hard_deadline = now + timedelta(
        hours=settings.VAST_HARD_DEADLINE_HOURS)
    inst.save(update_fields=[
        "vast_instance_id", "offer_dph", "status", "hard_deadline"])
    sched.status = AnalysisSchedule.STATUS_RUNNING
    sched.save(update_fields=["status"])
    return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_reconcile_vast_launch.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && bandit -ll analysis/management/commands/reconcile_vast_analysis.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/management/commands/reconcile_vast_analysis.py services/app/analysis/tests/test_reconcile_vast_launch.py
git commit -m "feat(#155): reconcile launch pass — FIFO, 1-instance, create (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: End-to-end reconcile integration test

**Files:**
- Test: `services/app/analysis/tests/test_reconcile_vast_integration.py` (no production code change — proves reap+launch compose correctly)

- [ ] **Step 1: Write the test**

Create `services/app/analysis/tests/test_reconcile_vast_integration.py`:

```python
"""
Title: test_reconcile_vast_integration.py — full reconcile lifecycle
Description:
    Tick 1: pending schedule → launched (running). Tick 2 with the
    worker's heartbeat stale → instance destroyed, schedule done, and a
    second pending schedule launched in the same tick (reap-then-launch).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from analysis.models import (
    AnalysisInstance, AnalysisSchedule, WorkerHeartbeat,
)

OFFER = {"id": 22, "gpu_name": "L40S", "dph_total": 0.90}
CREATE_OK = {"ok": True, "status_code": 200, "message": "created",
             "vast_instance_id": "98765"}
DESTROY_OK = {"ok": True, "status_code": 200, "message": "destroyed"}
_P = "analysis.management.commands.reconcile_vast_analysis.vast_dispatch."


@override_settings(VAST_ENABLED=True, VAST_API_KEY="k",
                   VAST_TEMPLATE_HASH="HASH", VAST_CAMPAIGN_ID="c",
                   VAST_MAX_JOBS=100, VAST_OFFER_GPU_NAME="L40S",
                   VAST_OFFER_MAX_DPH=1.5, VAST_HARD_DEADLINE_HOURS=6,
                   VAST_WORKER_STALE_MINUTES=15)
class ReconcileLifecycleTests(TestCase):
    """Reap-then-launch composes across ticks."""

    def test_full_lifecycle(self):
        s1 = AnalysisSchedule.objects.create()
        # Tick 1: launch s1.
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_OK), \
             patch(_P + "destroy_instance", return_value=DESTROY_OK), \
             patch(_P + "list_instances", return_value=[]):
            call_command("reconcile_vast_analysis", stdout=StringIO())
        s1.refresh_from_db()
        inst = AnalysisInstance.objects.get()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)
        self.assertEqual(s1.status, AnalysisSchedule.STATUS_RUNNING)

        # Worker appears, then goes stale (exited after draining batch).
        WorkerHeartbeat.objects.create(worker_id="w1")
        WorkerHeartbeat.objects.filter(worker_id="w1").update(
            last_seen=timezone.now() - timedelta(minutes=30))
        s2 = AnalysisSchedule.objects.create()  # queued for next run

        # Tick 2: reap s1's box (drained) then launch s2.
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_OK), \
             patch(_P + "destroy_instance", return_value=DESTROY_OK), \
             patch(_P + "list_instances", return_value=[]):
            call_command("reconcile_vast_analysis", stdout=StringIO())

        inst.refresh_from_db(); s1.refresh_from_db(); s2.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertEqual(s1.status, AnalysisSchedule.STATUS_DONE)
        self.assertEqual(s2.status, AnalysisSchedule.STATUS_RUNNING)
        self.assertEqual(
            AnalysisInstance.objects.filter(
                status=AnalysisInstance.STATUS_RUNNING).count(), 1)
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest analysis/tests/test_reconcile_vast_integration.py -v`
Expected: PASS (1 test). If it fails, the defect is in Task 6/7 composition — fix there, not here.

- [ ] **Step 3: Run the full vast suite**

Run: `python -m pytest analysis/tests/test_vast_dispatch.py analysis/tests/test_models_vast.py analysis/tests/test_admin_vast.py analysis/tests/test_reconcile_vast_gating.py analysis/tests/test_reconcile_vast_reap.py analysis/tests/test_reconcile_vast_launch.py analysis/tests/test_reconcile_vast_integration.py -v`
Expected: PASS (all).

- [ ] **Step 4: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/tests/test_reconcile_vast_integration.py
git commit -m "test(#155): end-to-end reconcile lifecycle (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Deployment note — Railway cron service

**Files:**
- Create: `docs/superpowers/specs/2026-05-18-vast-provisioning-deployment.md`

No application code. This documents how the operator wires the cron (Railway cron schedule is a service-level setting, not in `railway.toml`).

- [ ] **Step 1: Write the deployment note**

Create `docs/superpowers/specs/2026-05-18-vast-provisioning-deployment.md`:

```markdown
# vast.ai Reconcile — Deployment Note (Sub-project A)

**Cron command:** `python manage.py reconcile_vast_analysis`
**Schedule:** every 45 minutes (`*/45 * * * *`)
**Where:** a Railway **cron service** in the same project as the app,
sharing the app's Postgres. Railway cron schedule is set on the service
in the Railway dashboard (Settings → Cron Schedule), not in
`services/app/railway.toml` (that file is the web service).

**Required env on the cron service** (in addition to the shared DB vars):
- `VAST_ENABLED=true`
- `VAST_API_KEY=<secret>` (never placed on a rented box)
- `VAST_TEMPLATE_HASH=<current release template hash>` (re-point per
  worker release, e.g. when the image tag bumps)
- `VAST_CAMPAIGN_ID=<campaign id passed through to the worker>`
- Optional overrides: `VAST_OFFER_GPU_NAME` (default `L40S`),
  `VAST_OFFER_MAX_DPH` (default `1.50`), `VAST_MAX_JOBS` (default `100`),
  `VAST_HARD_DEADLINE_HOURS` (default `6`),
  `VAST_LAUNCH_GRACE_MINUTES` (default `20`),
  `VAST_WORKER_STALE_MINUTES` (default `15`).

**Worker template prerequisite:** the vast template referenced by
`VAST_TEMPLATE_HASH` must run the pull worker honoring `WL_CAMPAIGN_ID`,
`WLW_MAX_JOBS`, and reporting `WorkerHeartbeat` (existing worker behaviour;
no worker change in this sub-project). Per-run `env` (campaign, max jobs,
schedule id) is merged over the template env by vast at create time.

**Manual trigger:** insert a `pending` row in Django admin →
*Analysis Schedules* (or `AnalysisSchedule.objects.create()`); the next
cron tick picks it up. No web button (by design).

**Safety recap:** ≤1 instance ever live; a drained box is destroyed
within ≤45 min; `hard_deadline` is the absolute cost ceiling; all state
in Postgres so a cron crash/redeploy self-heals next tick.
```

- [ ] **Step 2: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add docs/superpowers/specs/2026-05-18-vast-provisioning-deployment.md
git commit -m "docs(#155): Railway cron deployment note (Sub-project A)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final verification (run before declaring A done)

- [ ] Full quality gate on the changed files (ruff → bandit → mypy → pytest), per project gate. At minimum:
  ```bash
  cd /Users/christopherwebster/Projects/wood_league/services/app && \
  source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && \
  python -m pytest analysis/tests/test_vast_dispatch.py analysis/tests/test_models_vast.py analysis/tests/test_admin_vast.py analysis/tests/test_reconcile_vast_gating.py analysis/tests/test_reconcile_vast_reap.py analysis/tests/test_reconcile_vast_launch.py analysis/tests/test_reconcile_vast_integration.py -v && \
  python manage.py makemigrations --check --dry-run analysis
  ```
  Expected: all tests PASS; `--check` reports no missing migrations.
- [ ] Confirm `git grep -n "RUNPOD" services/app/config/settings.py` still intact (no accidental edits to the RunPod block).
- [ ] Update GitHub issue #155: comment that Sub-project A is implemented; B remains specced/queued.

---

## Self-Review (completed by plan author)

- **Spec coverage:** control loop (T5–7), reap incl. hard_deadline/drained/orphan/recovery (T6), launch incl. crash-gap launching-row-first + FIFO + ≤1-instance (T7), drained-by-stale-heartbeat with launch snapshot + correlation (T6, model fields T2), two tables + admin input surface (T2, T3), vast client mirroring runpod_client (T4), settings/gating (T1, T5), Railway cron + worker env merge (T9), cost-safety invariants exercised in integration (T8). No spec requirement is unmapped.
- **Placeholder scan:** none — every code step contains complete, runnable code; stubs in T5 are explicitly replaced in T6/T7 with the real bodies shown.
- **Type consistency:** `_LIVE_STATES`, `effective_max_jobs()`, `is_live`, `_label_for`, `vast_instance_id` (str), `launch_worker_ids` (list), `worker_id` (str|None), and `vast_dispatch` function signatures (`search_cheapest_offer`/`create_instance`/`destroy_instance`/`list_instances`, all keyword-only `api_key=`) are used identically across tasks and tests.
