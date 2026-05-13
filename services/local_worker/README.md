# Wood League Local Analysis Worker

A CLI tool that pulls chess game analysis jobs from the Wood League API, runs them through Stockfish or Lc0 on your local machine, and submits the results back. Useful when you want to contribute compute using hardware not available on the server (e.g. a fast GPU for Lc0, or a high-core CPU for Stockfish).

## Prerequisites

- Python 3.11+
- [Stockfish](https://stockfishchess.org/download/) and/or [Lc0](https://lczero.org/play/download/) installed on your machine
- A Wood League API URL and worker API key

## Installation

From the repo root (uses [uv](https://docs.astral.sh/uv/) workspace):

```bash
# Just the worker (end users)
uv pip install -e "services/local_worker"

# Worker + test/lint tools (contributors)
uv pip install -e "services/local_worker[dev]"
```

Or from inside the `services/local_worker` directory:

```bash
pip install -e "."        # just the worker
pip install -e ".[dev]"   # worker + pytest, ruff, mypy
```

## Quick Start

**1. Run the setup wizard** (first time only):

```bash
wood-league-worker setup
```

This auto-detects Stockfish and Lc0 on your PATH, suggests thread/memory settings based on your hardware, and saves everything to a config file.

**2. Start processing jobs:**

```bash
wood-league-worker run
```

You'll be prompted to choose engines (stockfish, lc0, or both), batch size, and an optional time limit. Press `Ctrl+C` to stop.

## Commands

### `setup`

Interactive configuration wizard. Run this the first time, or any time you need to update settings.

```bash
wood-league-worker setup
```

Prompts for:
- API URL and worker API key
- Stockfish path (auto-detected if on PATH)
- Lc0 path (auto-detected if on PATH)
- Lc0 network weights — offers to download **BT4-it332** (~200 MB) from `storage.lczero.org` if not already present (this is the same network used by the RunPod worker)
- Syzygy tablebases — offers to download 3-4-5 piece WDL + DTZ files (~290 MB total) from `tablebase.lichess.ovh` if not configured
- Stockfish thread count, hash memory, and search depth
- Lc0 nodes per move

Settings are saved to a JSON file in your platform's user data directory (e.g. `~/.local/share/wood-league-worker/settings.json` on Linux, `~/Library/Application Support/WoodLeague/wood-league-worker/settings.json` on macOS).

---

### `run`

Start the analysis worker loop. Checks out jobs from the API queue, analyses them, and submits results. Runs until the queue is empty, the time limit is reached, or you press `Ctrl+C`.

```bash
wood-league-worker run [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--engine TEXT` | Force engine: `stockfish`, `lc0`, or `both`. Prompts if omitted. |
| `--batch-size INT` | Jobs to claim per checkout call (1–10). Prompts if omitted. |
| `--batch-time INT` | Stop after this many minutes. Runs until queue empty if omitted. |

**Examples:**

```bash
# Interactive — prompts for all options
wood-league-worker run

# Non-interactive — run Stockfish jobs in batches of 3 for 30 minutes
wood-league-worker run --engine stockfish --batch-size 3 --batch-time 30

# Process both engines until the queue is empty
wood-league-worker run --engine both --batch-size 5
```

The worker sends a heartbeat to the API every 30 seconds while running. A live display shows the current game, move progress, and per-session statistics.

---

### `analyze`

Analyse a single specific game by its game ID, bypassing the queue.

```bash
wood-league-worker analyze GAME_ID [OPTIONS]
```

| Argument/Option | Description |
|-----------------|-------------|
| `GAME_ID` | The game ID to analyse (required) |
| `--engine TEXT` | Engine to use: `stockfish` (default) or `lc0` |

**Example:**

```bash
wood-league-worker analyze abc123 --engine lc0
```

---

### `status`

Show current queue counts from the API — how many jobs are pending or in-progress per engine.

```bash
wood-league-worker status
```

## Settings Reference

Settings are stored as JSON. All fields can also be set by re-running `setup`. The file location is printed during setup.

| Setting | Default | Description |
|---------|---------|-------------|
| `api_url` | `""` | Wood League API base URL (e.g. `https://your-app.railway.app`) |
| `api_key` | `""` | Worker API key for authentication |
| `worker_id` | `""` | Optional identifier for this worker. Defaults to `local-<hostname>` |
| `stockfish_path` | `""` | Full path to the Stockfish binary |
| `lc0_path` | `""` | Full path to the Lc0 (`lc0`) binary |
| `lc0_weights_path` | `""` | Path to the Lc0 network weights file (`.pb.gz`). `setup` offers to download BT4-it332 automatically. |
| `syzygy_path` | `""` | Path to Syzygy endgame tablebases directory. `setup` offers to download 3-4-5 piece WDL + DTZ files automatically. |
| `lc0_backend` | `""` | Lc0 backend override (e.g. `cuda`, `opencl`, `cpu`). Auto-detected during setup. |
| `default_engines` | `["stockfish"]` | Engines to suggest when running interactively |
| `default_batch_size` | `5` | Default jobs per checkout |
| `batch_time_minutes` | `null` | Default time limit in minutes (`null` = unlimited) |
| `stockfish_depth` | `20` | Search depth for Stockfish per move |
| `stockfish_threads` | `4` | CPU threads for Stockfish (setup auto-suggests based on your CPU) |
| `stockfish_hash_mb` | `512` | Hash table size for Stockfish in MB (setup auto-suggests based on RAM) |
| `lc0_nodes` | `10000` | Nodes per move for Lc0 |

### `logs`

Show worker log output. Implemented in pure Python — works the same on Windows, macOS, and Linux without needing an external `tail` binary.

```bash
wood-league-worker logs [--tail N] [--follow]
```

| Option | Description |
|--------|-------------|
| `--tail N`, `-n N` | Print the last N lines (default 50). |
| `--follow`, `-f` | Print the tail and then poll for new lines until interrupted. |

The primary log file is overwritten at the start of every `run`, so it always reflects the most recent session. Read-only commands (`logs`, `status`, `version`, `telemetry *`) leave it untouched and instead write any warnings they raise to a separate `worker.diagnostics.log` in the same directory.

---

### `telemetry`

Manage opt-in remote diagnostics. The worker can optionally send anonymous error reports (with hardware info and engine versions) to a self-hosted **GlitchTip** instance to help debug crashes that are otherwise hard to reproduce. Telemetry is **off** by default; the first `run` will prompt you once, and the answer is persisted to `~/.config/wood-league-worker/config.json` (or the platform-equivalent) forever.

```bash
wood-league-worker telemetry status     # show current state
wood-league-worker telemetry enable     # opt in
wood-league-worker telemetry disable    # opt out
```

You can also override the persisted choice for a single invocation:

```bash
wood-league-worker --telemetry run       # force on for this run
wood-league-worker --no-telemetry run    # force off for this run
```

---

## Global Options

| Option | Env var | Description |
|--------|---------|-------------|
| `--log-level` | `WOOD_LEAGUE_LOG_LEVEL` | Logging threshold for the file sink. Accepts `TRACE`, `DEBUG`, `INFO` (default), `WARNING`, `ERROR`, `CRITICAL`. |
| `--telemetry` / `--no-telemetry` | — | Override persisted telemetry consent for one invocation. |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `WLW_LOG_DIR` | Override the directory where log files are written |
| `WOOD_LEAGUE_LOG_LEVEL` | Default logging threshold (same as `--log-level`). |
| `WOOD_LEAGUE_GLITCHTIP_DSN` | Override the baked-in GlitchTip DSN. Empty disables telemetry entirely. |

## Development

Run the test suite from inside `services/local_worker`:

```bash
pytest
```

Integration tests that require a real Stockfish or Lc0 binary are skipped automatically when the binary is not found on PATH.

Type checking:

```bash
mypy local_worker
```

Linting:

```bash
ruff check local_worker
```
