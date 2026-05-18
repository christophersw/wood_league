# Analysis Scheduling UI + Recurrence (Sub-project B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin web page to define recurring (crontab) and one-off analysis runs, plus a Step-0 in the existing reconcile cron that materializes due rules into `pending AnalysisSchedule` rows for Sub-project A to launch.

**Architecture:** Producer side layered on the frozen Sub-project A orchestrator. New `RecurringAnalysisSchedule` rule model; an additive `_materialize_recurring()` step prepended (before reap/launch) to `reconcile_vast_analysis`; an `_admin_login_required` page (`views_schedule.py` + templates) with rule CRUD, "run once", "re-run", and a croniter-powered "next runs" preview. The only touch-points to A are additive: Step 0 + a nullable `AnalysisSchedule.recurring_rule` FK.

**Tech Stack:** Django, `croniter`, Postgres, HTMX, management command. Spec: `docs/superpowers/specs/2026-05-18-vast-scheduling-ui-design.md`. Sub-project A is merged to `main` (commit `5baab14`).

---

## Conventions for every task

- **venv + test command** (run from repo):
  ```bash
  cd /Users/christopherwebster/Projects/wood_league/services/app && \
  source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && \
  python -m pytest <test path> -v
  ```
  `conftest.py` auto-sets `DJANGO_SETTINGS_MODULE=config.settings` and loads `.env.test`. Use Django `TestCase` + `override_settings` + `unittest.mock.patch` (mirror `analysis/tests/test_reconcile_vast_*.py`).
- **New test files** go in `analysis/tests/test_*.py` (the package — NOT `analysis/tests.py`).
- **Hard quality gates** (per-edit hook): ruff (no unused imports / E702), mypy, pytest, and **cyclomatic complexity ≤ grade B** (radon `-n C` must be empty). Halstead-effort WARN is non-blocking. After every code change, verify with:
  `ruff check <files> && radon cc <py> -s -n C && python -m pytest <tests> -q`
- After editing any `.py`, run `bandit -ll <file>` and fix Medium/High before commit.
- Every new `.py` starts with a `"""Title: … / Description: … / Changelog: …"""` header.
- **Commit** after each task with the message shown. Co-author trailer:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- Subagent reporting rule: only claim DONE with **pasted literal** ruff / radon / pytest output proving the gates pass.

---

## File Structure

- **Modify** `services/app/requirements.txt` + `services/app/pyproject.toml` — add `croniter`.
- **Modify** `services/app/analysis/models.py` — add `RecurringAnalysisSchedule`; add `recurring_rule` FK to `AnalysisSchedule`.
- **Create** `services/app/analysis/migrations/0010_recurringanalysisschedule_and_fk.py` (generated).
- **Create** `services/app/analysis/scheduling.py` — pure cron helpers (`next_runs`, `prev_fire`), no Django models, independently testable.
- **Modify** `services/app/analysis/management/commands/reconcile_vast_analysis.py` — add `_materialize_recurring()` + call it first in `handle()`.
- **Modify** `services/app/analysis/forms.py` — `RecurringAnalysisScheduleForm`.
- **Create** `services/app/analysis/views_schedule.py` — admin-gated page + actions + HTMX preview (mirrors `views_dashboard.py`).
- **Modify** `services/app/analysis/urls.py` — scheduling routes.
- **Create** `services/app/templates/analysis/scheduling.html` + `services/app/templates/analysis/_schedule_preview.html`.
- **Modify** `services/app/analysis/admin.py` — register `RecurringAnalysisSchedule`.
- **Create** tests: `test_scheduling_helpers.py`, `test_models_recurring.py`, `test_materialize_recurring.py`, `test_recurring_form.py`, `test_views_schedule.py`, `test_admin_recurring.py`, `test_scheduling_integration.py`.
- **Modify** `docs/superpowers/specs/2026-05-18-vast-scheduling-ui-design.md` — status note.

---

### Task 1: Add `croniter` dependency

**Files:**
- Modify: `services/app/requirements.txt`
- Modify: `services/app/pyproject.toml`
- Test: `services/app/analysis/tests/test_scheduling_helpers.py` (import-smoke only this task)

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_scheduling_helpers.py`:

```python
"""
Title: test_scheduling_helpers.py — cron helper + dependency tests
Description:
    Task 1: croniter import-smoke. Task 4 appends next_runs/prev_fire
    tests to this file.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.test import TestCase


class CroniterDependencyTests(TestCase):
    """croniter must be importable and validate expressions."""

    def test_croniter_importable_and_validates(self):
        """croniter is installed and its is_valid API works."""
        from croniter import croniter
        self.assertTrue(croniter.is_valid("0 2 * * 1"))
        self.assertFalse(croniter.is_valid("not a cron"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_scheduling_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'croniter'`.

- [ ] **Step 3: Add the dependency and install**

In `services/app/requirements.txt`, add this line (alphabetical-ish; place near the top app deps, before the Snyk-pinned block at the end):

```
croniter>=2.0.0
```

In `services/app/pyproject.toml`, inside the `dependencies = [` array (add after the `"httpx>=0.27.0",` line):

```
  "croniter>=2.0.0",
```

Install into the venv:
```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && \
source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && \
python -m pip install "croniter>=2.0.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest analysis/tests/test_scheduling_helpers.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/requirements.txt services/app/pyproject.toml services/app/analysis/tests/test_scheduling_helpers.py
git commit -m "feat(#155): add croniter dependency (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `RecurringAnalysisSchedule` model + `AnalysisSchedule.recurring_rule` FK

**Files:**
- Modify: `services/app/analysis/models.py` (append model; add FK field to existing `AnalysisSchedule`)
- Create: migration `0010_*` (via `makemigrations`)
- Test: `services/app/analysis/tests/test_models_recurring.py`

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_models_recurring.py`:

```python
"""
Title: test_models_recurring.py — RecurringAnalysisSchedule model
Description:
    crontab/timezone validation via clean(), max_jobs fallback,
    recurring_rule FK SET_NULL on rule delete.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from analysis.models import (
    AnalysisSchedule, RecurringAnalysisSchedule,
)


class RecurringModelTests(TestCase):
    """Validation, defaults, and FK behaviour."""

    def test_defaults(self):
        """A new rule is enabled with no last_materialized_at."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        self.assertTrue(r.enabled)
        self.assertIsNone(r.last_materialized_at)
        self.assertEqual(r.timezone, "UTC")

    def test_clean_rejects_bad_crontab(self):
        """An invalid crontab fails clean()."""
        r = RecurringAnalysisSchedule(name="x", crontab="nope")
        with self.assertRaises(ValidationError):
            r.full_clean()

    def test_clean_rejects_bad_timezone(self):
        """An unknown timezone fails clean()."""
        r = RecurringAnalysisSchedule(
            name="x", crontab="0 2 * * 1", timezone="Mars/Olympus")
        with self.assertRaises(ValidationError):
            r.full_clean()

    @override_settings(VAST_MAX_JOBS=100)
    def test_effective_max_jobs_fallback(self):
        """Null max_jobs falls back to settings.VAST_MAX_JOBS."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1", max_jobs=None)
        self.assertEqual(r.effective_max_jobs(), 100)
        r2 = RecurringAnalysisSchedule.objects.create(
            name="wk2", crontab="0 2 * * 1", max_jobs=7)
        self.assertEqual(r2.effective_max_jobs(), 7)

    def test_schedule_fk_set_null_on_rule_delete(self):
        """Deleting a rule nulls recurring_rule, keeps the schedule."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        s = AnalysisSchedule.objects.create(recurring_rule=r)
        r.delete()
        s.refresh_from_db()
        self.assertIsNone(s.recurring_rule)
        self.assertEqual(AnalysisSchedule.objects.count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_models_recurring.py -v`
Expected: FAIL — `ImportError: cannot import name 'RecurringAnalysisSchedule'`.

- [ ] **Step 3: Add the model + FK**

In `services/app/analysis/models.py`: append the `RecurringAnalysisSchedule` class at the END of the file, and add the `recurring_rule` field to the existing `AnalysisSchedule` class.

Add this field to `AnalysisSchedule` (immediately after its existing `note = models.TextField(null=True, blank=True)` line):

```python
    recurring_rule = models.ForeignKey(
        "RecurringAnalysisSchedule", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="materialized_schedules",
        help_text="Set when this row was materialized from a recurring "
                  "rule; null for one-offs.",
    )
```

Append at end of file:

```python
class RecurringAnalysisSchedule(models.Model):
    """A crontab rule that the reconcile cron materializes into
    `pending` AnalysisSchedule rows (issue #155 Sub-project B).

    The rule never launches anything itself; Step 0 of
    reconcile_vast_analysis turns a due rule into one pending schedule.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.CharField(max_length=128)
    crontab = models.CharField(
        max_length=128,
        help_text="5-field cron expression, e.g. '0 2 * * 1' (Mon 02:00).",
    )
    timezone = models.CharField(
        max_length=64, default="UTC",
        help_text="IANA tz name the crontab is evaluated in.",
    )
    enabled = models.BooleanField(default=True, db_index=True)
    max_jobs = models.IntegerField(
        null=True, blank=True,
        help_text="Per-run job cap; null → settings.VAST_MAX_JOBS.",
    )
    last_materialized_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "recurring_analysis_schedules"
        ordering = ["name"]
        verbose_name = "Recurring Analysis Schedule"
        verbose_name_plural = "Recurring Analysis Schedules"

    def __str__(self):
        """Return a human-readable identifier for this rule."""
        return f"RecurringAnalysisSchedule #{self.pk} [{self.name}]"

    def clean(self):
        """Validate the crontab expression and the timezone.

        Raises:
            ValidationError: when ``crontab`` is not a valid 5-field cron
                expression, or ``timezone`` is not a known IANA zone.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from croniter import croniter
        from django.core.exceptions import ValidationError

        if not croniter.is_valid(self.crontab or ""):
            raise ValidationError({"crontab": "Invalid cron expression."})
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            raise ValidationError({"timezone": "Unknown timezone."})

    def effective_max_jobs(self) -> int:
        """Return the job cap to use: explicit max_jobs or the setting.

        Returns:
            int: ``self.max_jobs`` when set, else
                ``django.conf.settings.VAST_MAX_JOBS``.
        """
        from django.conf import settings as _s
        return self.max_jobs if self.max_jobs is not None else _s.VAST_MAX_JOBS
```

- [ ] **Step 4: Make the migration**

Run:
```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && \
source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && \
python manage.py makemigrations analysis
```
Expected: creates `analysis/migrations/0010_*.py` with one `CreateModel` (RecurringAnalysisSchedule) + one `AddField` (AnalysisSchedule.recurring_rule). It must NOT alter any other model — if it does, STOP and report.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_models_recurring.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Verify gates + bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
ruff check analysis/models.py analysis/tests/test_models_recurring.py
radon cc analysis/models.py -s -n C
bandit -ll analysis/models.py
python manage.py makemigrations --check --dry-run analysis
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/models.py services/app/analysis/migrations/0010_*.py services/app/analysis/tests/test_models_recurring.py
git commit -m "feat(#155): RecurringAnalysisSchedule model + AnalysisSchedule FK (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
Gate pass: ruff clean; radon `-n C` empty; `--check` reports no changes; bandit clean. Add a `models.py` header-changelog line `2026-05-18: Add RecurringAnalysisSchedule + AnalysisSchedule.recurring_rule (#155 B).`

---

### Task 3: Cron helper module (`scheduling.py`)

**Files:**
- Create: `services/app/analysis/scheduling.py`
- Test: append to `services/app/analysis/tests/test_scheduling_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `services/app/analysis/tests/test_scheduling_helpers.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from analysis import scheduling


class NextRunsTests(TestCase):
    """next_runs returns upcoming fire times in the rule's tz."""

    def test_next_runs_weekly(self):
        """Weekly Monday 02:00 UTC yields Mondays at 02:00."""
        after = datetime(2026, 5, 18, 12, 0, tzinfo=ZoneInfo("UTC"))
        runs = scheduling.next_runs("0 2 * * 1", "UTC", 3, after=after)
        self.assertEqual(len(runs), 3)
        for dt in runs:
            self.assertEqual(dt.weekday(), 0)   # Monday
            self.assertEqual((dt.hour, dt.minute), (2, 0))
        self.assertTrue(runs[0] < runs[1] < runs[2])

    def test_next_runs_respects_timezone(self):
        """A non-UTC tz shifts the wall-clock fire time."""
        after = datetime(2026, 5, 18, 0, 0, tzinfo=ZoneInfo("UTC"))
        runs = scheduling.next_runs(
            "0 9 * * *", "America/New_York", 1, after=after)
        # 09:00 New York == 13:00 or 14:00 UTC depending on DST.
        self.assertIn(runs[0].astimezone(ZoneInfo("UTC")).hour, (13, 14))

    def test_next_runs_invalid_raises(self):
        """An invalid expression raises ValueError."""
        with self.assertRaises(ValueError):
            scheduling.next_runs("bogus", "UTC", 1)

    def test_prev_fire_before_now(self):
        """prev_fire returns the most recent fire <= the given instant."""
        now = datetime(2026, 5, 20, 3, 0, tzinfo=ZoneInfo("UTC"))  # Wed
        prev = scheduling.prev_fire("0 2 * * 1", "UTC", now)  # Mon 02:00
        self.assertEqual(prev.weekday(), 0)
        self.assertTrue(prev <= now)
        self.assertEqual((prev.hour, prev.minute), (2, 0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_scheduling_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analysis.scheduling'`.

- [ ] **Step 3: Implement the helper**

Create `services/app/analysis/scheduling.py`:

```python
"""
Title: scheduling.py — pure cron-expression helpers
Description:
    Timezone-aware wrappers over croniter used by Step 0 of the
    reconcile cron (prev_fire) and the scheduling UI (next_runs preview
    + future-planned table). No Django models; pure and unit-testable.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter


def _base(crontab: str, tz: str, anchor: datetime) -> croniter:
    """Return a croniter anchored at ``anchor`` in zone ``tz``.

    Args:
        crontab: 5-field cron expression.
        tz: IANA timezone name the expression is evaluated in.
        anchor: reference instant (tz-aware).

    Returns:
        croniter: iterator positioned at ``anchor`` in ``tz``.

    Raises:
        ValueError: if ``crontab`` is not a valid expression.
    """
    if not croniter.is_valid(crontab):
        raise ValueError(f"invalid cron expression: {crontab!r}")
    local = anchor.astimezone(ZoneInfo(tz))
    return croniter(crontab, local)


def next_runs(
    crontab: str, tz: str, count: int, *, after: datetime | None = None,
) -> list[datetime]:
    """Return the next ``count`` fire times strictly after ``after``.

    Args:
        crontab: 5-field cron expression.
        tz: IANA timezone name.
        count: how many upcoming times to return.
        after: instant to start from (tz-aware); defaults to now UTC.

    Returns:
        list[datetime]: ``count`` tz-aware datetimes in ``tz``, ascending.

    Raises:
        ValueError: if ``crontab`` is invalid.
    """
    anchor = after or datetime.now(ZoneInfo("UTC"))
    it = _base(crontab, tz, anchor)
    return [it.get_next(datetime) for _ in range(count)]


def prev_fire(crontab: str, tz: str, now: datetime) -> datetime:
    """Return the most recent fire time at or before ``now``.

    Args:
        crontab: 5-field cron expression.
        tz: IANA timezone name.
        now: reference instant (tz-aware).

    Returns:
        datetime: the tz-aware previous fire time (in ``tz``).

    Raises:
        ValueError: if ``crontab`` is invalid.
    """
    it = _base(crontab, tz, now)
    return it.get_prev(datetime)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_scheduling_helpers.py -v`
Expected: PASS (5 tests: 1 from Task 1 + 4 here).

- [ ] **Step 5: Verify gates + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
ruff check analysis/scheduling.py analysis/tests/test_scheduling_helpers.py
radon cc analysis/scheduling.py -s -n C
bandit -ll analysis/scheduling.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/scheduling.py services/app/analysis/tests/test_scheduling_helpers.py
git commit -m "feat(#155): cron helper module (next_runs/prev_fire) (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
Gate pass: ruff clean; radon `-n C` empty; bandit clean.

---

### Task 4: Step 0 — materialize due recurring rules

**Files:**
- Modify: `services/app/analysis/management/commands/reconcile_vast_analysis.py`
- Test: `services/app/analysis/tests/test_materialize_recurring.py`

Step-0 logic (spec "Recurrence → orchestrator integration"): for each **enabled** rule, `prev = scheduling.prev_fire(rule.crontab, rule.timezone, now)`; if `rule.last_materialized_at is None or prev > rule.last_materialized_at` → create `AnalysisSchedule(status=PENDING, recurring_rule=rule, max_jobs=rule.max_jobs)` and set `rule.last_materialized_at = now`. Per-rule `try/except` so one bad rule cannot break the run or other rules. Disabled rules skipped. Called **before** reap/launch, after the `VAST_ENABLED`/`VAST_API_KEY` gates.

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_materialize_recurring.py`:

```python
"""
Title: test_materialize_recurring.py — Step 0 of reconcile cron
Description:
    due→1 pending+stamp; not-due→none; disabled→skip; runner-down-
    across-N-occurrences→exactly one; failed prior run does NOT re-fire
    (Option A); bad crontab on one rule doesn't break others; Step 0
    runs before reap/launch.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from analysis.models import (
    AnalysisSchedule, RecurringAnalysisSchedule,
)
from analysis.management.commands.reconcile_vast_analysis import (
    _materialize_recurring,
)


@override_settings(VAST_MAX_JOBS=100)
class MaterializeRecurringTests(TestCase):
    """Step 0 turns due rules into exactly one pending schedule."""

    def test_due_rule_materializes_one_and_stamps(self):
        """A rule with no last_materialized_at and a past fire → 1 row."""
        r = RecurringAnalysisSchedule.objects.create(
            name="every-min", crontab="* * * * *", timezone="UTC")
        n = _materialize_recurring()
        self.assertEqual(n, 1)
        r.refresh_from_db()
        self.assertIsNotNone(r.last_materialized_at)
        sched = AnalysisSchedule.objects.get()
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_PENDING)
        self.assertEqual(sched.recurring_rule_id, r.id)

    def test_not_due_does_nothing(self):
        """last_materialized_at after the last fire → no new row."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1", timezone="UTC")
        r.last_materialized_at = timezone.now() + timedelta(days=400)
        r.save(update_fields=["last_materialized_at"])
        self.assertEqual(_materialize_recurring(), 0)
        self.assertEqual(AnalysisSchedule.objects.count(), 0)

    def test_disabled_rule_skipped(self):
        """A disabled rule never materializes or stamps."""
        RecurringAnalysisSchedule.objects.create(
            name="x", crontab="* * * * *", timezone="UTC", enabled=False)
        self.assertEqual(_materialize_recurring(), 0)
        self.assertEqual(AnalysisSchedule.objects.count(), 0)

    def test_coalesced_catch_up_one_run(self):
        """Runner down across many occurrences → exactly one make-up."""
        r = RecurringAnalysisSchedule.objects.create(
            name="hourly", crontab="0 * * * *", timezone="UTC")
        r.last_materialized_at = timezone.now() - timedelta(days=5)
        r.save(update_fields=["last_materialized_at"])
        self.assertEqual(_materialize_recurring(), 1)
        self.assertEqual(AnalysisSchedule.objects.count(), 1)
        # A second immediate tick must NOT add another (already stamped).
        self.assertEqual(_materialize_recurring(), 0)

    def test_failed_prior_run_does_not_refire(self):
        """A failed materialized run doesn't re-fire (Option A)."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1", timezone="UTC")
        _materialize_recurring()
        AnalysisSchedule.objects.update(
            status=AnalysisSchedule.STATUS_FAILED)
        self.assertEqual(_materialize_recurring(), 0)
        self.assertEqual(AnalysisSchedule.objects.count(), 1)

    def test_bad_crontab_isolated(self):
        """One un-parseable rule does not block a good rule."""
        RecurringAnalysisSchedule.objects.filter(pk__in=[]).delete()
        good = RecurringAnalysisSchedule.objects.create(
            name="good", crontab="* * * * *", timezone="UTC")
        # Force a stored-but-invalid crontab past clean() via update().
        bad = RecurringAnalysisSchedule.objects.create(
            name="bad", crontab="* * * * *", timezone="UTC")
        RecurringAnalysisSchedule.objects.filter(pk=bad.pk).update(
            crontab="totally-broken")
        n = _materialize_recurring()
        self.assertEqual(n, 1)
        self.assertEqual(
            AnalysisSchedule.objects.filter(
                recurring_rule_id=good.id).count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_materialize_recurring.py -v`
Expected: FAIL — `ImportError: cannot import name '_materialize_recurring'`.

- [ ] **Step 3: Implement Step 0**

In `services/app/analysis/management/commands/reconcile_vast_analysis.py`:

(a) Add to the import block (after `from analysis.services import vast_dispatch`):

```python
from analysis import scheduling
from analysis.models import RecurringAnalysisSchedule

_LOGGER = logging.getLogger(__name__)
```

…and add `import logging` to the top stdlib imports if not already present (place it with the other imports; if `_LOGGER` already exists in the module, do not redefine it).

(b) Add this module-level function (place it just above `def _reap_decision`):

```python
def _materialize_one(rule: RecurringAnalysisSchedule, now) -> int:
    """Materialize one pending schedule for ``rule`` if it is due.

    Due = the rule's most-recent fire <= now is strictly after its
    ``last_materialized_at`` (None counts as due). Stamps
    ``last_materialized_at = now`` after creating the row. Returns 1 if
    a row was created, else 0. A bad crontab is logged and skipped.
    """
    try:
        prev = scheduling.prev_fire(rule.crontab, rule.timezone, now)
    except (ValueError, KeyError) as exc:
        _LOGGER.warning(
            "recurring rule %s skipped (bad crontab/tz): %s",
            rule.pk, exc)
        return 0
    if rule.last_materialized_at is not None and \
            prev <= rule.last_materialized_at:
        return 0
    AnalysisSchedule.objects.create(
        status=AnalysisSchedule.STATUS_PENDING,
        recurring_rule=rule,
        max_jobs=rule.max_jobs,
    )
    rule.last_materialized_at = now
    rule.save(update_fields=["last_materialized_at"])
    return 1


def _materialize_recurring() -> int:
    """Step 0: materialize all due enabled recurring rules.

    Returns:
        int: number of pending schedules created this run.
    """
    now = timezone.now()
    created = 0
    for rule in RecurringAnalysisSchedule.objects.filter(enabled=True):
        created += _materialize_one(rule, now)
    return created
```

(c) In `handle()`, call Step 0 first — change the tail of `handle` from:

```python
        api_key = settings.VAST_API_KEY
        reaped = _reap(api_key)
        launched = _launch(api_key)
        self.stdout.write(
            f"vast reconcile done: reaped={reaped} launched={launched}")
```

to:

```python
        api_key = settings.VAST_API_KEY
        materialized = _materialize_recurring()
        reaped = _reap(api_key)
        launched = _launch(api_key)
        self.stdout.write(
            "vast reconcile done: "
            f"materialized={materialized} reaped={reaped} "
            f"launched={launched}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_materialize_recurring.py analysis/tests/test_reconcile_vast_gating.py analysis/tests/test_reconcile_vast_reap.py analysis/tests/test_reconcile_vast_launch.py analysis/tests/test_reconcile_vast_integration.py -q`
Expected: all PASS (6 new + the existing reconcile suite — no regression).

- [ ] **Step 5: Verify gates + bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
ruff check analysis/management/commands/reconcile_vast_analysis.py analysis/tests/test_materialize_recurring.py
radon cc analysis/management/commands/reconcile_vast_analysis.py -s -n C
bandit -ll analysis/management/commands/reconcile_vast_analysis.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/management/commands/reconcile_vast_analysis.py services/app/analysis/tests/test_materialize_recurring.py
git commit -m "feat(#155): Step 0 — materialize due recurring rules (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
Gate pass: ruff clean; radon `-n C` empty (each of `_materialize_one`/`_materialize_recurring` ≤ grade B); bandit clean. **Do not** modify `_reap`/`_launch`/`Command` reap-launch logic.

---

### Task 5: Rule form

**Files:**
- Modify: `services/app/analysis/forms.py`
- Test: `services/app/analysis/tests/test_recurring_form.py`

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_recurring_form.py`:

```python
"""
Title: test_recurring_form.py — RecurringAnalysisScheduleForm
Description:
    Valid input saves; invalid crontab and invalid timezone are
    rejected with field errors (mirrors model clean()).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.test import TestCase

from analysis.forms import RecurringAnalysisScheduleForm


class RecurringFormTests(TestCase):
    """Form validation mirrors model clean()."""

    def test_valid_form_saves(self):
        """A valid crontab + tz produces a saved rule."""
        form = RecurringAnalysisScheduleForm(data={
            "name": "Weekly Mon 02:00", "crontab": "0 2 * * 1",
            "timezone": "UTC", "max_jobs": "", "note": ""})
        self.assertTrue(form.is_valid(), form.errors.as_json())
        obj = form.save()
        self.assertEqual(obj.crontab, "0 2 * * 1")

    def test_invalid_crontab_rejected(self):
        """A bad crontab yields a crontab field error."""
        form = RecurringAnalysisScheduleForm(data={
            "name": "x", "crontab": "nope", "timezone": "UTC"})
        self.assertFalse(form.is_valid())
        self.assertIn("crontab", form.errors)

    def test_invalid_timezone_rejected(self):
        """A bad timezone yields a timezone field error."""
        form = RecurringAnalysisScheduleForm(data={
            "name": "x", "crontab": "0 2 * * 1",
            "timezone": "Nowhere/Land"})
        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_recurring_form.py -v`
Expected: FAIL — `ImportError: cannot import name 'RecurringAnalysisScheduleForm'`.

- [ ] **Step 3: Implement the form**

In `services/app/analysis/forms.py`, after the existing header docstring, add (and a changelog line `2026-05-18: Add RecurringAnalysisScheduleForm (#155 B).` to the header):

```python
from django import forms

from .models import RecurringAnalysisSchedule


class RecurringAnalysisScheduleForm(forms.ModelForm):
    """Create/edit form for a recurring analysis rule.

    Field-level validation is delegated to the model's ``clean()`` via
    ``ModelForm`` (``_post_clean`` calls ``instance.full_clean``), so an
    invalid crontab/timezone surfaces as a bound field error.
    """

    class Meta:
        model = RecurringAnalysisSchedule
        fields = ["name", "crontab", "timezone", "max_jobs", "note",
                  "enabled"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
        }
```

Note: `ModelForm._post_clean()` runs `instance.full_clean()` which calls the model `clean()` from Task 2; its `ValidationError({"crontab": ...})` / `{"timezone": ...}` become bound field errors automatically — no duplicate validation needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest analysis/tests/test_recurring_form.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Verify gates + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
ruff check analysis/forms.py analysis/tests/test_recurring_form.py
radon cc analysis/forms.py -s -n C
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/forms.py services/app/analysis/tests/test_recurring_form.py
git commit -m "feat(#155): RecurringAnalysisScheduleForm (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Admin-gated views + URLs

**Files:**
- Create: `services/app/analysis/views_schedule.py`
- Modify: `services/app/analysis/urls.py`
- Test: `services/app/analysis/tests/test_views_schedule.py`

Views (all wrapped with `_admin_login_required` imported from `analysis.views`):
- `scheduling_page` (GET) — renders `analysis/scheduling.html` with: rules, future-planned rows, recent-runs rows, an empty `RecurringAnalysisScheduleForm`.
- `rule_create` (POST) — validate + save form → redirect back; on error re-render page with bound form.
- `rule_edit` (POST, `<int:pk>`) — bind to instance, save → redirect.
- `rule_delete` (POST, `<int:pk>`) — delete rule → redirect.
- `rule_toggle` (POST, `<int:pk>`) — flip `enabled` → redirect.
- `run_once` (POST) — `AnalysisSchedule.objects.create(status=PENDING)` → redirect.
- `rerun` (POST, `<int:pk>`) — create a fresh one-off `AnalysisSchedule(status=PENDING)` (copying `max_jobs` from the source schedule) → redirect.
- `preview` (GET) — HTMX partial: `?crontab=&timezone=` → render `_schedule_preview.html` with next 3 runs or an error string.

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_views_schedule.py`:

```python
"""
Title: test_views_schedule.py — scheduling page + actions
Description:
    _admin_login_required gating; rule CRUD/toggle; run-once; re-run;
    tables render; HTMX preview ok + error.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

import uuid

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from analysis.models import (
    AnalysisInstance, AnalysisSchedule, RecurringAnalysisSchedule,
)


def _user(role: str) -> User:
    return User.objects.create_user(
        email=f"{role}-{uuid.uuid4().hex[:6]}@test",
        password="x",  # noqa: S106 — test-only
        role=role)


class SchedulingGatingTests(TestCase):
    """_admin_login_required protects every scheduling endpoint."""

    def test_anonymous_redirected(self):
        """Anonymous GET → login redirect (302)."""
        resp = self.client.get(reverse("analysis:scheduling"))
        self.assertEqual(resp.status_code, 302)

    def test_non_admin_forbidden(self):
        """Authenticated non-admin → not 200 (403/redirect)."""
        self.client.force_login(_user("player"))
        resp = self.client.get(reverse("analysis:scheduling"))
        self.assertNotEqual(resp.status_code, 200)

    def test_admin_ok(self):
        """Admin GET → 200 and the page renders."""
        self.client.force_login(_user("admin"))
        resp = self.client.get(reverse("analysis:scheduling"))
        self.assertEqual(resp.status_code, 200)


class SchedulingActionsTests(TestCase):
    """CRUD, run-once, re-run, preview."""

    def setUp(self):
        self.client.force_login(_user("admin"))

    def test_rule_create_valid(self):
        """Posting a valid rule creates it and redirects."""
        resp = self.client.post(reverse("analysis:rule_create"), {
            "name": "wk", "crontab": "0 2 * * 1", "timezone": "UTC",
            "max_jobs": "", "note": "", "enabled": "on"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(RecurringAnalysisSchedule.objects.count(), 1)

    def test_rule_create_invalid_crontab_no_save(self):
        """An invalid crontab does not create a rule (page re-renders)."""
        resp = self.client.post(reverse("analysis:rule_create"), {
            "name": "x", "crontab": "bad", "timezone": "UTC"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RecurringAnalysisSchedule.objects.count(), 0)

    def test_rule_toggle(self):
        """Toggle flips enabled."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        self.client.post(reverse("analysis:rule_toggle", args=[r.pk]))
        r.refresh_from_db()
        self.assertFalse(r.enabled)

    def test_rule_delete(self):
        """Delete removes the rule."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        self.client.post(reverse("analysis:rule_delete", args=[r.pk]))
        self.assertEqual(RecurringAnalysisSchedule.objects.count(), 0)

    def test_run_once_creates_pending(self):
        """Run-once creates a one-off pending schedule (no rule)."""
        self.client.post(reverse("analysis:run_once"))
        s = AnalysisSchedule.objects.get()
        self.assertEqual(s.status, AnalysisSchedule.STATUS_PENDING)
        self.assertIsNone(s.recurring_rule)

    def test_rerun_creates_new_pending(self):
        """Re-run creates a fresh pending one-off copying max_jobs."""
        src = AnalysisSchedule.objects.create(
            status=AnalysisSchedule.STATUS_FAILED, max_jobs=55)
        self.client.post(reverse("analysis:rerun", args=[src.pk]))
        new = AnalysisSchedule.objects.exclude(pk=src.pk).get()
        self.assertEqual(new.status, AnalysisSchedule.STATUS_PENDING)
        self.assertEqual(new.max_jobs, 55)

    def test_recent_and_future_tables_render(self):
        """A terminal run shows in recent; an enabled rule in future."""
        RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        sched = AnalysisSchedule.objects.create(
            status=AnalysisSchedule.STATUS_DONE)
        AnalysisInstance.objects.create(
            schedule=sched, status=AnalysisInstance.STATUS_DESTROYED,
            vast_instance_id="42", offer_dph=0.9)
        body = self.client.get(
            reverse("analysis:scheduling")).content.decode()
        self.assertIn("wk", body)
        self.assertIn("42", body)

    def test_preview_ok(self):
        """Preview returns next runs for a valid expression."""
        resp = self.client.get(reverse("analysis:schedule_preview"), {
            "crontab": "0 2 * * 1", "timezone": "UTC"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Invalid", resp.content.decode())

    def test_preview_invalid_graceful(self):
        """Preview shows an error string, not a 500, on bad input."""
        resp = self.client.get(reverse("analysis:schedule_preview"), {
            "crontab": "bogus", "timezone": "UTC"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Invalid", resp.content.decode())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_views_schedule.py -v`
Expected: FAIL — `NoReverseMatch` / view module missing.

- [ ] **Step 3: Implement views + URLs**

Create `services/app/analysis/views_schedule.py`:

```python
"""
Title: views_schedule.py — admin scheduling page (issue #155 B)
Description:
    _admin_login_required page to manage RecurringAnalysisSchedule
    rules and one-off runs, plus "recent runs" / "future planned runs"
    tables and an HTMX cron preview. Produces pending AnalysisSchedule
    rows that Sub-project A's reconcile cron consumes.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import RecurringAnalysisScheduleForm
from .models import (
    AnalysisInstance, AnalysisSchedule, RecurringAnalysisSchedule,
)
from . import scheduling
from .views import _admin_login_required

_PREVIEW_COUNT = 3


def _future_rows() -> list[dict]:
    """Next occurrence per enabled rule + non-terminal one-offs."""
    rows: list[dict] = []
    for rule in RecurringAnalysisSchedule.objects.filter(enabled=True):
        try:
            nxt = scheduling.next_runs(
                rule.crontab, rule.timezone, 1)[0]
        except (ValueError, KeyError):
            continue
        rows.append({"when": nxt, "source": rule.name,
                     "max_jobs": rule.effective_max_jobs(),
                     "status": "scheduled"})
    pend = AnalysisSchedule.objects.filter(
        status__in=[AnalysisSchedule.STATUS_PENDING,
                    AnalysisSchedule.STATUS_RUNNING]
    ).select_related("recurring_rule")
    for s in pend:
        rows.append({
            "when": s.created_at,
            "source": s.recurring_rule.name if s.recurring_rule
            else "one-off",
            "max_jobs": s.max_jobs, "status": s.status})
    return rows


def _recent_rows(limit: int = 50) -> list[dict]:
    """Terminal schedules joined to their latest instance."""
    qs = (AnalysisSchedule.objects
          .filter(status__in=[AnalysisSchedule.STATUS_DONE,
                              AnalysisSchedule.STATUS_FAILED])
          .select_related("recurring_rule")
          .order_by("-created_at")[:limit])
    rows: list[dict] = []
    for s in qs:
        inst = (AnalysisInstance.objects
                .filter(schedule=s).order_by("-created_at").first())
        rows.append({
            "id": s.id,
            "when": s.created_at,
            "source": (s.recurring_rule.name if s.recurring_rule
                       else "one-off"),
            "status": s.status,
            "failed": s.status == AnalysisSchedule.STATUS_FAILED,
            "instance_id": inst.vast_instance_id if inst else None,
            "offer_dph": inst.offer_dph if inst else None,
        })
    return rows


def _render_page(request: HttpRequest,
                 form: RecurringAnalysisScheduleForm,
                 status: int = 200) -> HttpResponse:
    """Render the scheduling page with all sections."""
    ctx = {
        "form": form,
        "rules": RecurringAnalysisSchedule.objects.all(),
        "future_rows": _future_rows(),
        "recent_rows": _recent_rows(),
    }
    return render(request, "analysis/scheduling.html", ctx, status=status)


@_admin_login_required
@require_GET
def scheduling_page(request: HttpRequest) -> HttpResponse:
    """Render the scheduling admin page."""
    return _render_page(request, RecurringAnalysisScheduleForm())


@_admin_login_required
@require_POST
def rule_create(request: HttpRequest) -> HttpResponse:
    """Create a recurring rule, or re-render with errors."""
    form = RecurringAnalysisScheduleForm(request.POST)
    if form.is_valid():
        form.save()
        return redirect("analysis:scheduling")
    return _render_page(request, form, status=200)


@_admin_login_required
@require_POST
def rule_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit an existing rule, or re-render with errors."""
    rule = get_object_or_404(RecurringAnalysisSchedule, pk=pk)
    form = RecurringAnalysisScheduleForm(request.POST, instance=rule)
    if form.is_valid():
        form.save()
        return redirect("analysis:scheduling")
    return _render_page(request, form, status=200)


@_admin_login_required
@require_POST
def rule_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete a rule (history rows keep, FK SET_NULL)."""
    get_object_or_404(RecurringAnalysisSchedule, pk=pk).delete()
    return redirect("analysis:scheduling")


@_admin_login_required
@require_POST
def rule_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    """Flip a rule's enabled flag."""
    rule = get_object_or_404(RecurringAnalysisSchedule, pk=pk)
    rule.enabled = not rule.enabled
    rule.save(update_fields=["enabled", "updated_at"])
    return redirect("analysis:scheduling")


@_admin_login_required
@require_POST
def run_once(request: HttpRequest) -> HttpResponse:
    """Create a one-off pending schedule (next-tick launch)."""
    AnalysisSchedule.objects.create(
        status=AnalysisSchedule.STATUS_PENDING)
    return redirect("analysis:scheduling")


@_admin_login_required
@require_POST
def rerun(request: HttpRequest, pk: int) -> HttpResponse:
    """Create a fresh one-off copying the source's max_jobs."""
    src = get_object_or_404(AnalysisSchedule, pk=pk)
    AnalysisSchedule.objects.create(
        status=AnalysisSchedule.STATUS_PENDING, max_jobs=src.max_jobs)
    return redirect("analysis:scheduling")


@_admin_login_required
@require_GET
def schedule_preview(request: HttpRequest) -> HttpResponse:
    """HTMX partial: next runs for a candidate crontab, or an error."""
    crontab = request.GET.get("crontab", "")
    tz = request.GET.get("timezone", "UTC")
    error = None
    runs: list = []
    try:
        runs = scheduling.next_runs(crontab, tz, _PREVIEW_COUNT)
    except (ValueError, KeyError):
        error = "Invalid cron expression or timezone."
    return render(request, "analysis/_schedule_preview.html",
                  {"runs": runs, "error": error})
```

In `services/app/analysis/urls.py`: add `views_schedule` to the `from . import ...` line and append these patterns to `urlpatterns` (before the diagnostics redirect):

```python
    path("schedule/", views_schedule.scheduling_page, name="scheduling"),
    path("schedule/rule/new/", views_schedule.rule_create,
         name="rule_create"),
    path("schedule/rule/<int:pk>/edit/", views_schedule.rule_edit,
         name="rule_edit"),
    path("schedule/rule/<int:pk>/delete/", views_schedule.rule_delete,
         name="rule_delete"),
    path("schedule/rule/<int:pk>/toggle/", views_schedule.rule_toggle,
         name="rule_toggle"),
    path("schedule/run-once/", views_schedule.run_once, name="run_once"),
    path("schedule/<int:pk>/rerun/", views_schedule.rerun, name="rerun"),
    path("schedule/preview/", views_schedule.schedule_preview,
         name="schedule_preview"),
```

(Update the `from . import views, views_dashboard, views_queue` line to also import `views_schedule`, and add a urls.py changelog line `2026-05-18: Add /schedule/ routes (#155 B).`)

- [ ] **Step 4: Run tests** — they will still fail on missing templates (Task 7). Run only the gating + action-logic tests that don't need template body assertions:

Run: `python -m pytest analysis/tests/test_views_schedule.py -v -k "not tables_render and not admin_ok and not preview and not invalid_crontab_no_save"`
Expected: PASS for create/toggle/delete/run_once/rerun/anonymous/non_admin (redirect-based, no template body). The template-dependent tests pass after Task 7.

- [ ] **Step 5: Verify gates + bandit + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
ruff check analysis/views_schedule.py analysis/urls.py analysis/tests/test_views_schedule.py
radon cc analysis/views_schedule.py -s -n C
bandit -ll analysis/views_schedule.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/views_schedule.py services/app/analysis/urls.py services/app/analysis/tests/test_views_schedule.py
git commit -m "feat(#155): scheduling views + URLs (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
Gate pass: ruff clean; radon `-n C` empty (helpers `_future_rows`/`_recent_rows`/`_render_page` keep each view tiny — if any function trips grade C, split it further); bandit clean.

---

### Task 7: Templates

**Files:**
- Create: `services/app/templates/analysis/scheduling.html`
- Create: `services/app/templates/analysis/_schedule_preview.html`
- Test: (the full `test_views_schedule.py` now passes end-to-end)

- [ ] **Step 1: Create `services/app/templates/analysis/scheduling.html`**

```html
{% extends "base.html" %}
{% comment %}
  Title: scheduling.html — analysis scheduling admin page (#155 B)
  Description: Recurring-rule CRUD + run-once, plus "future planned runs"
      and "recent runs" tables. Data-dense admin tables use
      .wc-table .wc-table--zebra (no .pg-table).
  Changelog:
      2026-05-18: Initial — issue #155 Sub-project B.
{% endcomment %}
{% block title %}Analysis Scheduling{% endblock %}
{% block content %}
<section class="pg-section">
  <h1>Analysis Scheduling</h1>

  <h2>Recurring rules</h2>
  <table class="wc-table wc-table--zebra">
    <thead><tr><th>Name</th><th>Crontab</th><th>TZ</th>
      <th>Max jobs</th><th>Enabled</th><th>Actions</th></tr></thead>
    <tbody>
    {% for r in rules %}
      <tr>
        <td>{{ r.name }}</td><td><code>{{ r.crontab }}</code></td>
        <td>{{ r.timezone }}</td><td>{{ r.max_jobs|default:"—" }}</td>
        <td>{{ r.enabled|yesno:"yes,no" }}</td>
        <td>
          <form method="post"
                action="{% url 'analysis:rule_toggle' r.pk %}"
                style="display:inline">{% csrf_token %}
            <button type="submit">{{ r.enabled|yesno:"Disable,Enable" }}</button>
          </form>
          <form method="post"
                action="{% url 'analysis:rule_delete' r.pk %}"
                style="display:inline">{% csrf_token %}
            <button type="submit">Delete</button>
          </form>
        </td>
      </tr>
    {% empty %}
      <tr><td colspan="6">No rules yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2>New rule</h2>
  <form method="post" action="{% url 'analysis:rule_create' %}">
    {% csrf_token %}
    {{ form.as_p }}
    <div id="cron-preview"
         hx-get="{% url 'analysis:schedule_preview' %}"
         hx-trigger="load, change from:#id_crontab,
                     change from:#id_timezone"
         hx-include="#id_crontab,#id_timezone">
    </div>
    <button type="submit">Create rule</button>
  </form>

  <form method="post" action="{% url 'analysis:run_once' %}">
    {% csrf_token %}
    <button type="submit">Run once now</button>
  </form>

  <h2>Future planned runs</h2>
  <table class="wc-table wc-table--zebra">
    <thead><tr><th>When</th><th>Source</th><th>Max jobs</th>
      <th>Status</th></tr></thead>
    <tbody>
    {% for row in future_rows %}
      <tr><td>{{ row.when }}</td><td>{{ row.source }}</td>
        <td>{{ row.max_jobs|default:"—" }}</td>
        <td>{{ row.status }}</td></tr>
    {% empty %}
      <tr><td colspan="4">Nothing scheduled.</td></tr>
    {% endfor %}
    </tbody>
  </table>

  <h2>Recent runs</h2>
  <table class="wc-table wc-table--zebra">
    <thead><tr><th>When</th><th>Source</th><th>Status</th>
      <th>Instance</th><th>$/hr</th><th></th></tr></thead>
    <tbody>
    {% for row in recent_rows %}
      <tr{% if row.failed %} class="wc-row--danger"{% endif %}>
        <td>{{ row.when }}</td><td>{{ row.source }}</td>
        <td>{{ row.status }}</td>
        <td>{{ row.instance_id|default:"—" }}</td>
        <td>{{ row.offer_dph|default:"—" }}</td>
        <td>
          <form method="post"
                action="{% url 'analysis:rerun' row.id %}"
                style="display:inline">{% csrf_token %}
            <button type="submit">Re-run</button>
          </form>
        </td>
      </tr>
    {% empty %}
      <tr><td colspan="6">No runs yet.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

- [ ] **Step 2: Create `services/app/templates/analysis/_schedule_preview.html`**

```html
{% comment %}HTMX partial: next-runs preview for a candidate rule.{% endcomment %}
{% if error %}
  <p class="wc-text--danger">Invalid: {{ error }}</p>
{% else %}
  <p>Next runs:</p>
  <ul>
    {% for dt in runs %}<li>{{ dt }}</li>{% endfor %}
  </ul>
{% endif %}
```

- [ ] **Step 3: Run the full view suite**

Run: `python -m pytest analysis/tests/test_views_schedule.py -v`
Expected: PASS (all tests, including the previously template-dependent ones). `test_preview_invalid_graceful` asserts the page contains "Invalid" — supplied by `_schedule_preview.html`.

- [ ] **Step 4: Verify gates + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
ruff check analysis/tests/test_views_schedule.py
python -m pytest analysis/tests/test_views_schedule.py -q
cd /Users/christopherwebster/Projects/wood_league
git add services/app/templates/analysis/scheduling.html services/app/templates/analysis/_schedule_preview.html
git commit -m "feat(#155): scheduling page templates (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Tailwind note** — these templates only use existing utility classes (`.wc-table`, `.wc-table--zebra`, `.pg-section`, `.wc-row--danger`, `.wc-text--danger`). If `wc-row--danger`/`wc-text--danger` are not already defined in the compiled CSS, substitute the nearest existing "danger/red" utility found in `templates/analysis/_dash_failures.html` (inspect it) rather than hand-editing `tailwind.css` (it is a build artifact — never hand-edit; rebuild via `services/app/bin/build_tailwind.sh` only if a genuinely new class is required, and call that out in the commit).

---

### Task 8: Register `RecurringAnalysisSchedule` in admin

**Files:**
- Modify: `services/app/analysis/admin.py`
- Test: `services/app/analysis/tests/test_admin_recurring.py`

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_admin_recurring.py`:

```python
"""
Title: test_admin_recurring.py — admin registration for the rule model
Description:
    RecurringAnalysisSchedule must be registered (operator fallback).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.contrib import admin
from django.test import TestCase

from analysis.models import RecurringAnalysisSchedule


class RecurringAdminTests(TestCase):
    """The rule model is registered in Django admin."""

    def test_registered(self):
        """RecurringAnalysisSchedule appears in the admin registry."""
        self.assertTrue(
            admin.site.is_registered(RecurringAnalysisSchedule))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest analysis/tests/test_admin_recurring.py -v`
Expected: FAIL — `AssertionError: False is not true`.

- [ ] **Step 3: Register in admin**

In `services/app/analysis/admin.py`: add `RecurringAnalysisSchedule` to the `.models` import line and append (and add a header changelog line `2026-05-18: Register RecurringAnalysisSchedule (#155 B).`):

```python
@admin.register(RecurringAnalysisSchedule)
class RecurringAnalysisScheduleAdmin(admin.ModelAdmin):
    """Operator fallback for editing recurring rules."""

    list_display = ("id", "name", "crontab", "timezone", "enabled",
                    "max_jobs", "last_materialized_at")
    list_filter = ("enabled",)
    readonly_fields = ("created_at", "updated_at", "last_materialized_at")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest analysis/tests/test_admin_recurring.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Verify gates + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
ruff check analysis/admin.py analysis/tests/test_admin_recurring.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/admin.py services/app/analysis/tests/test_admin_recurring.py
git commit -m "feat(#155): register RecurringAnalysisSchedule in admin (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: End-to-end integration + final verification

**Files:**
- Test: `services/app/analysis/tests/test_scheduling_integration.py`
- Modify: `docs/superpowers/specs/2026-05-18-vast-scheduling-ui-design.md` (status note)

- [ ] **Step 1: Write the integration test**

Create `services/app/analysis/tests/test_scheduling_integration.py`:

```python
"""
Title: test_scheduling_integration.py — B→A composition
Description:
    A rule created via the admin page → reconcile Step 0 materializes a
    pending AnalysisSchedule → A's launch (vast mocked) consumes it.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

import uuid
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from analysis.models import (
    AnalysisInstance, AnalysisSchedule, RecurringAnalysisSchedule,
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
class SchedulingToOrchestratorTests(TestCase):
    """A UI-created rule flows through Step 0 into A's launch."""

    def test_rule_materializes_then_launches(self):
        admin = User.objects.create_user(
            email=f"a-{uuid.uuid4().hex[:6]}@test",
            password="x", role="admin")  # noqa: S106
        self.client.force_login(admin)

        # Create an always-due rule through the real admin page.
        self.client.post(reverse("analysis:rule_create"), {
            "name": "min", "crontab": "* * * * *", "timezone": "UTC",
            "max_jobs": "", "note": "", "enabled": "on"})
        self.assertEqual(RecurringAnalysisSchedule.objects.count(), 1)

        # Reconcile tick: Step 0 materializes, A's launch consumes it.
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_OK), \
             patch(_P + "destroy_instance", return_value=DESTROY_OK), \
             patch(_P + "list_instances", return_value=[]):
            call_command("reconcile_vast_analysis", stdout=StringIO())

        sched = AnalysisSchedule.objects.get()
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_RUNNING)
        self.assertIsNotNone(sched.recurring_rule)
        inst = AnalysisInstance.objects.get()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)
        self.assertEqual(inst.vast_instance_id, "98765")
```

- [ ] **Step 2: Run + full B suite + A regression**

Run:
```bash
python -m pytest analysis/tests/test_scheduling_integration.py analysis/tests/test_scheduling_helpers.py analysis/tests/test_models_recurring.py analysis/tests/test_materialize_recurring.py analysis/tests/test_recurring_form.py analysis/tests/test_views_schedule.py analysis/tests/test_admin_recurring.py analysis/tests/test_vast_dispatch.py analysis/tests/test_models_vast.py analysis/tests/test_admin_vast.py analysis/tests/test_reconcile_vast_gating.py analysis/tests/test_reconcile_vast_reap.py analysis/tests/test_reconcile_vast_launch.py analysis/tests/test_reconcile_vast_integration.py -q
```
Expected: all PASS (B suite + A suite — no regression).

- [ ] **Step 3: Update spec status note**

In `docs/superpowers/specs/2026-05-18-vast-scheduling-ui-design.md`, change the header `**Status:** Draft (2026-05-18)` to `**Status:** Implemented (2026-05-18) — see plan 2026-05-18-vast-scheduling-ui-B.md`.

- [ ] **Step 4: Final verification**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
ruff check analysis/ --exclude migrations
radon cc analysis/scheduling.py analysis/views_schedule.py analysis/management/commands/reconcile_vast_analysis.py -s -n C
python manage.py makemigrations --check --dry-run analysis
bandit -ll analysis/views_schedule.py analysis/scheduling.py analysis/management/commands/reconcile_vast_analysis.py
```
Expected: ruff clean; radon `-n C` empty; `--check` "No changes detected"; bandit clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/analysis/tests/test_scheduling_integration.py docs/superpowers/specs/2026-05-18-vast-scheduling-ui-design.md
git commit -m "test(#155): B→A scheduling integration + spec status (Sub-project B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** `RecurringAnalysisSchedule` model + `recurring_rule` FK (T2); Step-0 materialization with coalesced catch-up + Option-A no-refire + bad-rule isolation + disabled-skip + ordering-before-reap (T4); cron validation in model `clean()` + form (T2/T5); admin-gated page with rule CRUD/toggle, run-once, re-run, future + recent tables, HTMX next-runs preview (T6/T7); croniter dependency (T1); cron helper module (T3); admin registration (T8); B→A integration (T9). Every spec section maps to a task. Out-of-scope items (no A reap/launch change, no engine/campaign selection, no notifications) are respected — Step 0 only creates pending rows; `_reap`/`_launch` untouched.
- **Placeholder scan:** none — every code step is complete and runnable; the only deferred item is the Task 7 CSS-class fallback, which gives an explicit inspect-and-substitute instruction (not a TODO).
- **Type consistency:** `RecurringAnalysisSchedule` fields (`crontab`, `timezone`, `enabled`, `max_jobs`, `last_materialized_at`), `effective_max_jobs()`, `AnalysisSchedule.recurring_rule` / `recurring_rule_id` / related_name `materialized_schedules`, `scheduling.next_runs(crontab, tz, count, *, after=)` / `scheduling.prev_fire(crontab, tz, now)`, and `_materialize_recurring()` / `_materialize_one(rule, now)` are used identically across model, command, views, and tests. URL names (`analysis:scheduling`, `rule_create`, `rule_edit`, `rule_delete`, `rule_toggle`, `run_once`, `rerun`, `schedule_preview`) match between `urls.py`, views, templates, and tests.
