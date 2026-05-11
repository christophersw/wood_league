---
Title: Race-safe enqueue_analysis_job via partial unique index
Issue: #15
Date: 2026-05-11
---

# Race-safe `enqueue_analysis_job`

## Problem

`services/app/analysis/services/enqueue.py::enqueue_analysis_job` performs
`.exists()` + `.create()` without a row lock or DB-level uniqueness
constraint. Two callers for the same `(game, engine)` pair can both pass the
dedup check and insert duplicate active `AnalysisJob` rows.

Today the only production caller (`sync_games`) holds a Postgres advisory
lock around its sweep, so the race cannot occur in current usage. The
function's docstring documents this. Any future caller that doesn't take the
lock — an admin "Enqueue this game" button, a webhook handler, a manual
admin-site save — can race against the cron sweep. Defense-in-depth at the
schema level is much harder to accidentally bypass than convention.

## Goal

Make `enqueue_analysis_job` race-safe without external coordination, while
preserving its current dedup semantics:
1. Skip if any active job (`pending`/`running`/`submitted`) exists for
   `(game, engine)`.
2. Skip if a completed job at `depth >= requested` exists.
3. Otherwise insert a new pending job.

## Design

### Schema change

Add a partial `UniqueConstraint` to `AnalysisJob.Meta.constraints`:

```python
from django.db.models import Q

constraints = [
    models.UniqueConstraint(
        fields=["game", "engine"],
        condition=Q(status__in=["pending", "running", "submitted"]),
        name="analysis_jobs_active_engine_unique",
    ),
]
```

Generate the migration with `manage.py makemigrations analysis`. Django 5.x
renders `UniqueConstraint(condition=...)` as a partial unique index on
Postgres. SQLite supports it as well, so test DBs remain compatible.

Status string literals (not `AnalysisJob.STATUS_PENDING` constants) are used
inside the `Q` so the migration freezes cleanly without dragging in the
model's class body.

### Code change

In `enqueue_analysis_job`:

- Keep the two pre-check `.exists()` queries — they remain useful as the
  fast path in the uncontended case (which is the overwhelming common case).
- Wrap the final `AnalysisJob.objects.create(...)` in
  `try/except IntegrityError`. On `IntegrityError`, return `None` — the race
  was lost because another caller inserted an active row between our check
  and our insert. This is semantically equivalent to the dedup-skip path.
- Drop the surrounding `transaction.atomic()`. With the unique index in
  place there is nothing to serialize: the DB enforces the invariant
  atomically per row. (`create()` runs in its own implicit transaction.)
- Update the docstring: remove the "NOT race-safe" caveat; document that
  the partial unique index enforces the active-job invariant at the schema
  level, and that callers may now invoke this function without external
  coordination.

### Tests

Add to `services/app/analysis/tests/`:

1. **DB constraint, positive**: directly insert one `AnalysisJob` with
   `status=pending`, then call `AnalysisJob.objects.create(...)` again with
   the same `(game, engine)` and any active status — assert it raises
   `django.db.IntegrityError`.
2. **DB constraint, completed coexists**: insert a `completed` job, then a
   `pending` job, for the same `(game, engine)` — assert both succeed
   (constraint only covers active statuses).
3. **DB constraint, two completed coexist**: insert two `completed` jobs
   for the same `(game, engine)` — assert both succeed (completed is not
   in the predicate).
4. **Service swallows IntegrityError**: simulate the race by patching the
   first `.exists()` query to return `False` while an active row is present.
   Assert `enqueue_analysis_job(...)` returns `None` and does not raise.
5. **Service happy path unchanged**: existing dedup tests for the
   pre-check paths continue to pass.

The threaded/true-concurrency test is intentionally out of scope —
DB-level integrity plus the service-level patch test cover the failure
mode without CI flakiness.

## Out of Scope

- Removing the Postgres advisory lock around `sync_games`. The lock has
  other roles (e.g., preventing duplicate sweep work) and is unrelated to
  per-row dedup.
- Refactoring callers. Existing call sites continue to work; the change is
  purely additive at the schema and error-handling level.
- Changing the completed-depth dedup logic.

## Risks

- **Existing data**: if any duplicate active rows exist in production, the
  migration will fail. Mitigation: pre-check with a query in a migration
  data step, or accept the failure as a signal that manual cleanup is
  needed. Likely zero rows in practice because the advisory lock has
  prevented this race so far. The migration will surface any latent
  duplicates.
- **SQLite test parity**: confirmed `UniqueConstraint(condition=...)` runs
  on SQLite (used in CI). Postgres remains the production target.
