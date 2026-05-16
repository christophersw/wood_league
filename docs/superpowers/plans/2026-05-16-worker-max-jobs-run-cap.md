# Worker run cap (`--max-jobs`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the worker's `--batch-size` chunk-claim with one-job-at-a-time checkout plus a new `--max-jobs` run cap, so workers never hold reserved-but-unstarted jobs and a run stops after N completed jobs (or queue-empty / `--batch-time`, whichever first).

**Architecture:** `run_batch`'s per-engine drain (`_drain_engine_queue`) is restructured to launch the warm lc0 engine once per engine run, then loop `checkout(count=1) → run_one_job → submit → count++`, stopping on OR of {queue-empty, `max_jobs`, `batch_time`, `stop_event`}. `default_batch_size`/`WLW_DEFAULT_BATCH_SIZE`/`--batch-size` are cleanly removed (no alias); `max_jobs`/`WLW_MAX_JOBS`/`--max-jobs` added, parsed like the existing optional-int `batch_time_minutes`.

**Tech Stack:** Python 3.11, Typer + questionary CLI, dataclass settings, pytest.

**Spec:** `docs/superpowers/specs/2026-05-15-worker-max-jobs-run-cap-design.md`

---

## Context

`--batch-size` (default 5, env `WLW_DEFAULT_BATCH_SIZE`, clamped 1–10) controls *jobs claimed per checkout call*. Claiming a chunk reserves up to N jobs on one worker before they start, delaying their submission and starving other workers. Results are already submitted per-job (`run_one_job` calls `complete_lc0`/`complete_stockfish` immediately), so only *claim* behaviour is wrong. This is sub-project **E**; its spec is approved. The vast.ai deployment (#126, merged) already wired `WLW_MAX_JOBS` conditionally into `services/local_worker/vast/onstart.sh`, so once this lands the vast bounded-run behaviour activates automatically with no further change there.

## Current-state reconciliation (spec was written pre-#126)

- **Version:** spec says bump `0.9.5 → 0.9.6`; the worker is now at **`0.9.7`** (bumped by #126). This plan bumps **`0.9.7 → 0.9.8`** and the release tag is `worker-v0.9.8`.
- **`run_loop`** in the spec = the actual `run_batch` + its inner `_drain_engine_queue` in `services/local_worker/local_worker/loop.py`.
- **`vast/onstart.sh`** already uses `${WLW_MAX_JOBS:+--max-jobs "${WLW_MAX_JOBS}"}` and no `--batch-size` → **verify-only**, no change.

## File Structure

**Modify:**
- `services/local_worker/local_worker/config.py` — add `Settings.max_jobs`; add `WLW_MAX_JOBS` optional-int override; remove `default_batch_size` field + `WLW_DEFAULT_BATCH_SIZE` mapping.
- `services/local_worker/local_worker/loop.py` — `run_batch` signature (`batch_size`→removed, add `max_jobs`); restructure `_drain_engine_queue` to one-at-a-time + hoisted warm engine + processed counter + `max_jobs` stop.
- `services/local_worker/local_worker/commands/run.py` — `run()` `--batch-size`→`--max-jobs` option; `_resolve_run_options` prompt + return tuple; `run_batch(...)` call.
- `services/local_worker/runpod/bootstrap.sh` — drop `--batch-size 10` from both engine launches (keep `--batch-time 1440`).
- `services/local_worker/README.md` (and any doc referencing `--batch-size`/`WLW_DEFAULT_BATCH_SIZE`).
- `services/local_worker/pyproject.toml` — version `0.9.7` → `0.9.8`.
- Tests: `tests/test_config_env.py`, `tests/test_loop.py`, `tests/test_run_command.py` (verify exact filenames; adapt to actual layout).

**Verify-only (no change expected):**
- `services/local_worker/runpod/runpod_start.sh`, `services/local_worker/vast/onstart.sh` — confirm no `--batch-size` reference.

**Reused (do not change signature):**
- `WorkerClient.checkout(engine, worker_id, batch_size, game_id, dispatch_mode)` in `services/local_worker/local_worker/worker_client/client.py` and `packages/shared/wood_league_shared/worker_client/client.py` — keep the API; always call with the count arg = `1`.
- `run_one_job(...)`, `_engine_alive(...)`, `lc0_launch_engine(...)` in `loop.py` — unchanged.

---

## Task 1: config — add `max_jobs` + `WLW_MAX_JOBS`

**Files:**
- Modify: `services/local_worker/local_worker/config.py`
- Test: `services/local_worker/tests/test_config_env.py`

- [ ] **Step 1: Write the failing tests**

Append to `services/local_worker/tests/test_config_env.py` (match the file's existing import/fixture style; it already has helpers to set/clear `WLW_*` env and call `load_settings`):

```python
def test_wlw_max_jobs_parses_int(monkeypatch, tmp_path):
    monkeypatch.setenv("WLW_MAX_JOBS", "25")
    s = load_settings(tmp_path / "settings.json")
    assert s.max_jobs == 25


def test_wlw_max_jobs_blank_or_nondigit_is_none(monkeypatch, tmp_path):
    monkeypatch.setenv("WLW_MAX_JOBS", "")
    assert load_settings(tmp_path / "settings.json").max_jobs is None
    monkeypatch.setenv("WLW_MAX_JOBS", "abc")
    assert load_settings(tmp_path / "settings.json").max_jobs is None


def test_wlw_max_jobs_lt_one_is_none(monkeypatch, tmp_path):
    monkeypatch.setenv("WLW_MAX_JOBS", "0")
    assert load_settings(tmp_path / "settings.json").max_jobs is None
    monkeypatch.setenv("WLW_MAX_JOBS", "-3")
    assert load_settings(tmp_path / "settings.json").max_jobs is None


def test_default_max_jobs_is_none(tmp_path):
    assert load_settings(tmp_path / "settings.json").max_jobs is None
```

(If `load_settings` import or signature differs in the file, match what the existing `WLW_BATCH_TIME_MINUTES` tests in this file already do.)

- [ ] **Step 2: Run, verify FAIL**

Run: `cd services/local_worker && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && python -m pytest tests/test_config_env.py -k max_jobs -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'max_jobs'`.

- [ ] **Step 3: Implement in `config.py`**

(a) Add the field to `Settings` immediately after `batch_time_minutes: Optional[int] = None` (line ~47):

```python
    max_jobs: Optional[int] = None
```

(b) Add an applier mirroring `_apply_optional_int_override`, with the `< 1 → None` rule. Place it directly after `_apply_optional_int_override` (ends ~line 164):

```python
def _apply_max_jobs_override(settings: Settings) -> None:
    """Apply the optional-int ``WLW_MAX_JOBS`` override.

    Blank / non-integer → leave as-is (``None`` default). A parsed value
    ``< 1`` (e.g. ``0`` or negative) is treated as unset so a degenerate
    cap can never stop the run before it starts.
    """
    raw = os.environ.get("WLW_MAX_JOBS")
    if not raw:
        return
    try:
        parsed = int(raw)
    except ValueError:
        return
    settings.max_jobs = parsed if parsed >= 1 else None
```

(c) Wire it into `_apply_env_overrides` (after the `_apply_optional_int_override(settings)` line):

```python
    _apply_optional_int_override(settings)
    _apply_max_jobs_override(settings)
```

- [ ] **Step 4: Run, verify PASS**

Run: `python -m pytest tests/test_config_env.py -v`
Expected: PASS (new max_jobs tests + all existing config-env tests still green).

- [ ] **Step 5: Quality gate + commit**

Run (must be clean): `ruff check local_worker/config.py tests/test_config_env.py && mypy local_worker/config.py`
Then commit (worktree root):
```bash
git add services/local_worker/local_worker/config.py services/local_worker/tests/test_config_env.py
git commit -m "feat(worker): add max_jobs setting + WLW_MAX_JOBS override

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: loop + run.py — one-at-a-time checkout, `max_jobs`, hoisted warm engine

This is the core refactor. It changes `run_batch`'s signature and its only production call site (`commands/run.py`) together so the suite never sees a half-renamed state.

**Files:**
- Modify: `services/local_worker/local_worker/loop.py` (`run_batch`, `_drain_engine_queue`)
- Modify: `services/local_worker/local_worker/commands/run.py` (`run`, `_resolve_run_options`)
- Test: `services/local_worker/tests/test_loop.py`, `services/local_worker/tests/test_run_command.py`

- [ ] **Step 1: Write the failing tests (loop behaviour)**

Add to `services/local_worker/tests/test_loop.py` (match its existing fakes for `WorkerClient`/jobs/engine; the file already exercises `run_batch`). These assert the new contract:

```python
def test_checkout_is_always_count_one(monkeypatch):
    """Every checkout call requests exactly one job (no chunk reservation)."""
    client = FakeClient(jobs_per_engine={"stockfish": _n_jobs(3)})
    counts = []
    orig = client.checkout
    def spy(**kw):
        counts.append(kw.get("batch_size"))
        return orig(**kw)
    client.checkout = spy
    run_batch(settings=_settings(), engines=["stockfish"], max_jobs=None,
              _client=client)  # see Step 3 for the _client seam
    assert counts and all(c == 1 for c in counts)


def test_max_jobs_stops_after_n_completed(monkeypatch):
    client = FakeClient(jobs_per_engine={"stockfish": _n_jobs(10)})
    stats = run_batch(settings=_settings(), engines=["stockfish"],
                      max_jobs=3, _client=client)
    assert stats.games_processed == 3


def test_blank_max_jobs_drains_until_empty():
    client = FakeClient(jobs_per_engine={"stockfish": _n_jobs(4)})
    stats = run_batch(settings=_settings(), engines=["stockfish"],
                      max_jobs=None, _client=client)
    assert stats.games_processed == 4


def test_warm_lc0_engine_launched_once_across_single_job_claims(monkeypatch):
    launches = []
    monkeypatch.setattr("local_worker.loop.lc0_launch_engine",
                        lambda **kw: (launches.append(1) or (FakeEngine(), "BT4")))
    client = FakeClient(jobs_per_engine={"lc0": _n_jobs(5)})
    run_batch(settings=_settings(), engines=["lc0"], max_jobs=None,
              _client=client)
    assert len(launches) == 1  # one warm engine spans all 5 single-job claims


def test_max_jobs_and_batch_time_first_to_hit_wins(monkeypatch):
    # batch_time tiny -> time cap fires before the count cap
    client = FakeClient(jobs_per_engine={"stockfish": _n_jobs(100)})
    stats = run_batch(settings=_settings(), engines=["stockfish"],
                      max_jobs=100, batch_time_minutes=0, _client=client)
    assert stats.games_processed < 100
```

> **Adapt to the file's actual harness.** `test_loop.py` already constructs a fake client/jobs/engine and calls `run_batch`. Reuse those exact helpers (their real names/shapes) instead of the `FakeClient`/`_n_jobs`/`_settings`/`FakeEngine` placeholders above — keep the *assertions* (count==1, stops at N, drains all, one launch, first-cap-wins) and the new `max_jobs=` kwarg. If `run_batch` is currently called in tests with `batch_size=`, update those call sites to drop `batch_size` and pass `max_jobs=` as appropriate.

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_loop.py -v`
Expected: FAIL — `run_batch() got an unexpected keyword argument 'max_jobs'` (and/or the `_client` seam / count assertions).

- [ ] **Step 3: Refactor `loop.py`**

In `run_batch` (currently `def run_batch(*, settings, engines, batch_size=5, batch_time_minutes=None, game_id=None, on_job_start=None, on_job_done=None, on_progress=None, on_jobs_claimed=None, stop_event=None)`):

(a) **Signature:** remove `batch_size: int = 5`; add `max_jobs: Optional[int] = None`. If the test harness needs to inject a client, also add an optional injection seam `_client=None` and use it when provided (`client = _client if _client is not None else WorkerClient(base_url=settings.api_url, api_key=settings.api_key)`); otherwise keep the existing construction. Update the docstring (Args: `max_jobs` replaces `batch_size`).

(b) **Processed counter:** add `processed = 0` next to `stats`/`start_time`. Add a helper next to `_should_stop`:

```python
    def _cap_reached() -> bool:
        """True once the optional max_jobs run cap is hit."""
        return max_jobs is not None and processed >= max_jobs
```

Note `processed` is mutated inside `_drain_engine_queue`; use `nonlocal processed` there.

(c) **Restructure `_drain_engine_queue(engine)`** so the warm lc0 engine is launched ONCE per engine run (hoisted above the claim loop, not per claimed batch), and jobs are claimed one at a time:

```python
    def _drain_engine_queue(engine: str) -> None:
        """Claim one job at a time for `engine`, analyse+submit, until the
        queue is empty / max_jobs / batch_time / stop_event — whichever
        first. The warm lc0 engine (issue #117) is launched once for the
        whole engine run and quit on exit; a dead engine is relaunched by
        the existing _engine_alive guard inside the loop.
        """
        nonlocal processed
        warm_engine = None
        warm_network_name = ""
        if engine == "lc0":
            try:
                warm_engine, warm_network_name = lc0_launch_engine(
                    lc0_path=settings.lc0_path,
                    weights_path=settings.lc0_weights_path,
                    syzygy_path=settings.syzygy_path,
                    backend=settings.lc0_backend or "cpu",
                )
            except Exception:  # noqa: BLE001
                log.warning(
                    "lc0: warm engine launch failed; per-job cold-start",
                    exc_info=True,
                )
                warm_engine = None
        try:
            while True:
                if _should_stop() or _cap_reached():
                    break
                _send_heartbeat(engine)
                try:
                    jobs = client.checkout(
                        engine=engine,
                        worker_id=worker_id,
                        batch_size=1,
                        game_id=game_id,
                        dispatch_mode="pull",
                    )
                except WorkerClientError as exc:
                    log.error("Checkout failed for %s: %s", engine, exc)
                    break
                if not jobs:
                    break
                job = jobs[0]
                if on_jobs_claimed:
                    on_jobs_claimed([job])
                if on_job_start:
                    on_job_start(job)
                job_start = time.monotonic()
                success = run_one_job(
                    job=job,
                    settings=settings,
                    stats=stats,
                    client=client,
                    progress_callback=on_progress,
                    lc0_engine=warm_engine if engine == "lc0" else None,
                    lc0_network_name=warm_network_name,
                )
                processed += 1
                if (
                    engine == "lc0"
                    and warm_engine is not None
                    and not _engine_alive(warm_engine)
                ):
                    log.warning("lc0: warm engine died; relaunching")
                    try:
                        warm_engine, warm_network_name = lc0_launch_engine(
                            lc0_path=settings.lc0_path,
                            weights_path=settings.lc0_weights_path,
                            syzygy_path=settings.syzygy_path,
                            backend=settings.lc0_backend or "cpu",
                        )
                    except Exception:  # noqa: BLE001
                        log.warning(
                            "lc0: relaunch failed; remaining jobs cold-start",
                            exc_info=True,
                        )
                        warm_engine = None
                        warm_network_name = ""
                if on_job_done:
                    on_job_done(job, success, time.monotonic() - job_start)
        finally:
            if warm_engine is not None:
                try:
                    warm_engine.quit()
                except Exception:  # noqa: BLE001
                    log.warning("lc0: warm engine quit failed", exc_info=True)
```

(d) Keep the existing outer `for engine in engines: if _should_stop() or _cap_reached(): break; _drain_engine_queue(engine)` (add the `_cap_reached()` check alongside `_should_stop()` so a cap reached during engine A stops before engine B).

> This preserves every existing behaviour (warm-engine reuse, `_engine_alive` relaunch, per-job submit, heartbeat, callbacks, `game_id` single-checkout) and only changes: chunk size → 1, warm engine hoisted to once-per-engine, `processed`/`max_jobs` stop. Match the exact symbol names already in `loop.py` (`WorkerClientError`, `run_one_job`, `lc0_launch_engine`, `_engine_alive`, `_send_heartbeat`, `log`, `time`, `worker_id`) — do not introduce new ones.

- [ ] **Step 4: Update the production call site + prompt in `commands/run.py`**

(a) `run()` option: replace the `batch_size` parameter with `max_jobs`:

```python
def run(
    engine: Optional[str] = typer.Option(
        None, help="Force engine: stockfish, lc0, or both"
    ),
    max_jobs: Optional[int] = typer.Option(
        None, help="Stop after this many completed jobs (blank = until queue empty)"
    ),
    batch_time: Optional[int] = typer.Option(
        None, help="Run for this many minutes then stop"
    ),
) -> None:
```

(b) `_resolve_run_options` — rename param, change prompt, return `max_jobs`:

```python
def _resolve_run_options(
    engine: Optional[str],
    max_jobs: Optional[int],
    batch_time: Optional[int],
) -> tuple[list[str], Optional[int], Optional[int]]:
    """Resolve run options, prompting interactively if needed.

    Returns:
        Tuple of (engines list, max_jobs, batch_time_minutes).
    """
    if engine is None:
        engine = questionary.select(
            "Which engines should this worker process?",
            choices=["stockfish", "lc0", "both"],
        ).ask()

    if max_jobs is None:
        mj_raw = questionary.text(
            "Max jobs this run? (blank = until queue empty):"
        ).ask()
        max_jobs = int(mj_raw) if mj_raw and mj_raw.strip().isdigit() else None

    if batch_time is None:
        bt_raw = questionary.text(
            "Run for how many minutes? (leave blank to run until queue empty):"
        ).ask()
        batch_time = int(bt_raw) if bt_raw and bt_raw.strip().isdigit() else None

    engines = ["stockfish", "lc0"] if engine == "both" else [engine]
    return engines, max_jobs, batch_time
```

(c) Update `run()` body: `engines, max_jobs, batch_time = _resolve_run_options(engine, max_jobs, batch_time)` and the `run_batch(...)` call → replace `batch_size=batch_size,` with `max_jobs=max_jobs,`. If `settings.max_jobs` should seed an unset CLI value, prefer the explicit CLI/prompt value; when both unset leave `None` (env `WLW_MAX_JOBS` already lands on `settings.max_jobs` — pass `max_jobs if max_jobs is not None else settings.max_jobs`).

- [ ] **Step 5: Add/adjust `test_run_command.py`**

Ensure tests assert: `--max-jobs` option exists; passing `--batch-size` errors as an unknown option; the interactive prompt text is `"Max jobs this run? (blank = until queue empty):"`. Match the file's existing CliRunner/monkeypatch patterns. Example assertions:

```python
def test_run_has_max_jobs_option_and_no_batch_size():
    from typer.testing import CliRunner
    from local_worker.cli import app
    res = CliRunner().invoke(app, ["run", "--help"])
    assert "--max-jobs" in res.output
    assert "--batch-size" not in res.output

def test_batch_size_flag_is_unknown_option():
    from typer.testing import CliRunner
    from local_worker.cli import app
    res = CliRunner().invoke(app, ["run", "--batch-size", "10"])
    assert res.exit_code != 0
```

- [ ] **Step 6: Run, verify PASS**

Run: `python -m pytest tests/test_loop.py tests/test_run_command.py -v`
Expected: PASS — new behaviour green, no regressions.

- [ ] **Step 7: Quality gate + commit**

Run (clean): `ruff check local_worker/loop.py local_worker/commands/run.py tests/test_loop.py tests/test_run_command.py && mypy local_worker/loop.py local_worker/commands/run.py`
(Pre-existing unrelated `loop.py` mypy errors at the `Lc0GameResult`/`StockfishGameResult` lines are out of scope — confirm you introduced no NEW errors vs. before.)
Commit:
```bash
git add services/local_worker/local_worker/loop.py services/local_worker/local_worker/commands/run.py services/local_worker/tests/test_loop.py services/local_worker/tests/test_run_command.py
git commit -m "feat(worker): one-at-a-time checkout + --max-jobs run cap

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Remove `default_batch_size` / `WLW_DEFAULT_BATCH_SIZE` (clean rename)

Now that nothing reads it, delete it with no alias (spec: surface the change, don't silently flip behaviour).

**Files:**
- Modify: `services/local_worker/local_worker/config.py`
- Test: `services/local_worker/tests/test_config_env.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config_env.py`:

```python
def test_default_batch_size_field_removed():
    from local_worker.config import Settings
    assert "default_batch_size" not in Settings.__dataclass_fields__


def test_wlw_default_batch_size_no_longer_mapped():
    import local_worker.config as cfg
    assert "WLW_DEFAULT_BATCH_SIZE" not in cfg._INT_ENV_FIELDS
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_config_env.py -k "batch_size" -v`
Expected: FAIL (field/key still present).

- [ ] **Step 3: Implement**

In `config.py`: delete the `default_batch_size: int = 5` line from `Settings`, and delete the `"WLW_DEFAULT_BATCH_SIZE": "default_batch_size",` entry from `_INT_ENV_FIELDS`. Grep the package to confirm no remaining references: `cd services/local_worker && grep -rn "default_batch_size\|WLW_DEFAULT_BATCH_SIZE" local_worker || echo "clean"` → expect `clean`. (Persisted JSON settings with a stale `default_batch_size` key are already tolerated: `load_settings` filters unknown keys via the `known` set.)

- [ ] **Step 4: Run, verify PASS**

Run: `python -m pytest tests/test_config_env.py -v` → PASS. Then full suite quick check: `python -m pytest -q` → no regressions.

- [ ] **Step 5: Quality gate + commit**

`ruff check local_worker/config.py tests/test_config_env.py && mypy local_worker/config.py`
```bash
git add services/local_worker/local_worker/config.py services/local_worker/tests/test_config_env.py
git commit -m "refactor(worker): remove default_batch_size / WLW_DEFAULT_BATCH_SIZE (clean rename)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: RunPod / vast launch scripts

Spec risk: if `bootstrap.sh` still passes the now-unknown `--batch-size 10`, both engine processes abort on a headless pod. Must land with the code.

**Files:**
- Modify: `services/local_worker/runpod/bootstrap.sh`
- Verify-only: `services/local_worker/runpod/runpod_start.sh`, `services/local_worker/vast/onstart.sh`

- [ ] **Step 1: Locate the launches**

Run: `cd services/local_worker && grep -n "batch-size\|batch-time\|wood-league-worker .* run" runpod/bootstrap.sh runpod/runpod_start.sh vast/onstart.sh`
Expected: two `--batch-size 10` occurrences in `runpod/bootstrap.sh` (the lc0 and stockfish launches, each with `--batch-time 1440`); none in `runpod_start.sh`; `vast/onstart.sh` shows `${WLW_MAX_JOBS:+--max-jobs ...}` and no `--batch-size`.

- [ ] **Step 2: Edit `runpod/bootstrap.sh`**

Two changes:
1. In each of the two launch lines (`~172` stockfish, `~176` lc0) `wood-league-worker --telemetry run --engine <eng> --batch-size 10 --batch-time 1440`, delete ` --batch-size 10` only → `wood-league-worker --telemetry run --engine <eng> --batch-time 1440` (no `--max-jobs` → drain until empty, bounded by the 24h time ceiling, per spec).
2. The cosmetic log line (`~161`) `log "launching parallel engines: stockfish + lc0 (batch-size=10 each)"` — drop the now-false `(batch-size=10 each)` so it reads `log "launching parallel engines: stockfish + lc0"`.

- [ ] **Step 3: Verify**

Run: `grep -n "batch-size" runpod/bootstrap.sh runpod/runpod_start.sh vast/onstart.sh || echo "no batch-size anywhere — good"`
Expected: `no batch-size anywhere — good`.
Run: `shellcheck -S error runpod/bootstrap.sh` → zero error-severity. (`vast/onstart.sh` unchanged — no action; confirm it still references `WLW_MAX_JOBS` so this plan's E support activates it.)

- [ ] **Step 4: Commit**

```bash
git add services/local_worker/runpod/bootstrap.sh
git commit -m "fix(worker): drop --batch-size 10 from RunPod bootstrap (clean rename)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Docs + version bump

**Files:**
- Modify: `services/local_worker/README.md` (and any other doc referencing `--batch-size`/`WLW_DEFAULT_BATCH_SIZE`)
- Modify: `services/local_worker/pyproject.toml`

- [ ] **Step 1: Find doc references**

Run: `cd services/local_worker && grep -rn "batch-size\|batch_size\|WLW_DEFAULT_BATCH_SIZE" README.md docs 2>/dev/null || echo "none"`

- [ ] **Step 2: Update docs**

For each hit, replace the `--batch-size` / `WLW_DEFAULT_BATCH_SIZE` explanation with `--max-jobs` / `WLW_MAX_JOBS`: "Stop after this many completed jobs; blank/unset = run until the queue is empty. Checkout is always one job at a time." Keep `--batch-time` docs as-is. If there are no references, state that and skip.

- [ ] **Step 3: Version bump**

In `services/local_worker/pyproject.toml`, change `version = "0.9.7"` to `version = "0.9.8"`. (Reconciled: spec said 0.9.5→0.9.6, but #126 already moved it to 0.9.7.)

- [ ] **Step 4: Verify + commit**

Run: `python -m pip install -e . --dry-run 2>&1 | tail -1` (resolves). 
```bash
git add services/local_worker/README.md services/local_worker/pyproject.toml
git commit -m "docs(worker): --max-jobs replaces --batch-size; bump 0.9.7 -> 0.9.8

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
(Include any other updated doc files in the `git add`.)

---

## Task 6: Full suite + quality gate

**Files:** none (verification only)

- [ ] **Step 1: Full worker suite**

Run: `cd services/local_worker && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && python -m pytest -q`
Expected: all pass / pre-existing skips only; no regressions vs. the 296-passed baseline (count changes only by net new tests).

- [ ] **Step 2: Quality gate on changed files**

Run, in order, on changed Python (`config.py`, `loop.py`, `commands/run.py`, the three test files): `ruff check` → `bandit -q -r` → `semgrep --error --quiet --config=auto` → `xenon --max-absolute B --max-modules B --max-average A` → `mypy` (no NEW errors vs. baseline; pre-existing `loop.py` `Lc0GameResult`/`StockfishGameResult` mypy errors are out of scope) → `pytest --cov`.
Expected: clean. Fix any *new* finding; if a Halstead `:WARN` appears on a test file, assess it the way the #126 review did (advisory; only act on real complexity).

- [ ] **Step 3: Acceptance check (spec §Acceptance)**

Confirm by inspection/tests: checkout count is always 1; `--max-jobs N` stops after N; blank/unset drains; `--batch-time` still caps (first-to-hit wins); one warm lc0 engine spans a run (relaunched only on death); `--batch-size`/`WLW_DEFAULT_BATCH_SIZE` fully gone; RunPod script + docs updated; version `0.9.8`.

- [ ] **Step 4: Commit any gate fixes** (skip if none)

```bash
git add -A && git commit -m "chore(worker): quality-gate fixes for --max-jobs run cap

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Verification (end-to-end)

1. `cd services/local_worker && pytest -q` — green, no regressions.
2. Quality gate clean on changed files (Task 6).
3. `wood-league-worker run --help` shows `--max-jobs`, not `--batch-size`; `wood-league-worker run --batch-size 10` errors "no such option".
4. Spec §Acceptance items all satisfied (Task 6 Step 3).
5. Release: tag `worker-v0.9.8` (matches `pyproject.toml`) per the existing publish process — performed by the human after merge, not in this plan.

## Self-Review Notes

- **Spec coverage:** one-at-a-time checkout (T2), `--max-jobs`/`WLW_MAX_JOBS` count cap with `<1→None` (T1,T2), warm lc0 engine launched once per run + `_engine_alive` relaunch preserved (T2), `--batch-time`/`stop_event`/queue-empty OR'd stop (T2), clean removal of `--batch-size`/`WLW_DEFAULT_BATCH_SIZE` with no alias incl. `--batch-size` now an unknown-option error (T2,T3), interactive prompt reworded (T2), RunPod `bootstrap.sh` updated + `runpod_start.sh`/`vast/onstart.sh` verified (T4), docs + version bump (T5, reconciled to 0.9.7→0.9.8), tests across the three named files (T1–T3), risks (RunPod regression: scripts land with code in T4; warm-engine regression: explicit "launched once" test in T2).
- **No placeholders:** every code/test/script step has concrete content; the `test_loop.py`/`test_config_env.py`/`test_run_command.py` harness-adaptation notes are explicit instructions to match existing fixtures, not deferred work.
- **Type/name consistency:** `max_jobs: Optional[int]` used identically across `Settings`, `_apply_max_jobs_override`, `run_batch`, `run`/`_resolve_run_options`; `WLW_MAX_JOBS` env name consistent; `checkout(... batch_size=1 ...)` keeps the existing client API unchanged; reused `loop.py` symbols (`WorkerClientError`, `run_one_job`, `lc0_launch_engine`, `_engine_alive`, `_send_heartbeat`) referenced by their actual names.
