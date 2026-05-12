# Race-safe `enqueue_analysis_job` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `enqueue_analysis_job` safe against concurrent callers by enforcing the active-job dedup invariant at the database level (partial unique index) and catching `IntegrityError` in the service.

**Architecture:** Add a partial `UniqueConstraint` on `AnalysisJob(game, engine)` scoped to active statuses (`pending`/`running`/`submitted`). Generate a Django migration. Wrap the `.create()` call in the service with `try/except IntegrityError` so a lost race returns `None` instead of raising. The pre-check `.exists()` queries stay as a fast path. Existing dedup semantics (active skip, completed-depth skip, otherwise create) are unchanged from the caller's perspective.

**Tech Stack:** Django 5.x, Postgres (prod), SQLite (CI), pytest-django.

**Spec:** `docs/superpowers/specs/2026-05-11-enqueue-race-safe-design.md`

**Working dir for all commands below:** `services/app/` (Django project root). Run `cd services/app` once before starting if you're not already there.

---

## Task 1: Add the partial UniqueConstraint to the model

**Files:**
- Modify: `services/app/analysis/models.py` (the `AnalysisJob.Meta` block, currently at lines 226-234)

- [ ] **Step 1: Edit `AnalysisJob.Meta` to add `constraints`**

In `services/app/analysis/models.py`, locate the `AnalysisJob` model's `Meta` class. Add `Q` to the existing `django.db.models` import if not already present (the file imports `from django.db import models`, so `Q` is reachable as `models.Q`). Then add a `constraints` list to `Meta`.

Replace this block:

```python
    class Meta:
        db_table = "analysis_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "engine"]),
            models.Index(fields=["status", "priority"]),
        ]
        verbose_name = "Analysis Job"
        verbose_name_plural = "Analysis Jobs"
```

With:

```python
    class Meta:
        db_table = "analysis_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "engine"]),
            models.Index(fields=["status", "priority"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "engine"],
                condition=models.Q(status__in=["pending", "running", "submitted"]),
                name="analysis_jobs_active_engine_unique",
            ),
        ]
        verbose_name = "Analysis Job"
        verbose_name_plural = "Analysis Jobs"
```

Note: status values are written as bare strings (not `STATUS_PENDING` etc.) so the migration freezes cleanly without depending on the model class body.

- [ ] **Step 2: Generate the migration**

Run: `python manage.py makemigrations analysis`

Expected: a new file is created at `analysis/migrations/0007_analysisjob_<auto-name>.py` (Django will name it something like `0007_analysisjob_analysis_jobs_active_engine_unique.py`). It should contain a single `migrations.AddConstraint` operation referencing `analysis_jobs_active_engine_unique`. If `makemigrations` says "No changes detected", the edit in Step 1 didn't take — re-check the indentation of `constraints` inside `Meta`.

- [ ] **Step 3: Inspect the generated migration**

Open the new migration file and verify it contains:

```python
operations = [
    migrations.AddConstraint(
        model_name="analysisjob",
        constraint=models.UniqueConstraint(
            condition=models.Q(("status__in", ["pending", "running", "submitted"])),
            fields=("game", "engine"),
            name="analysis_jobs_active_engine_unique",
        ),
    ),
]
```

If the form differs slightly (e.g., `models.Q(status__in=...)` rendered as a keyword arg vs a tuple), that's fine — Django renders Q in different ways across versions. The key is the `name` and the `fields`/`condition`.

- [ ] **Step 4: Apply the migration**

Run: `python manage.py migrate analysis`

Expected: output ends with `Applying analysis.0007_...: OK`.

If the migration fails with `IntegrityError: could not create unique index ... Key (game_id, engine)=(..., ...) is duplicated`, you have existing duplicate active rows. Stop and report — manual cleanup is needed, which is out of scope for this task.

- [ ] **Step 5: Run the full test suite — should still pass**

Run: `pytest analysis/tests/test_enqueue.py -v`

Expected: all 6 existing dedup tests still pass (the constraint doesn't change the happy paths — they all use one job per `(game, engine)`).

- [ ] **Step 6: Run bandit on the changed file**

Run: `bandit -ll analysis/models.py`

Expected: no Medium or High findings.

- [ ] **Step 7: Commit**

```bash
git add analysis/models.py analysis/migrations/0007_*.py
git commit -m "feat(analysis): add partial unique constraint on active jobs (issue #15)

Enforces (game, engine) uniqueness at the DB level for jobs in pending,
running, or submitted status. Completed and failed jobs are unaffected."
```

---

## Task 2: Write failing DB-constraint tests

**Files:**
- Modify: `services/app/analysis/tests/test_enqueue.py`

- [ ] **Step 1: Add three new tests**

Append the following to `services/app/analysis/tests/test_enqueue.py` (after the existing `test_completed_lower_depth_creates`):

```python
from django.db import IntegrityError


@pytest.mark.django_db
@pytest.mark.parametrize("second_status", [
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_RUNNING,
    AnalysisJob.STATUS_SUBMITTED,
])
def test_partial_unique_blocks_second_active(second_status):
    """DB-level: a second active job for the same (game, engine) must be rejected.

    Args:
        second_status: Active status for the second insert — parametrized over
            pending/running/submitted.
    """
    game = _make_game()
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, depth=20,
    )
    with pytest.raises(IntegrityError):
        AnalysisJob.objects.create(
            game=game, engine="stockfish",
            status=second_status, depth=20,
        )


@pytest.mark.django_db
def test_partial_unique_allows_completed_plus_active():
    """DB-level: completed + active for the same (game, engine) is allowed.

    Only active statuses fall under the partial unique index, so a completed
    job must not block a new pending job.
    """
    game = _make_game()
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED, depth=20,
    )
    # Should not raise.
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, depth=25,
    )


@pytest.mark.django_db
def test_partial_unique_allows_two_completed():
    """DB-level: two completed jobs for the same (game, engine) are allowed.

    Completed jobs are outside the partial unique index, so re-analysis
    history can accumulate.
    """
    game = _make_game()
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED, depth=20,
    )
    # Should not raise.
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED, depth=25,
    )
```

- [ ] **Step 2: Run new tests — verify they pass**

Run: `pytest analysis/tests/test_enqueue.py -v -k "partial_unique"`

Expected: 5 PASS (3 parametrized + 2 standalone). These tests verify the migration from Task 1, so they should already pass. If the parametrized `test_partial_unique_blocks_second_active` *fails to raise*, the migration didn't apply correctly — re-run `migrate` and investigate.

- [ ] **Step 3: Commit**

```bash
git add analysis/tests/test_enqueue.py
git commit -m "test(analysis): cover partial unique constraint on AnalysisJob (issue #15)"
```

---

## Task 3: Catch IntegrityError in `enqueue_analysis_job`

**Files:**
- Modify: `services/app/analysis/services/enqueue.py`

- [ ] **Step 1: Write a failing test for the race-path return value**

Append to `services/app/analysis/tests/test_enqueue.py`:

```python
from unittest.mock import patch


@pytest.mark.django_db
def test_enqueue_returns_none_when_race_violates_constraint():
    """If a concurrent caller inserts an active row between our .exists() check
    and our .create(), the DB unique constraint rejects the insert. The service
    must swallow the IntegrityError and return None, matching the dedup-skip
    contract.

    Simulated by pre-creating an active row, then patching the first .exists()
    query in the service to return False (i.e., lying about the row's absence).
    """
    game = _make_game()
    # The "concurrent" active row already exists.
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, depth=20,
    )

    # Force the dedup pre-check to lie — simulates the race window.
    with patch(
        "analysis.services.enqueue.AnalysisJob.objects.filter"
    ) as mock_filter:
        mock_filter.return_value.exists.return_value = False
        result = enqueue_analysis_job(game=game, engine="stockfish", depth=20)

    assert result is None
    # And we did not create a duplicate.
    assert AnalysisJob.objects.filter(game=game, engine="stockfish").count() == 1
```

- [ ] **Step 2: Run the new test — verify it FAILS**

Run: `pytest analysis/tests/test_enqueue.py::test_enqueue_returns_none_when_race_violates_constraint -v`

Expected: FAIL with `django.db.utils.IntegrityError` raised out of `enqueue_analysis_job`. This confirms that without the fix, the service propagates the error instead of treating it as dedup-skip.

- [ ] **Step 3: Implement the fix in `enqueue.py`**

Replace the entire body of `enqueue_analysis_job` in `services/app/analysis/services/enqueue.py` (currently a `with transaction.atomic():` block) with the version below. Also update the imports: remove `from django.db import transaction` and add `from django.db import IntegrityError`.

```python
"""
Title: enqueue.py — Dedup-safe AnalysisJob creation
Description: Single source of truth for deciding whether a Game needs a new
    AnalysisJob. The active-job dedup invariant is enforced by a partial
    unique index on (game, engine) WHERE status IN ('pending','running',
    'submitted'), so this function is safe under concurrent callers without
    external coordination. The pre-check .exists() queries remain as a fast
    path in the uncontended case.
Changelog:
    2026-05-10: Initial — Task A3 of scrap-dispatchers plan.
    2026-05-11: Race-safe via partial unique constraint (issue #15).
"""
from __future__ import annotations

from django.db import IntegrityError

from analysis.models import AnalysisJob
from games.models import Game

# Statuses that indicate a job is actively being processed or waiting to run.
# A job in any of these states blocks creation of a duplicate for the same
# game+engine pair.
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

    Dedup rules (checked in order):
    1. Any active job (pending, running, or submitted) for game+engine → skip.
    2. A completed job at depth >= requested depth for game+engine → skip.
    3. Otherwise → attempt to create. If the partial unique index rejects the
       insert (a concurrent caller raced in between the pre-check and the
       create), treat as dedup-skip and return None.

    dispatch_mode is intentionally excluded from all filters — it is being
    removed in Phase F and must not affect dedup decisions.

    Args:
        game: The Game instance to analyze.
        engine: Engine name, e.g. 'stockfish' or 'lc0'.
        depth: Stockfish depth or Lc0 node budget threshold. Used to decide
            whether a completed job already satisfies the requested depth.
        priority: Job priority; higher values run first.

    Returns:
        The newly created AnalysisJob with STATUS_PENDING, or None if an
        active or sufficiently-deep completed job already exists, or if a
        concurrent caller won the race for the active slot.
    """
    if AnalysisJob.objects.filter(
        game=game,
        engine=engine,
        status__in=_ACTIVE_STATUSES,
    ).exists():
        return None

    if AnalysisJob.objects.filter(
        game=game,
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        depth__gte=depth,
    ).exists():
        return None

    try:
        return AnalysisJob.objects.create(
            game=game,
            engine=engine,
            depth=depth,
            priority=priority,
            status=AnalysisJob.STATUS_PENDING,
        )
    except IntegrityError:
        # Lost the race: another caller inserted an active row for this
        # (game, engine) between our pre-check and our INSERT. The partial
        # unique constraint rejected our row, which is semantically the
        # same as the dedup-skip path above.
        return None
```

- [ ] **Step 4: Run the race-path test — verify it PASSES**

Run: `pytest analysis/tests/test_enqueue.py::test_enqueue_returns_none_when_race_violates_constraint -v`

Expected: PASS.

- [ ] **Step 5: Run the full enqueue test file — verify all tests still pass**

Run: `pytest analysis/tests/test_enqueue.py -v`

Expected: all tests pass (6 pre-existing + 3 parametrized constraint cases from Task 2 + 2 standalone constraint cases from Task 2 + 1 new race-path case from this task).

- [ ] **Step 6: Run bandit on the changed file**

Run: `bandit -ll analysis/services/enqueue.py`

Expected: no Medium or High findings.

- [ ] **Step 7: Run the broader analysis test suite to check for regressions**

Run: `pytest analysis/ -v`

Expected: all tests pass. If anything in `test_runpod_dispatch.py`, `test_views_queue.py`, etc. relied on `transaction.atomic()` semantics inside `enqueue_analysis_job`, this is where it would surface — those callers should not depend on this internal detail, but verify.

- [ ] **Step 8: Commit**

```bash
git add analysis/services/enqueue.py analysis/tests/test_enqueue.py
git commit -m "fix(analysis): make enqueue_analysis_job race-safe (closes #15)

Catch IntegrityError from the partial unique constraint and treat it as
the dedup-skip path. Removes the misleading 'NOT race-safe' caveat from
the docstring."
```

---

## Task 4: Run the full project quality gate

**Files:** (none — verification only)

- [ ] **Step 1: Full pytest run**

Run: `pytest -q`

Expected: full suite green. If anything fails outside `analysis/`, investigate before proceeding — the change is local enough that unrelated failures likely indicate a pre-existing issue, but confirm.

- [ ] **Step 2: Ruff lint**

Run: `ruff check analysis/`

Expected: clean.

- [ ] **Step 3: Confirm migration round-trips**

Run: `python manage.py migrate analysis 0006 && python manage.py migrate analysis`

Expected: the unconstrain step succeeds, then re-applying succeeds. This proves the migration is reversible — important if a future rollback is needed.

- [ ] **Step 4: Push the branch and open a PR**

```bash
git push -u origin issue/15-enqueue-race-safe
gh pr create --title "fix(analysis): race-safe enqueue_analysis_job via partial unique index (closes #15)" --body "$(cat <<'EOF'
## Summary
- Add a partial `UniqueConstraint` on `AnalysisJob(game, engine)` for active statuses (`pending`/`running`/`submitted`), enforced as a Postgres partial unique index.
- Catch `IntegrityError` in `enqueue_analysis_job` and treat it as the dedup-skip path. Removes the previous "NOT race-safe" caveat.
- Drop the now-redundant `transaction.atomic()` wrapper.

## Why
`enqueue_analysis_job` was safe only because the sole production caller (`sync_games`) holds a Postgres advisory lock. Any future caller (admin action, webhook) could race against the cron sweep and produce duplicate active jobs. The partial unique index makes the invariant defense-in-depth at the schema level.

Spec: `docs/superpowers/specs/2026-05-11-enqueue-race-safe-design.md`

## Test plan
- [x] DB constraint blocks a second active job for the same `(game, engine)`
- [x] DB constraint allows `completed` + active to coexist
- [x] DB constraint allows multiple `completed` rows
- [x] Service returns `None` (not raises) when a race causes the insert to be rejected
- [x] Existing dedup matrix tests still pass
- [x] Migration round-trips cleanly

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Return the URL.
