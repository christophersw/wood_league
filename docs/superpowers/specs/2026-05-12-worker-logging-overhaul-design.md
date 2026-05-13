# Worker Logging Overhaul — Design

**Status:** Approved (2026-05-12)
**Issue:** [#43 — Logging issues on Windoze Local Runner](https://github.com/christophersw/wood_league/issues/43)
**Component:** `services/local_worker` (PyPI: `wood-league-worker`)

## Background

Two problems are bundled in #43:

1. **Bug.** On Windows, `wood-league-worker logs` fails with
   `Could not read log: [WinError 2] The system cannot find the file specified`.
   Root cause: `cli.py` shells out to the Unix `tail` binary
   (`services/local_worker/local_worker/cli.py:519,526`), which does not exist
   on Windows.
2. **Feature gap.** The current logger (stdlib `RotatingFileHandler`) lacks:
   user-settable log level, hardware/driver capture, single-session file
   semantics with automatic cleanup, and any remote diagnostics path.

## Goals

- Fix the Windows `tail` bug so `logs --tail` and `logs --follow` work on
  Windows, macOS, and Linux.
- Replace the stdlib logger with `loguru` for ergonomic level/rotation/format
  control.
- Capture host hardware, drivers, and engine selection at the top of every
  worker session so performance issues are diagnosable from the log alone.
- Keep only the most recent session's log locally; rely on **GlitchTip** for
  historical / remote diagnostics.
- Make remote logging opt-in via a first-run prompt; honour the choice forever.

## Non-Goals

- No replacement of Django-side application logging (still stdlib `logging`).
- No multi-file rotation or retention sweeps — the local file is single-session
  and overwritten by the next `run`.
- No structured/JSON log format. Local file is human-readable; GlitchTip
  receives structured events via `sentry-sdk`.
- No log-collection UI on the Django side (GlitchTip is the destination).

## Approach

Stack chosen after evaluating alternatives:

- **loguru** for the worker's logging backbone. ~20k★ MIT, ergonomic
  level/rotation/retention/format. A one-liner `InterceptHandler` bridges
  stdlib `logging` (python-chess, httpx, urllib3) into loguru.
- **GlitchTip** (AGPL, self-hostable, Sentry-API-compatible) for remote
  collection. Wire up via the unmodified `sentry-sdk` pointed at our DSN;
  `LoggingIntegration` automatically ships WARNING+ breadcrumbs and ERROR+
  events.

Alternatives considered: `structlog` (too JSON-first for a CLI), plain stdlib
`logging` (every requested feature hand-rolled), home-grown Django upload
endpoint (reinvents Sentry-style dedup, grouping, PII scrubbing).

## Architecture

### Module changes

#### `services/local_worker/local_worker/logging_setup.py` (rewritten)

```python
def configure_logging(level: str = "INFO", reset_file: bool = False) -> Path:
    """Install loguru sinks for this CLI invocation.

    Args:
        level: Threshold for the file sink. Accepts loguru level names
            (TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL), case-insensitive.
        reset_file: If True, truncate the main log file before opening it
            (called from long-running commands). If False, attach to a
            secondary diagnostics sink so read-only commands do not clobber
            the run log.

    Returns:
        Path to the main `worker.log` file.
    """

def log_session_banner(log_file: Path) -> None:
    """Write the hardware/driver/engine block as the first lines of a fresh
    session. Called once, immediately after `configure_logging(reset_file=True)`.
    """

def _detect_environment() -> dict[str, Any]:
    """Probe host OS/arch, Python version, torch availability + CUDA + MPS,
    GPU list, engine binaries on PATH, Syzygy presence. Pure function; all
    OS calls go through small helpers so tests can mock per-platform.
    """

class _InterceptHandler(logging.Handler):
    """Forwards stdlib logging records into loguru with correct level + frame
    so third-party libraries appear in the same sink as our own logger.
    """
```

#### `services/local_worker/local_worker/telemetry.py` (new)

```python
_DEFAULT_GLITCHTIP_DSN: str = "<baked-in>"  # overridable via env

def init_telemetry(consent: bool, release: str, dsn: str | None = None) -> bool:
    """Initialise sentry_sdk against GlitchTip. No-op if consent is False or
    DSN resolves to empty. Returns True if telemetry was actually initialised.

    Integrations: LoggingIntegration(level=INFO, event_level=ERROR).
    Tags: release, os, arch, python, engine_selection, worker_id (hashed).
    """

def prompt_for_consent(config_path: Path) -> bool:
    """First-run interactive prompt. Persists `{telemetry: bool, asked_at: iso}`
    to the worker config file. Returns the current consent value (cached if
    previously answered).
    """

def set_consent(config_path: Path, value: bool) -> None:
    """Used by `telemetry enable` / `telemetry disable` subcommands."""
```

#### `services/local_worker/local_worker/cli.py` (modified)

- Global typer option:
  `--log-level` (env `WOOD_LEAGUE_LOG_LEVEL`, default `INFO`).
- Global flags: `--telemetry` / `--no-telemetry` override the config for one
  invocation.
- `LONG_RUNNING_COMMANDS = {"run"}` — set used by `_startup` to decide
  `reset_file=True` vs. attaching to the diagnostics sink.
- `_startup` new flow:
  1. Resolve effective log level (flag > env > config > default).
  2. `configure_logging(level, reset_file=ctx.invoked_subcommand in LONG_RUNNING_COMMANDS)`.
  3. If `reset_file`: call `log_session_banner(log_file)`.
  4. If long-running: resolve consent (config; or call `prompt_for_consent`
     if never asked) and call `init_telemetry(...)`.
- `logs` command rewritten — Python-native tail using `collections.deque`
  for the initial read and a polling loop (`time.sleep(0.5)` + `seek`) for
  `--follow`. No `subprocess`, no `tail` binary. Closes #43.
- New `telemetry` Typer sub-app:
  `telemetry status` / `telemetry enable` / `telemetry disable`.

### Log file lifecycle

- Single primary file:
  `platformdirs.user_log_dir("wood-league-worker", "WoodLeague")/worker.log`.
- `run` truncates it on entry and writes the banner; subsequent log lines
  append until the command exits.
- Read-only commands (`logs`, `version`, `status`, `models`, `telemetry *`)
  configure logging at WARNING threshold to a side sink
  `worker.diagnostics.log` (loguru rotation `1 MB`, retention `1` file). The
  primary `worker.log` is left untouched so `logs` always shows the last
  real run.
- No multi-file rotation or retention sweeps on the primary file — one file,
  overwritten on the next `run`. Item 4 ("purge older logs") is satisfied by
  truncation; remote retention is GlitchTip's responsibility.

### Hardware / driver banner (item 3)

Sample first lines of a fresh session:

```
=== wood-league-worker 0.3.0 — session 2026-05-12T21:30:12Z ===
host: Darwin arm64 25.3.0 / Python 3.12.4
torch: 2.4.0  cuda=False  mps=True
gpus: []  (mps available)
engines: stockfish 17 @ /usr/local/bin/stockfish; lc0 0.31 @ /opt/lc0/lc0
selected engine: stockfish (threads=4, hash=512MB)
syzygy: dtz+wdl present at ~/.wood-league/syzygy (5-piece)
telemetry: enabled (glitchtip)
```

All detection lives inside `_detect_environment()`. Failures probing any
single field degrade to `unknown` rather than aborting the banner.

### GlitchTip integration

- `sentry-sdk>=2.0`, unchanged, pointed at GlitchTip DSN.
- DSN resolution order: `WOOD_LEAGUE_GLITCHTIP_DSN` env var → baked-in
  default. Empty string disables.
- First-run UX (only on `run`):
  ```
  Help debug worker issues by sending anonymous diagnostics
  (errors, hardware info) to <glitchtip host>? [y/N]
  ```
  Answer persisted to the worker config file. Never re-prompted unless the
  config is deleted.
- Runtime override: `--telemetry` / `--no-telemetry` for one invocation;
  `wood-league-worker telemetry enable|disable` to update the persisted
  choice.
- Tags attached on init: `release`, `os`, `arch`, `python`, `engine`,
  `worker_id` (SHA-256 of the install token, first 12 chars).

### CLI surface (final)

```
wood-league-worker --log-level=debug run
wood-league-worker --no-telemetry run
wood-league-worker telemetry status
wood-league-worker telemetry enable
wood-league-worker telemetry disable
wood-league-worker logs --tail 100        # fixed on Windows
wood-league-worker logs --follow          # Python-native polling
```

## Dependencies

Added to `services/local_worker/pyproject.toml`:

- `loguru>=0.7`
- `sentry-sdk>=2.0`

Version bump: `wood-league-worker` 0.2.x → **0.3.0** (new feature + new
runtime deps; release tag `worker-v0.3.0`).

## Testing

### Unit

- `_detect_environment` — patch `platform.*`, `torch`, `shutil.which`, etc.
  for Linux / macOS / Windows fixtures; assert the dict shape and `unknown`
  fallbacks.
- `configure_logging` — verify file is truncated when `reset_file=True`,
  appended when `False`; verify level threshold is honoured.
- `logs` command — populate a temp `worker.log` with N lines, assert
  `tail=10` prints the last 10 lines on all platforms (no subprocess).
- `prompt_for_consent` — feed simulated stdin; assert config file is
  written and re-runs read from it without re-prompting.
- `init_telemetry` — patch `sentry_sdk.init` and assert it is called with
  expected DSN/tags when `consent=True` and skipped when `consent=False`.

### Manual

- Run `wood-league-worker logs` on a Windows VM with no `tail.exe` on PATH;
  confirm tail output appears (the original WinError 2 is gone).
- Trigger a deliberate `logger.error("test")` from `run` and confirm the
  event arrives in GlitchTip with the expected tags.
- Delete the config file and re-run `run`; confirm the first-run prompt
  appears exactly once.

## Migration / Rollout

- Bump `services/local_worker/pyproject.toml` `version` to `0.3.0`.
- Tag `worker-v0.3.0` after merge; PyPI publish happens via the existing
  release workflow.
- Update `services/local_worker/README.md` with the `--log-level`,
  `telemetry`, and updated `logs` usage notes.
- No Django-side changes.

## Risks

- **GlitchTip availability.** We must stand up a GlitchTip instance before
  the release tag; otherwise the baked-in DSN is dead. Plan: provision on
  Railway alongside other infra, document the DSN in the project's secrets
  store, then cut the release.
- **Loguru/stdlib bridge edge cases.** Some libraries emit at module-import
  time before `configure_logging` runs. Mitigation: install the
  `InterceptHandler` as the first action in `_startup`.
- **PII in logs.** Hardware info and engine paths are low-risk; the
  install-token hash is one-way. Engine paths may contain a username on
  Windows — acceptable in opt-in telemetry.

## Open Questions

None at design time. Confirm GlitchTip hosting plan during planning.
