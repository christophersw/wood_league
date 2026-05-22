# Auto-enqueue Env Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make post-ingest auto-enqueue work reliably, driven by Railway env vars, with detection that no longer depends on the unstamped `created_at` column.

**Architecture:** Replace the DB-backed `SiteSettings` toggles with env-only Django settings (`AUTO_ENQUEUE_STOCKFISH`/`AUTO_ENQUEUE_LC0`, both default `False`). Replace the broken `created_at__gte=started_at` "new games" filter in the `sync_games` command with a sweep that enqueues any PGN game lacking an active or deep-enough completed `AnalysisJob`, reusing the existing race-safe `enqueue_analysis_job`.

**Tech Stack:** Django 5, python-decouple (`config`), pytest / pytest-django, PostgreSQL.

**Ordering note:** Settings are added first; `sync_games` is rewritten to read settings (and stop referencing `SiteSettings.auto_enqueue_*`) **before** the DB fields are removed. This keeps the test suite green at every commit.

**Spec:** `docs/superpowers/specs/2026-05-22-auto-enqueue-env-fix-design.md`

---

## Conventions for every test command

All test/lint commands assume the repo venv is active and you are in the Django project dir:

```bash
cd /Users/christopherwebster/Projects/wood_league && source .venv/bin/activate && cd services/app
```

Per `services/app/CLAUDE.md`, after editing any `.py` file run `bandit -ll <file>` and fix Medium/High findings before committing.

---

## File Structure

- `services/app/config/settings.py` — **Modify:** add the two env-read booleans.
- `services/app/core/tests/test_settings.py` — **Create:** assert the settings exist, are bools, default `False`.
- `services/app/ingest/management/commands/sync_games.py` — **Modify:** read env toggles, replace `created_at` filter with sweep, drop `SiteSettings`/`started_at`/`timezone` usage.
- `services/app/ingest/tests/test_sync_games_command.py` — **Modify:** drive enqueue via `override_settings`; add sweep/dedup/off-by-default tests.
- `services/app/core/models.py` — **Modify:** remove the two `BooleanField`s.
- `services/app/core/admin.py` — **Modify:** drop the two fields from `list_display`.
- `services/app/core/migrations/0002_*.py` — **Create (via makemigrations):** `RemoveField` ×2.
- `services/app/core/tests/test_models.py` — **Modify:** replace the default-toggles test with a "fields are gone" guard.

---

## Task 1: Add env-only auto-enqueue settings

**Files:**
- Modify: `services/app/config/settings.py` (near lines 217-218, the existing engine settings)
- Test: `services/app/core/tests/test_settings.py` (create)

- [ ] **Step 1: Write the failing test**

Create `services/app/core/tests/test_settings.py`:

```python
"""
Title: test_settings.py — Auto-enqueue env setting wiring
Description: Verify AUTO_ENQUEUE_STOCKFISH / AUTO_ENQUEUE_LC0 exist on Django
    settings, are booleans, and default to False when their env vars are unset.
Changelog:
    2026-05-22: Initial — issue #201 (env-only auto-enqueue toggles).
"""
from django.conf import settings


def test_auto_enqueue_settings_exist_and_are_bool():
    """Both toggles must be present and boolean-typed."""
    assert isinstance(settings.AUTO_ENQUEUE_STOCKFISH, bool)
    assert isinstance(settings.AUTO_ENQUEUE_LC0, bool)


def test_auto_enqueue_settings_default_false():
    """With the env vars unset (test environment), both default to False."""
    assert settings.AUTO_ENQUEUE_STOCKFISH is False
    assert settings.AUTO_ENQUEUE_LC0 is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/test_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'AUTO_ENQUEUE_STOCKFISH'`.

- [ ] **Step 3: Add the settings**

In `services/app/config/settings.py`, immediately after the existing
`LC0_NODES = config(...)` line (currently line 218), add:

```python
# Auto-enqueue toggles (issue #201): env-only, opt-in, both default off.
# Set on the Railway `wood_league_cron` service to enable per engine at runtime.
AUTO_ENQUEUE_STOCKFISH = config("AUTO_ENQUEUE_STOCKFISH", default=False, cast=bool)
AUTO_ENQUEUE_LC0 = config("AUTO_ENQUEUE_LC0", default=False, cast=bool)
```

(`config` is already imported at the top: `from decouple import Csv, config`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest core/tests/test_settings.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
bandit -ll config/settings.py
git add config/settings.py core/tests/test_settings.py
git commit -m "feat(#201): add env-only AUTO_ENQUEUE_STOCKFISH/LC0 settings (default off)"
```

---

## Task 2: Rewrite sync_games to use env toggles + sweep detection

**Files:**
- Modify: `services/app/ingest/management/commands/sync_games.py`
- Test: `services/app/ingest/tests/test_sync_games_command.py`

This task makes `sync_games` read the new settings and enqueue via a sweep. It
stops referencing `SiteSettings.auto_enqueue_*` and the `created_at` filter.

- [ ] **Step 1: Write the failing tests**

In `services/app/ingest/tests/test_sync_games_command.py`:

(a) Change the imports block (lines 11-22) to drop `SiteSettings`, add
`override_settings`:

```python
import uuid
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from analysis.models import AnalysisJob
from games.models import Game
from players.models import Player
```

(b) Delete the `setUp` method (lines 40-42) — `SiteSettings` is no longer needed.

(c) Replace the existing `test_auto_enqueue_creates_stockfish_jobs_when_flag_on`
method (lines 44-80) with the following four methods (note the `@override_settings`
decorators drive behavior now):

```python
    @staticmethod
    def _fake_run_two_games(suffix):
        """Return a subprocess.run side_effect that inserts two new PGN games."""
        def fake_run(*args, **kwargs):
            Game.objects.create(
                id=f"d1-new1-{suffix}", played_at=timezone.now(),
                time_control="600", pgn="1. e4 *",
            )
            Game.objects.create(
                id=f"d1-new2-{suffix}", played_at=timezone.now(),
                time_control="600", pgn="1. d4 *",
            )
            return MagicMock(returncode=0)
        return fake_run

    @override_settings(AUTO_ENQUEUE_STOCKFISH=True, AUTO_ENQUEUE_LC0=False)
    def test_enqueues_stockfish_when_sf_toggle_on(self):
        """SF on, Lc0 off: stockfish jobs created for ingested games, no lc0 jobs."""
        suffix = uuid.uuid4().hex[:8]
        _make_player(f"alice-{suffix}")
        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=self._fake_run_two_games(suffix),
        ):
            call_command("sync_games", f"alice-{suffix}", stdout=StringIO())

        self.assertEqual(
            AnalysisJob.objects.filter(
                engine="stockfish", game__id__startswith="d1-new"
            ).count(),
            2,
        )
        self.assertEqual(
            AnalysisJob.objects.filter(
                engine="lc0", game__id__startswith="d1-new"
            ).count(),
            0,
        )

    @override_settings(AUTO_ENQUEUE_STOCKFISH=True, AUTO_ENQUEUE_LC0=True)
    def test_enqueues_lc0_when_lc0_toggle_on(self):
        """Lc0 on: lc0 jobs created for ingested games."""
        suffix = uuid.uuid4().hex[:8]
        _make_player(f"alice-{suffix}")
        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=self._fake_run_two_games(suffix),
        ):
            call_command("sync_games", f"alice-{suffix}", stdout=StringIO())

        self.assertEqual(
            AnalysisJob.objects.filter(
                engine="lc0", game__id__startswith="d1-new"
            ).count(),
            2,
        )

    @override_settings(AUTO_ENQUEUE_STOCKFISH=False, AUTO_ENQUEUE_LC0=False)
    def test_no_enqueue_when_both_toggles_off(self):
        """Both off (the default): no jobs are created even though games ingested."""
        suffix = uuid.uuid4().hex[:8]
        _make_player(f"alice-{suffix}")
        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=self._fake_run_two_games(suffix),
        ):
            call_command("sync_games", f"alice-{suffix}", stdout=StringIO())

        self.assertEqual(
            AnalysisJob.objects.filter(game__id__startswith="d1-new").count(), 0
        )

    @override_settings(AUTO_ENQUEUE_STOCKFISH=True, AUTO_ENQUEUE_LC0=False)
    def test_sweep_does_not_duplicate_existing_active_job(self):
        """A game that already has an active stockfish job gets no second job."""
        suffix = uuid.uuid4().hex[:8]
        _make_player(f"alice-{suffix}")

        def fake_run(*args, **kwargs):
            game = Game.objects.create(
                id=f"d1-new1-{suffix}", played_at=timezone.now(),
                time_control="600", pgn="1. e4 *",
            )
            AnalysisJob.objects.create(
                game=game, engine="stockfish",
                status=AnalysisJob.STATUS_PENDING, depth=20,
            )
            return MagicMock(returncode=0)

        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=fake_run,
        ):
            call_command("sync_games", f"alice-{suffix}", stdout=StringIO())

        self.assertEqual(
            AnalysisJob.objects.filter(
                engine="stockfish", game__id=f"d1-new1-{suffix}"
            ).count(),
            1,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ingest/tests/test_sync_games_command.py -v`
Expected: FAIL — the off-by-default and lc0 tests fail because the current
command reads `SiteSettings` (sf defaults True, lc0 False) instead of the
overridden settings.

- [ ] **Step 3: Rewrite the command**

In `services/app/ingest/management/commands/sync_games.py`:

(a) Imports (lines 24-35) — remove `from django.utils import timezone` and
`from core.models import SiteSettings`; add the query helpers, the model, and the
shared active-status tuple:

```python
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Exists, OuterRef, Q

from analysis.models import AnalysisJob
from analysis.services.enqueue import _ACTIVE_STATUSES, enqueue_analysis_job
from games.clock_parser import parse_move_times
from games.models import Game, GameMoveTime
from games.opening_resolver import resolve_opening_id
from ingest.models import SystemEvent
from players.models import Player
```

(b) Replace `handle` (lines 210-234) so it no longer captures/passes `started_at`:

```python
    def handle(self, *args, **options):
        """Acquire advisory lock, run sync, auto-enqueue. Release lock on exit.

        Args:
            *args: Positional arguments (unused).
            **options: Parsed command options from add_arguments.

        Returns:
            None

        Side effects:
            Acquires and releases Postgres advisory lock. May create AnalysisJob
            rows and SystemEvent rows.
        """
        if not _try_acquire_lock():
            self.stdout.write(
                "sync_games: advisory lock held; another run in progress, exiting."
            )
            return

        try:
            self._do_sync(options)
        finally:
            _release_lock()
```

(c) Change the `_do_sync` signature (line 236) to drop `started_at`:

```python
    def _do_sync(self, options: dict) -> None:
```

(d) Replace the auto-enqueue block (lines 292-306) with the sweep:

```python
        # Auto-enqueue games still needing analysis, per env toggles (issue #201).
        # Detection is by "lacking a satisfying job", not by created_at — the
        # ingest subprocess writes via the legacy SQLAlchemy model which never
        # stamps created_at.
        sf_count = lc_count = 0
        if settings.AUTO_ENQUEUE_STOCKFISH:
            sf_count = self._sweep_enqueue("stockfish", _stockfish_depth())
        if settings.AUTO_ENQUEUE_LC0:
            lc_count = self._sweep_enqueue("lc0", _lc0_nodes())
```

(e) Update the SystemEvent `details` (lines 320-324) to drop `new_games`:

```python
            details=(
                f"members={','.join(usernames)}; "
                f"sf_enqueued={sf_count}; lc0_enqueued={lc_count}"
            ),
```

(f) Add the `_sweep_enqueue` helper method to the `Command` class (place it just
before `_run_move_time_post_step`):

```python
    def _sweep_enqueue(self, engine: str, depth: int) -> int:
        """Enqueue every PGN game lacking a satisfying AnalysisJob for an engine.

        A game is a candidate when it has no active job (pending/running/
        submitted) and no completed job at depth >= the requested depth. Each
        candidate is run through enqueue_analysis_job, which re-checks dedup
        race-safely and skips 0-move PGNs.

        Args:
            engine: Engine name, 'stockfish' or 'lc0'.
            depth: Stockfish depth or Lc0 node budget for new jobs and the
                completed-job sufficiency threshold.

        Returns:
            int: Number of AnalysisJob rows created.

        Side effects:
            Creates AnalysisJob rows.
        """
        satisfying = AnalysisJob.objects.filter(
            game=OuterRef("pk"), engine=engine,
        ).filter(
            Q(status__in=_ACTIVE_STATUSES)
            | Q(status=AnalysisJob.STATUS_COMPLETED, depth__gte=depth)
        )
        candidates = Game.objects.filter(pgn__gt="").exclude(Exists(satisfying))
        count = 0
        for game in candidates.iterator():
            if enqueue_analysis_job(game=game, engine=engine, depth=depth):
                count += 1
        return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest ingest/tests/test_sync_games_command.py -v`
Expected: PASS (all methods, including the three advisory-lock / move-time /
pythonpath tests that were already present).

- [ ] **Step 5: Commit**

```bash
bandit -ll ingest/management/commands/sync_games.py
git add ingest/management/commands/sync_games.py ingest/tests/test_sync_games_command.py
git commit -m "fix(#201): enqueue via lacking-job sweep, driven by env toggles"
```

---

## Task 3: Remove the obsolete SiteSettings DB toggles

**Files:**
- Modify: `services/app/core/models.py`
- Modify: `services/app/core/admin.py`
- Modify: `services/app/core/tests/test_models.py`
- Create (via makemigrations): `services/app/core/migrations/0002_*.py`

- [ ] **Step 1: Write the failing test**

In `services/app/core/tests/test_models.py`, replace `test_default_toggles`
(lines 21-26) with a guard that the fields are gone, and update the module
docstring's second sentence to: `Verify SiteSettings.get_solo() returns the same
row across calls.`

```python
@pytest.mark.django_db
def test_auto_enqueue_fields_removed():
    """The auto-enqueue toggles are env-only now (#201); the model must not
    expose them as fields."""
    field_names = {f.name for f in SiteSettings._meta.get_fields()}
    assert "auto_enqueue_stockfish" not in field_names
    assert "auto_enqueue_lc0" not in field_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest core/tests/test_models.py -v`
Expected: FAIL on `test_auto_enqueue_fields_removed` (fields still present).

- [ ] **Step 3: Remove the model fields**

In `services/app/core/models.py`, delete the two `BooleanField` definitions
(lines 16-23) so the class body is:

```python
class SiteSettings(models.Model):
    """Singleton row of site-wide configuration. Always pk=1."""

    updated_at = models.DateTimeField(auto_now=True)
```

Also update the module docstring `Description` (lines 3-4) to:
`Description: Holds site-wide singleton configuration. (Auto-enqueue toggles
moved to env settings in #201.)` and add a changelog line:
`    2026-05-22: Remove auto_enqueue_* fields — now env-only (#201).`

- [ ] **Step 4: Remove the admin columns**

In `services/app/core/admin.py`, change `list_display` (line 17) to:

```python
    list_display = ("__str__", "updated_at")
```

- [ ] **Step 5: Generate the migration**

Run: `python manage.py makemigrations core`
Expected: creates `core/migrations/0002_remove_sitesettings_auto_enqueue_lc0_and_more.py`
(or similar) containing two `migrations.RemoveField` operations for
`auto_enqueue_lc0` and `auto_enqueue_stockfish`.

Verify no other model changes were picked up:
Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 6: Run the full affected suites to verify green**

Run: `pytest core/ ingest/tests/test_sync_games_command.py analysis/tests/test_enqueue.py -v`
Expected: PASS (all). This confirms the removal didn't break the command
(Task 2 already stopped referencing the fields) or enqueue.

- [ ] **Step 7: Commit**

```bash
bandit -ll core/models.py core/admin.py
git add core/models.py core/admin.py core/migrations/0002_*.py core/tests/test_models.py
git commit -m "refactor(#201): drop SiteSettings auto_enqueue_* fields (env-only now)"
```

---

## Task 4: Full verification + PR

- [ ] **Step 1: Run the full app test suite**

Run: `pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 2: Confirm migrations are consistent**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 3: Push and open the PR**

```bash
cd /Users/christopherwebster/Projects/wood_league
git push -u origin issue/201-auto-enqueue-env-fix
gh pr create --fill --base main
```

PR body must note the **operational follow-up**: after merge/deploy, set
`AUTO_ENQUEUE_STOCKFISH` (and optionally `AUTO_ENQUEUE_LC0`) on the Railway
`wood_league_cron` service — they default to **off**, so auto-enqueue stays
disabled until explicitly enabled. Then re-run ingest and confirm the
`game_sync` SystemEvent shows `sf_enqueued`/`lc0_enqueued` > 0.

---

## Self-Review Notes

- **Spec coverage:** env-only toggles (Task 1+3), both default False (Task 1), sweep
  detection reusing `enqueue_analysis_job` + `_ACTIVE_STATUSES` (Task 2), SystemEvent
  detail change (Task 2), test updates across all three test files (Tasks 1-3),
  `created_at` column left in place (never touched). Covered.
- **Type consistency:** `_sweep_enqueue(engine: str, depth: int) -> int` is defined in
  Task 2 and called only in Task 2. `_fake_run_two_games` defined and used within the
  same test class. `enqueue_analysis_job` / `_ACTIVE_STATUSES` / `AnalysisJob` import
  paths match `analysis/services/enqueue.py` and `analysis/models.py`.
- **Ordering:** settings → command rewrite → field removal keeps the suite green at
  every commit (the command stops reading the DB fields before they are deleted).
