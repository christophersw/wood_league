# Django App Quality Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring all 158 Python files in `services/app` to full compliance with the project's code quality and documentation standards by running and fixing the quality gate pipeline (ruff → bandit → radon/xenon → mypy → pytest) and adding required file headers and function docstrings.

**Architecture:** Work is parallelizable by type: auto-fix linting first (no risk), then fix the Django test setup failure, then add headers and docstrings (mechanical/Haiku), then refactor high-complexity functions (Sonnet), then resolve mypy type errors, then run Snyk security scan. Each task commits independently.

**Tech Stack:** Python 3.13, Django 5.x, ruff, bandit, semgrep, radon, xenon, mypy, pytest — all tools pre-installed at paths defined in `.claude/hooks/quality-gate.sh`

---

## Baseline (as of 2026-05-08)

| Check | Status | Count |
|-------|--------|-------|
| ruff auto-fixable | FAIL | 60 errors |
| ruff manual | FAIL | 10 errors |
| bandit | WARN | nosec suppression only — no real issues |
| xenon grade C | WARN | 18 functions |
| xenon grade D | FAIL | 12 functions |
| xenon grade E | FAIL | 2 functions (continuation_flow in 2 files) |
| mypy errors | FAIL | 30 errors |
| file headers missing | FAIL | 106 files |
| pytest (non-api) | FAIL | 1 failure (py39 compat test) |
| pytest api/ | FAIL | AppRegistryNotReady (conftest missing) |

---

## File Map

| File(s) | Task |
|---------|------|
| All 158 `.py` files in `services/app/` | Task 1 (ruff auto-fix) |
| `ingest/urls.py`, `api/views.py`, `games/views.py`, `accounts/models.py`, `accounts/admin.py`, `api/views.py` | Task 2 (ruff manual + mypy annotation hints) |
| `api/tests/__init__.py` or `api/tests/conftest.py` (create) | Task 3 (Django test setup) |
| `analysis/views.py` | Task 4 (mypy attr-defined errors) |
| `app/services/lc0_service.py`, `app/services/stockfish_service.py`, `games/stat_cards.py`, `dashboard/management/commands/copy_vendor_js.py` | Task 5 (mypy type errors) |
| All 106 files missing headers (see baseline scan) | Task 6 (file headers — Haiku) |
| All source `.py` files with undocumented functions | Task 7 (function docstrings — Haiku) |
| `app/services/opening_position_service.py`, `openings/services.py` | Task 8 (grade E refactor) |
| `app/ingest/sync_service.py`, `app/services/lc0_service.py`, `app/services/stockfish_service.py`, `app/services/welcome_service.py`, `app/services/game_search_service.py`, `app/services/analysis_service.py`, `openings/services.py`, `dashboard/services.py`, `search/services.py` | Task 9 (grade D refactor) |
| Entire `services/app/` | Task 10 (Snyk scan + fixes) |
| Entire `services/app/` | Task 11 (final gate verification) |

---

## Task 1: Ruff Auto-Fix (Model: Haiku)

**Files:** All `.py` files in `services/app/`

- [ ] **Step 1: Run ruff auto-fix**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
/opt/homebrew/bin/ruff check . --fix
```

Expected: "60 errors fixed" or similar. Some unfixable will remain.

- [ ] **Step 2: Verify only manual errors remain**

```bash
/opt/homebrew/bin/ruff check . --statistics
```

Expected: Only E402 (7), E741 (2), F841 (1) remain.

- [ ] **Step 3: Commit**

```bash
git add -u
git commit -m "fix(lint): auto-fix 60 ruff errors (unused imports, f-strings)"
```

---

## Task 2: Ruff Manual Fixes + Annotation Hints (Model: Haiku)

**Files:** `ingest/urls.py`, `api/views.py`, `games/views.py`, `accounts/models.py`, `accounts/admin.py` — plus any files with E402/E741/F841

**Context:** Run `cd services/app && /opt/homebrew/bin/ruff check . --output-format=text` to see exact line numbers.

- [ ] **Step 1: Fix E402 — module-level import not at top**

For each file flagged with E402: move the flagged import to the top of the file, above any non-`__future__` / non-`__all__` code that was appearing before it. If an import must stay after code (e.g., `django.setup()` must be called first), add `# noqa: E402` with a comment explaining why.

Run `ruff check . --select E402` to see all instances first.

- [ ] **Step 2: Fix E741 — ambiguous variable names**

Replace `l`, `O`, `I` variable names with descriptive equivalents. Run `ruff check . --select E741` to find them.

- [ ] **Step 3: Fix F841 — local variable assigned but never used**

Delete or replace the unused local variable. Run `ruff check . --select F841`.

- [ ] **Step 4: Verify ruff clean**

```bash
/opt/homebrew/bin/ruff check .
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "fix(lint): resolve manual ruff errors (E402, E741, F841)"
```

---

## Task 3: Fix Django Test Setup (Model: Sonnet)

**Files:** `services/app/api/tests/conftest.py` (create), or fix existing conftest

**Context:** Running pytest from project root fails with `AppRegistryNotReady` because Django settings aren't configured before models are imported in `api/tests/`. The fix is a `conftest.py` that calls `django.setup()` before test collection.

- [ ] **Step 1: Check for existing conftest files**

```bash
find /Users/christopherwebster/Projects/wood_league/services/app -name "conftest.py"
```

- [ ] **Step 2: Create or update conftest.py at the app root**

If no root conftest exists, create `services/app/conftest.py`:

```python
"""
Title: conftest.py — Pytest configuration for Django app
Description:
    Configures Django settings before test collection so that model imports
    in test files do not trigger AppRegistryNotReady errors.

Changelog:
    2026-05-08: Created to fix AppRegistryNotReady in api/tests/
"""
import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
```

If a root conftest already exists, add the `os.environ.setdefault` and `django.setup()` calls at the top.

- [ ] **Step 3: Run the api tests to confirm fix**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
DJANGO_SETTINGS_MODULE=config.settings ../../.venv/bin/pytest api/tests/ --tb=short -q
```

Expected: Tests run (pass or fail with actual test failures, not import errors).

- [ ] **Step 4: Fix the py39 compat test**

Check `tests/test_py39_annotation_compat.py:46` — it asserts a file list is non-empty but gets `[]`. Read the test to understand what glob pattern it uses, then either:
  - Fix the glob pattern to match actual file paths, OR
  - Update it to reflect the current Python version (this project runs 3.13, not 3.9).

```bash
cat /Users/christopherwebster/Projects/wood_league/services/app/tests/test_py39_annotation_compat.py
```

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
DJANGO_SETTINGS_MODULE=config.settings ../../.venv/bin/pytest . --tb=short -q
```

Expected: All tests pass or only known intentional failures remain.

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "fix(tests): add conftest Django setup, fix py39 compat test"
```

---

## Task 4: Fix mypy Attribute Errors in analysis/views.py (Model: Sonnet)

**Files:** `services/app/analysis/views.py`, `services/app/analysis/services.py` (or `services/app/analysis/services/jobs.py`)

**Context:** mypy reports 5 `attr-defined` errors: `analysis/views.py` imports `queue_totals`, `queue_by_engine`, `runpod_health`, `worker_heartbeats`, `recent_jobs` from `analysis.services` but those symbols aren't found. They likely live in `analysis/services/jobs.py` (a sub-module) but the import references the package root.

- [ ] **Step 1: Find where these functions are defined**

```bash
grep -r "def queue_totals\|def queue_by_engine\|def runpod_health\|def worker_heartbeats\|def recent_jobs" \
  /Users/christopherwebster/Projects/wood_league/services/app/analysis/
```

- [ ] **Step 2: Fix the import in analysis/views.py**

If the functions are in `analysis/services/jobs.py`, change the import from:
```python
from analysis import services
# used as: services.queue_totals(...)
```
to:
```python
from analysis.services import jobs
# used as: jobs.queue_totals(...)
```
OR add re-exports to `analysis/services/__init__.py`:
```python
from analysis.services.jobs import (
    queue_totals,
    queue_by_engine,
    runpod_health,
    worker_heartbeats,
    recent_jobs,
)
```

- [ ] **Step 3: Verify mypy clean for this file**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
../../.venv/bin/mypy --ignore-missing-imports --follow-imports=skip --explicit-package-bases analysis/views.py
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "fix(types): resolve mypy attr-defined errors in analysis/views.py"
```

---

## Task 5: Fix mypy Type Errors in Source Files (Model: Sonnet)

**Files:**
- `services/app/app/services/lc0_service.py` (lines ~176, ~366)
- `services/app/app/services/stockfish_service.py` (line ~220)
- `services/app/games/stat_cards.py` (line ~413)
- `services/app/dashboard/management/commands/copy_vendor_js.py` (line ~16)

Run full mypy to get current line numbers:
```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
../../.venv/bin/mypy --ignore-missing-imports --follow-imports=skip --explicit-package-bases . 2>&1 | grep "error:" | grep -v migrations
```

- [ ] **Step 1: Fix lc0_service.py bracketed type expression errors**

At line ~176, the error is: `Bracketed expression "[...]" is not valid as a type` and `Function "builtins.callable" is not valid as a type`. This likely means a type annotation like `Callable[...]` or `list[callable]` is used incorrectly.

Fix: Import `Callable` from `collections.abc` and use `Callable[[ArgType], ReturnType]` syntax:
```python
from collections.abc import Callable
```

At line ~366: `"callable?[Any, None]" not callable` — this is likely an incorrectly typed variable used as a function. Inspect and add proper type guard or cast.

- [ ] **Step 2: Fix stockfish_service.py bracketed type expression**

Same pattern as lc0_service.py line ~220. Apply the same `Callable` import fix.

- [ ] **Step 3: Fix stat_cards.py arg-type error**

At line ~413: `Argument 1 to "_metric_bar" has incompatible type "float | None"; expected "float"`.

Fix: Either update `_metric_bar`'s signature to accept `float | None`, or add a guard before the call:
```python
if value is not None:
    _metric_bar(value, ...)
```

- [ ] **Step 4: Fix copy_vendor_js.py Path arg-type error**

At line ~16: `Argument 1 to "Path" has incompatible type "str | None"; expected "str | PathLike[str]"`.

Fix: add a `None` guard or use `or ""`:
```python
base = Path(os.environ.get("BASE_DIR") or "")
```

- [ ] **Step 5: Fix annotation hints (migration boilerplate + Django patterns)**

For migration files (`dependencies: list[<type>] = ...`), `accounts/models.py` (`REQUIRED_FIELDS`), `accounts/admin.py` (`filter_horizontal`), `api/views.py` (`permission_classes`), `games/views.py` (`arrow_labels_by_ply`): add explicit type annotations. Example:

```python
# In migration files (auto-generated, add type annotation):
dependencies: list[tuple[str, str]] = []

# In accounts/models.py:
REQUIRED_FIELDS: list[str] = []

# In accounts/admin.py:
filter_horizontal: tuple[str, ...] = ()

# In api/views.py:
permission_classes: list[type] = [IsAuthenticated]

# In games/views.py:
arrow_labels_by_ply: dict[int, list[str]] = {}
```

- [ ] **Step 6: Verify mypy clean (excluding migrations)**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
../../.venv/bin/mypy --ignore-missing-imports --follow-imports=skip --explicit-package-bases \
  --exclude migrations . 2>&1 | grep "error:" | head -20
```

Expected: 0 errors in non-migration files.

- [ ] **Step 7: Commit**

```bash
git add -u
git commit -m "fix(types): resolve 30 mypy type errors across services"
```

---

## Task 6: Add File Headers (Model: Haiku)

**Files:** 106 files listed by this command (run first to get current list):
```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
python3 -c "
import os
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ['__pycache__', 'migrations', '.venv']]
    for f in files:
        if f.endswith('.py') and not f.startswith('__'):
            path = os.path.join(root, f)
            with open(path) as fh:
                content = fh.read(500)
            if 'Title:' not in content and 'Description:' not in content:
                print(path)
"
```

**Header format** (from `~/.claude/docs/code-standards.md`):

```python
"""
Title: <filename>.py — <one-line purpose>
Description:
    <2-4 sentence explanation of what the module does and its role in the system>

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
```

**Rules:**
- For `__init__.py` files: one-line docstring is sufficient if the file is empty or just re-exports: `"""<app_name> app package."""`
- For Django boilerplate files (`apps.py`, `admin.py`, `forms.py` with just `pass`): still add the header to the module docstring.
- For migration files: skip (they are auto-generated).
- Place the docstring as the very first thing in the file, before any imports.

- [ ] **Step 1: Process accounts app files**

Add headers to: `accounts/admin.py`, `accounts/apps.py`, `accounts/backends.py`, `accounts/forms.py`, `accounts/middleware.py`, `accounts/models.py`, `accounts/tests.py`, `accounts/urls.py`, `accounts/views.py`

Run ruff after each batch to confirm no new lint issues.

- [ ] **Step 2: Process analysis app files**

Add headers to: `analysis/admin.py`, `analysis/apps.py`, `analysis/forms.py`, `analysis/models.py`, `analysis/partial_urls.py`, `analysis/services.py`, `analysis/services/jobs.py`, `analysis/tests.py`, `analysis/urls.py`, `analysis/views.py`

- [ ] **Step 3: Process api app files**

Add headers to: `api/admin.py`, `api/admin_urls.py`, `api/admin_views.py`, `api/apps.py`, `api/authentication.py`, `api/models.py`, `api/serializers.py`, `api/urls.py`, `api/views.py`, all files in `api/tests/`

- [ ] **Step 4: Process app/ (ingest + services + storage) files**

Add headers to: `app/config.py`, all files in `app/ingest/`, `app/services/`, `app/storage/`

- [ ] **Step 5: Process dashboard, games, ingest, openings, players, search apps**

Add headers to all non-`__init__` files in each app directory.

- [ ] **Step 6: Process config/, manage.py, top-level tests/**

Add headers to: `manage.py`, `config/settings.py`, `config/urls.py`, `config/asgi.py`, `config/wsgi.py`, `tests/test_py39_annotation_compat.py`

- [ ] **Step 7: Verify all headers present**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
python3 -c "
import os
missing = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ['__pycache__', 'migrations', '.venv']]
    for f in files:
        if f.endswith('.py') and not f.startswith('__'):
            path = os.path.join(root, f)
            with open(path) as fh:
                content = fh.read(500)
            if 'Title:' not in content and 'Description:' not in content:
                missing.append(path)
print(f'Still missing: {len(missing)}')
for p in missing: print(p)
"
```

Expected: 0 files missing headers.

- [ ] **Step 8: Commit**

```bash
git add -u
git commit -m "docs: add file headers to all 106 Python source files"
```

---

## Task 7: Add Function Docstrings (Model: Haiku)

**Scope:** Every non-trivial function (anything with a body longer than 1 line) must have a docstring. Skip: `__init__`, `__str__`, `__repr__`, Django `Meta` classes, migration `forwards`.

**Docstring format** (per global CLAUDE.md):
```python
def function_name(param1: Type, param2: Type) -> ReturnType:
    """
    Brief one-line description of what this does.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of return value.
    """
```

Process by app in order. For each file, read it, identify functions/methods missing docstrings, add them. Run ruff after each file to ensure no new lint issues.

- [ ] **Step 1: Add docstrings to `app/services/` files** (highest complexity, most value)

Files: `analysis_service.py`, `auth_service.py`, `game_search_service.py`, `history_service.py`, `lc0_service.py`, `opening_analysis_service.py`, `opening_labels.py`, `opening_position_service.py`, `stockfish_service.py`, `time_control.py`, `welcome_service.py`

- [ ] **Step 2: Add docstrings to `app/ingest/` files**

Files: `analysis_worker.py`, `chesscom_client.py`, `enqueue_analysis.py`, `lc0_analysis_worker.py`, `run_analysis_worker.py`, `run_lc0_worker.py`, `run_sync.py`, `sync_service.py`

- [ ] **Step 3: Add docstrings to Django app views and services**

Process each app: `games/`, `dashboard/`, `openings/`, `players/`, `search/`, `analysis/`, `api/`, `accounts/`

- [ ] **Step 4: Verify ruff still clean**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
/opt/homebrew/bin/ruff check .
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "docs: add function docstrings to all source files"
```

---

## Complexity Decision Framework (Tasks 8 & 9)

Before touching any function, read it and apply this decision tree:

```
Read the function body
        │
        ▼
Is the complexity inherent to the domain?
(tree traversal with many branches, exhaustive
 SQL sanitizer rules, state machine, PGN parser)
        │
    YES ├──────────────────────────────────────────────────────────────►
        │                                                               │
        ▼                                                               │
Can it be decomposed into named helpers         Would splitting it make it HARDER
that each make sense independently?             to read (e.g. scattered branch logic,
(separable concerns, repeated patterns)         artificial helper names)?
        │                                               │
      YES ▼                                           YES ▼
  Refactor: extract helpers,              Acceptable complexity:
  verify tests pass, commit              add # noqa: C901 with a
                                         comment, add to FLAGGED.md
        │                                         │
        ▼                                         ▼
   Grade ≤ B?                           Can't decide / unsure?
      YES ▼                                       │
   Done ✓                                       YES ▼
                                         Add to FLAGGED.md for
                                         human review — do NOT guess
```

**FLAGGED.md** lives at `services/app/docs/complexity-review.md`. Append each flagged function in this format:

```markdown
### `<file>::<function>` — Grade <X>

**Radon CC score:** <N>
**Why flagged:** <one sentence: inherent domain complexity / uncertain decomposition / etc.>
**Recommendation:** <accept as-is / needs human eyes before refactor>

```bash
# To inspect:
radon cc -s <file> | grep -A5 <function>
```
```

---

## Task 8: Evaluate & Act on Grade E Functions (Model: Sonnet)

**Functions:**
- `app/services/opening_position_service.py::continuation_flow` (grade E)
- `openings/services.py::continuation_flow` (grade E)

- [ ] **Step 1: Create the complexity review file**

```bash
mkdir -p /Users/christopherwebster/Projects/wood_league/services/app/docs
cat > /Users/christopherwebster/Projects/wood_league/services/app/docs/complexity-review.md << 'EOF'
# Complexity Review — Flagged for Human Review

Functions flagged by the quality audit that require human judgement before
refactoring. Each entry explains why the tool flagged it and what decision
is needed.

EOF
```

- [ ] **Step 2: Read both continuation_flow functions in full**

```bash
/opt/homebrew/Cellar/python@3.9/3.9.25/Frameworks/Python.framework/Versions/3.9/bin/radon cc -s \
  /Users/christopherwebster/Projects/wood_league/services/app/app/services/opening_position_service.py \
  /Users/christopherwebster/Projects/wood_league/services/app/openings/services.py \
  | grep -A3 "continuation_flow"
```

Then read each file fully (use `get_skeleton` or `Read`) to understand the logic before deciding.

- [ ] **Step 3: Apply decision framework to `app/services/opening_position_service.py::continuation_flow`**

After reading:

**If refactorable:** Extract helpers (e.g. `_get_root_node`, `_build_continuation_nodes`, `_compute_move_stat`). Each helper CC ≤ 5, main function CC ≤ 5. Then go to Step 4a.

**If inherently complex or uncertain:** Go to Step 4b.

- [ ] **Step 4a (refactor path): Refactor and verify**

```bash
# After editing:
/opt/homebrew/Cellar/python@3.9/3.9.25/Frameworks/Python.framework/Versions/3.9/bin/xenon \
  --max-absolute B --max-modules A --max-average A \
  /Users/christopherwebster/Projects/wood_league/services/app/app/services/opening_position_service.py

cd /Users/christopherwebster/Projects/wood_league/services/app
DJANGO_SETTINGS_MODULE=config.settings ../../.venv/bin/pytest . --tb=short -q
```

Expected: xenon exits 0, tests unchanged.

- [ ] **Step 4b (flag path): Suppress and document**

Add `# noqa: C901` to the function definition line. Append to `docs/complexity-review.md`:

```markdown
### `app/services/opening_position_service.py::continuation_flow` — Grade E

**Radon CC score:** <actual score>
**Why flagged:** <your one-sentence assessment>
**Recommendation:** <accept / needs refactor with domain knowledge>
```

- [ ] **Step 5: Repeat Steps 3–4 for `openings/services.py::continuation_flow`**

Note: if both are near-identical implementations, flag both and recommend deduplication as a separate decision.

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "refactor(complexity): evaluate grade-E functions — refactor or flag for review"
```

---

## Task 9: Evaluate & Act on Grade D Functions (Model: Sonnet)

**Functions (process one at a time):**

| File | Function | Grade |
|------|----------|-------|
| `app/ingest/sync_service.py` | `_upsert_game` | D |
| `app/services/lc0_service.py` | `analyze_pgn` | D |
| `app/services/stockfish_service.py` | `analyze_pgn` | D |
| `app/services/welcome_service.py` | `get_opening_flow` | D |
| `app/services/game_search_service.py` | `_sanitize_sql` | D |
| `app/services/analysis_service.py` | `get_game_analysis` | D |
| `app/services/opening_position_service.py` | `opening_tree_context` | D |
| `openings/services.py` | `opening_tree_context` | D |
| `dashboard/services.py` | `get_opening_flow` | D |
| `search/services.py` | `_sanitize_sql` | D |

For **each function**, follow this sequence:

- [ ] **Step A: Read the function**

```bash
/opt/homebrew/Cellar/python@3.9/3.9.25/Frameworks/Python.framework/Versions/3.9/bin/radon cc -s <file> | grep -A5 <function_name>
```

Then read the full function body in the file.

- [ ] **Step B: Apply the decision framework**

Hints by function type:
- **`_upsert_game`**: DB upsert — often has inherent branching for conflict handling. Check if branches are truly separable or just defensive.
- **`analyze_pgn` (lc0 + stockfish)**: Engine pipeline — "parse PGN → per-move loop → collect results" is often cleanly separable. Good refactor candidate.
- **`get_opening_flow` (welcome + dashboard)**: Sankey/tree builder — node construction and edge construction are often separable. Check if they share too much local state.
- **`_sanitize_sql` (game_search + search)**: Likely a long if-elif chain of validation rules. If both files are duplicates, flag for deduplication instead of refactoring each.
- **`get_game_analysis`**: Analysis pipeline — "load → process → format" stages are usually cleanly separable.
- **`opening_tree_context`**: Tree context builder — similar to continuation_flow; read carefully before deciding.

- [ ] **Step C (refactor path): Extract helpers, run xenon + tests**

```bash
# After editing:
/opt/homebrew/Cellar/python@3.9/3.9.25/Frameworks/Python.framework/Versions/3.9/bin/xenon \
  --max-absolute B --max-modules A --max-average A <file>

cd /Users/christopherwebster/Projects/wood_league/services/app
DJANGO_SETTINGS_MODULE=config.settings ../../.venv/bin/pytest . --tb=short -q
```

Expected: xenon exits 0, no test regressions.

- [ ] **Step D (flag path): Suppress + document**

Add `# noqa: C901` to the function def line. Append to `docs/complexity-review.md`:

```markdown
### `<file>::<function>` — Grade D

**Radon CC score:** <actual>
**Why flagged:** <assessment>
**Recommendation:** <accept as-is / needs domain knowledge to refactor / deduplicate with sibling>
```

- [ ] **Step E: Commit after each file**

```bash
git add -u
git commit -m "refactor(complexity): <function> in <file> — <refactored D→B | flagged for review>"
```

- [ ] **Step F: After all 10 functions — summarize the review file**

Add a summary section at the top of `docs/complexity-review.md`:

```markdown
## Summary

| Function | File | Grade | Decision |
|----------|------|-------|----------|
| ... | ... | ... | refactored / flagged |
```

Then commit:

```bash
git add docs/complexity-review.md
git commit -m "docs: add complexity review summary for human review"
```

---

## Task 10: Snyk Security Scan (Model: Sonnet)

**Scope:** Run Snyk code and dependency scans on the Django app, fix any findings.

- [ ] **Step 1: Run Snyk code scan**

Use the `snyk_code_scan` MCP tool targeting `services/app/`.

- [ ] **Step 2: Review findings**

For each issue:
- Critical/High: Fix immediately.
- Medium: Fix if quick; document if complex.
- Low/Info: Accept or suppress with justification.

- [ ] **Step 3: Run Snyk SCA scan for dependency vulnerabilities**

Use the `snyk_sca_scan` MCP tool on `services/app/pyproject.toml` or `requirements.txt`.

- [ ] **Step 4: Fix or suppress dependency vulnerabilities**

For any vulnerable packages: update to patched version if available and compatible.

- [ ] **Step 5: Re-scan to confirm clean**

Re-run `snyk_code_scan` and confirm 0 new issues introduced.

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "fix(security): address Snyk findings in Django app"
```

---

## Task 11: Final Quality Gate Verification (Model: Sonnet)

- [ ] **Step 1: Run full ruff check**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/app
/opt/homebrew/bin/ruff check .
```

Expected: 0 errors.

- [ ] **Step 2: Run bandit**

```bash
/Users/christopherwebster/.local/bin/bandit -ll -q -r . --exclude ./.venv,./migrations 2>&1
```

Expected: 0 issues (nosec warnings are acceptable if justified).

- [ ] **Step 3: Run xenon complexity check**

```bash
/opt/homebrew/Cellar/python@3.9/3.9.25/Frameworks/Python.framework/Versions/3.9/bin/xenon \
  --max-absolute B --max-modules A --max-average A .
```

Expected: exit 0, no grade C+ functions.

- [ ] **Step 4: Run mypy**

```bash
../../.venv/bin/mypy --ignore-missing-imports --follow-imports=skip --explicit-package-bases \
  --exclude migrations . 2>&1 | grep "error:"
```

Expected: 0 errors.

- [ ] **Step 5: Run full test suite**

```bash
DJANGO_SETTINGS_MODULE=config.settings ../../.venv/bin/pytest . -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 6: Verify all file headers present**

```bash
python3 -c "
import os
missing = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ['__pycache__', 'migrations', '.venv']]
    for f in files:
        if f.endswith('.py') and not f.startswith('__'):
            path = os.path.join(root, f)
            with open(path) as fh:
                content = fh.read(500)
            if 'Title:' not in content and 'Description:' not in content:
                missing.append(path)
print(f'Missing headers: {len(missing)}')
"
```

Expected: 0.

- [ ] **Step 7: Final commit**

```bash
git add -u
git commit -m "chore: final quality gate — all checks pass"
```

---

## Self-Review

**Spec coverage:**
- ✅ "runs" — Task 3 (Django test setup), Task 11 (full test suite)
- ✅ "consistent with code quality standards" — Tasks 1–2 (ruff), Task 8–9 (complexity)
- ✅ "documentation standards" — Tasks 6–7 (headers, docstrings)
- ✅ "code quality and security scanning" — Task 10 (Snyk), Tasks 1–5 (full pipeline)
- ✅ "fix problems" — each task fixes what the scan finds
- ✅ "plan first" — this is the plan
- ✅ "delegate to cheaper models" — model routing noted per task (Haiku for mechanical, Sonnet for reasoning)

**Model routing summary:**
| Task | Model |
|------|-------|
| 1 — ruff auto-fix | Haiku |
| 2 — ruff manual | Haiku |
| 3 — Django test setup | Sonnet |
| 4 — mypy attr errors | Sonnet |
| 5 — mypy type errors | Sonnet |
| 6 — file headers | Haiku |
| 7 — docstrings | Haiku |
| 8 — grade E refactor | Sonnet |
| 9 — grade D refactor | Sonnet |
| 10 — Snyk scan | Sonnet |
| 11 — final verification | Sonnet |

**Placeholder scan:** No TBD/TODO/similar patterns in this plan. All steps include commands or code.

**Type consistency:** No function signatures defined across tasks — each task is self-contained with discovery commands before edits.
