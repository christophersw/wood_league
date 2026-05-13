"""
Title: cli.py — Typer CLI entry point for wood-league-worker
Description:
    Defines the `wood-league-worker` CLI with four commands:
    - setup: interactive first-time configuration
    - run: interactive session to configure and start the worker loop
    - analyze: analyse a specific game by game_id
    - status: show queue counts from the API

Changelog:
    2026-05-09: Initial creation
    2026-05-10: Added BT4 network and Syzygy download helpers in setup; fix Syzygy URL (3-4-5-wdl subdir)
    2026-05-12: Rewrote ``logs`` as a Python-native tail (closes #43);
        wired loguru-based logging, --log-level, telemetry flags and
        ``telemetry`` sub-app.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

import httpx
import platformdirs
import questionary
import typer
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn
from rich.table import Table

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from local_worker.config import Settings, load_settings, normalize_api_url, save_settings
from local_worker.detector import (
    detect_hardware,
    detect_lc0_backend,
    find_lc0,
    find_stockfish,
    suggest_stockfish_settings,
)
from local_worker.display import worker_display
from local_worker.game_meta import parse_game_meta
from local_worker.logging_setup import (
    _detect_environment,
    configure_logging,
    log_session_banner,
)
from local_worker.loop import WorkerStats, run_batch
from local_worker.telemetry import (
    default_config_path as _telemetry_config_path,
    get_consent,
    init_telemetry,
    prompt_for_consent,
    set_consent,
)

# Subcommand names that produce long-running worker sessions. These are the
# only commands that (a) truncate ``worker.log`` and emit a fresh session
# banner, and (b) initialise telemetry when consent is on.
LONG_RUNNING_COMMANDS: set[str] = {"run"}

app = typer.Typer(
    name="wood-league-worker",
    help="Local analysis worker for the Wood League chess platform.",
    no_args_is_help=True,
)
console = Console()

telemetry_app = typer.Typer(
    name="telemetry",
    help="Manage opt-in remote diagnostics (GlitchTip).",
    no_args_is_help=True,
)
app.add_typer(telemetry_app, name="telemetry")


def _effective_telemetry(override: Optional[bool], config_path: Path) -> bool:
    """Resolve effective telemetry state given the CLI override and config.

    Args:
        override: ``True`` from ``--telemetry``, ``False`` from
            ``--no-telemetry``, or ``None`` if neither flag was passed.
        config_path: Path to the worker config file.

    Returns:
        Effective consent value to feed into :func:`init_telemetry`.
    """
    if override is not None:
        return override
    persisted = get_consent(config_path)
    if persisted is None:
        # Only prompt during long-running commands; everywhere else
        # default to off so read-only invocations stay silent.
        return prompt_for_consent(config_path)
    return persisted


def _current_release() -> str:
    """Return the installed package version, or ``"source"`` when editable.

    Returns:
        Release tag string used by Sentry/GlitchTip ``release`` filtering.
    """
    try:
        return _pkg_version("wood-league-worker")
    except PackageNotFoundError:
        return "source"


@app.callback()
def _startup(
    ctx: typer.Context,
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        envvar="WOOD_LEAGUE_LOG_LEVEL",
        help="Logging threshold (TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL).",
    ),
    telemetry: Optional[bool] = typer.Option(
        None,
        "--telemetry/--no-telemetry",
        help="Override persisted telemetry consent for this invocation.",
    ),
    log_dir: str = typer.Option(
        "",
        envvar="WLW_LOG_DIR",
        help="Override log file directory (hidden, intended for tests).",
        hidden=True,
    ),
) -> None:
    """Configure logging and optional telemetry on every invocation."""
    # ``log_dir`` is honoured via the WLW_LOG_DIR env var read inside
    # logging_setup; reflect the CLI override back into the environment so
    # both code paths converge.
    if log_dir:
        import os

        os.environ["WLW_LOG_DIR"] = log_dir

    is_long_running = ctx.invoked_subcommand in LONG_RUNNING_COMMANDS
    log_file = configure_logging(level=log_level, reset_file=is_long_running)
    if is_long_running:
        log_session_banner(log_file)
        config_path = _telemetry_config_path()
        consent = _effective_telemetry(telemetry, config_path)
        init_telemetry(
            consent=consent,
            release=_current_release(),
            environment_info=_detect_environment(),
            worker_id=load_settings().worker_id,
        )


def _prompt_api_credentials(settings: Settings) -> tuple[str, str]:
    """
    Prompt for API URL and key.

    Args:
        settings: Current settings to use as defaults.

    Returns:
        Tuple of (api_url, api_key). Exits if cancelled.
    """
    api_url = questionary.text(
        "API URL (e.g. https://your-app.railway.app):",
        default=settings.api_url or "",
    ).ask()
    if not api_url:
        console.print("[red]Setup cancelled.")
        raise typer.Exit(1)

    api_key = questionary.password("Worker API key:").ask()
    if not api_key:
        console.print("[red]Setup cancelled.")
        raise typer.Exit(1)

    return api_url, api_key


def _prompt_engine_paths(
    detected_sf: Optional[str],
    detected_lc0: Optional[str],
    settings: Settings,
) -> tuple[str, str]:
    """
    Prompt for engine paths.

    Args:
        detected_sf: Auto-detected Stockfish path or None.
        detected_lc0: Auto-detected Lc0 path or None.
        settings: Current settings to use as defaults.

    Returns:
        Tuple of (sf_path, lc0_path).
    """
    if detected_sf:
        sf_path = questionary.text("Stockfish path:", default=detected_sf).ask() or detected_sf
    else:
        sf_path = questionary.text("Stockfish path (leave blank to skip):").ask() or ""

    if detected_lc0:
        lc0_path = questionary.text("Lc0 path:", default=detected_lc0).ask() or detected_lc0
    else:
        lc0_path = questionary.text("Lc0 path (leave blank to skip):").ask() or ""

    return sf_path, lc0_path


def _prompt_engine_settings(
    sf_settings: dict, settings: Settings
) -> tuple[int, int, int, int]:
    """
    Prompt for engine tuning parameters.

    Args:
        sf_settings: Suggested Stockfish settings from hardware detection.
        settings: Current settings to use as defaults.

    Returns:
        Tuple of (threads, hash_mb, sf_depth, lc0_nodes).
    """
    threads = int(
        questionary.text("Stockfish threads:", default=str(sf_settings["threads"])).ask()
        or sf_settings["threads"]
    )
    hash_mb = int(
        questionary.text("Stockfish hash MB:", default=str(sf_settings["hash_mb"])).ask()
        or sf_settings["hash_mb"]
    )
    sf_depth = int(
        questionary.text("Stockfish depth:", default=str(settings.stockfish_depth)).ask()
        or settings.stockfish_depth
    )
    lc0_nodes = int(
        questionary.text("Lc0 nodes per move:", default=str(settings.lc0_nodes)).ask()
        or settings.lc0_nodes
    )
    return threads, hash_mb, sf_depth, lc0_nodes


_BT4_URL = (
    "https://storage.lczero.org/files/networks-contrib/"
    "BT4-1024x15x32h-swa-6147500-policytune-332.pb.gz"
)
_BT4_FILENAME = "BT4-1024x15x32h-swa-6147500-policytune-332.pb.gz"

_SYZYGY_BASE_URL = "https://tablebase.lichess.ovh/tables/standard/"
_SYZYGY_SUBDIRS = {"rtbw": "3-4-5-wdl", "rtbz": "3-4-5-dtz"}
_SYZYGY_345_POSITIONS = [
    "KBBvK", "KBNvK", "KBPvK", "KBvK", "KBvKB",
    "KBvKN", "KBvKP", "KNNvK", "KNPvK", "KNvK",
    "KNvKN", "KNvKP", "KPPvK", "KPvK", "KPvKP",
    "KQBvK", "KQNvK", "KQPvK", "KQQvK",
    "KQRvK", "KQvK", "KQvKB", "KQvKN", "KQvKP",
    "KQvKQ", "KQvKR", "KRBvK", "KRNvK", "KRPvK",
    "KRRvK", "KRvK", "KRvKB", "KRvKN", "KRvKP",
    "KRvKR",
]
_SYZYGY_345_FILES = [
    f"{position}.{ext}" for position in _SYZYGY_345_POSITIONS for ext in ("rtbw", "rtbz")
]


def _data_dir() -> Path:
    """Return the platform user-data directory for this worker.

    Returns:
        Path to the writable data directory; created if absent.
    """
    path = Path(platformdirs.user_data_dir("wood-league-worker", "WoodLeague"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_file(url: str, dest: Path, label: str) -> bool:
    """Stream-download url to dest, showing a Rich progress bar.

    Args:
        url: HTTP(S) URL to download.
        dest: Destination file path.
        label: Short label shown in the progress bar.

    Returns:
        True on success, False on any error.
    """
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0)) or None
            with Progress(
                TextColumn(label),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
            ) as progress:
                task = progress.add_task("", total=total)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        fh.write(chunk)
                        progress.advance(task, len(chunk))
        return True
    except Exception as exc:
        console.print(f"[red]Download failed: {exc}")
        if dest.exists():
            dest.unlink()
        return False


def _offer_download_bt4(current_path: str) -> str:
    """Offer to download the BT4 network if no weights are configured.

    Args:
        current_path: Currently configured lc0_weights_path (may be empty).

    Returns:
        Path string to the weights file (existing, newly downloaded, or empty).
    """
    if current_path and Path(current_path).exists():
        return current_path

    dest = _data_dir() / "networks" / _BT4_FILENAME
    if dest.exists():
        console.print(f"  BT4 network: [green]{dest}")
        return str(dest)

    console.print("\n[yellow]No Lc0 network weights found.")
    console.print("  BT4-it332 (~200 MB) will be downloaded from storage.lczero.org")
    if not questionary.confirm("Download BT4-it332 network now?", default=True).ask():
        return questionary.text("Enter path to existing weights file (or leave blank):").ask() or ""

    if _download_file(_BT4_URL, dest, "BT4-it332"):
        console.print(f"[green]Saved to {dest}")
        return str(dest)
    return ""


def _offer_download_syzygy(current_path: str) -> str:
    """Offer to download 3-4-5 piece Syzygy WDL+DTZ tablebases if none are configured.

    Args:
        current_path: Currently configured syzygy_path (may be empty).

    Returns:
        Path string to the Syzygy directory, or empty string.
    """
    if current_path and Path(current_path).exists():
        return current_path

    console.print("\n[yellow]No Syzygy tablebase path configured.")
    console.print("  3-4-5 piece WDL+DTZ files (~290 MB) will be downloaded from tablebase.lichess.ovh")
    if not questionary.confirm("Download 3-4-5 piece Syzygy tablebases now?", default=False).ask():
        return questionary.text("Enter path to existing Syzygy directory (or leave blank):").ask() or ""

    dest_dir = _data_dir() / "syzygy"
    dest_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for filename in _SYZYGY_345_FILES:
        ext = filename.rsplit(".", 1)[1]
        url = f"{_SYZYGY_BASE_URL}{_SYZYGY_SUBDIRS[ext]}/{filename}"
        dest = dest_dir / filename
        if dest.exists():
            continue
        if not _download_file(url, dest, filename):
            failed += 1

    if failed:
        console.print(f"[yellow]{failed} files failed — partial tablebase at {dest_dir}")
    else:
        console.print(f"[green]Syzygy tablebases saved to {dest_dir}")
    return str(dest_dir)


@app.command()
def setup() -> None:
    """Interactive first-time configuration wizard."""
    console.rule("[bold cyan]Wood League Worker — Setup")
    settings = load_settings()

    api_url, api_key = _prompt_api_credentials(settings)

    # Detect engines
    console.print("\n[bold]Detecting engines…")
    sf_path = find_stockfish()
    lc0_path = find_lc0()
    hw = detect_hardware()
    backend = detect_lc0_backend()
    sf_settings = suggest_stockfish_settings(hw)

    console.print(f"  Stockfish: [green]{sf_path or 'not found'}")
    console.print(f"  Lc0:       [green]{lc0_path or 'not found'}")
    console.print(f"  Lc0 backend detected: [cyan]{backend}")
    console.print(f"  CPU cores: {hw.cpu_count}  RAM: {hw.ram_mb} MB")
    console.print(
        f"  Suggested Stockfish threads: {sf_settings['threads']}  hash: {sf_settings['hash_mb']} MB"
    )

    sf_path, lc0_path = _prompt_engine_paths(sf_path, lc0_path, settings)

    lc0_weights_path = _offer_download_bt4(settings.lc0_weights_path)
    syzygy_path = _offer_download_syzygy(settings.syzygy_path)

    threads, hash_mb, sf_depth, lc0_nodes = _prompt_engine_settings(sf_settings, settings)

    new_settings = Settings(
        api_url=normalize_api_url(api_url.rstrip("/")),
        api_key=api_key,
        stockfish_path=sf_path,
        lc0_path=lc0_path,
        lc0_weights_path=lc0_weights_path,
        lc0_backend=backend,
        syzygy_path=syzygy_path,
        stockfish_threads=threads,
        stockfish_hash_mb=hash_mb,
        stockfish_depth=sf_depth,
        lc0_nodes=lc0_nodes,
    )
    save_settings(new_settings)
    console.print("\n[bold green]Settings saved! Run `wood-league-worker run` to start.")


def _resolve_run_options(
    engine: Optional[str],
    batch_size: Optional[int],
    batch_time: Optional[int],
) -> tuple[list[str], int, Optional[int]]:
    """
    Resolve run command options, prompting interactively if needed.

    Args:
        engine: Engine choice from CLI or None to prompt.
        batch_size: Batch size from CLI or None to prompt.
        batch_time: Batch time minutes from CLI or None to prompt.

    Returns:
        Tuple of (engines list, batch_size, batch_time_minutes).
    """
    if engine is None:
        engine_choice = questionary.select(
            "Which engines should this worker process?",
            choices=["stockfish", "lc0", "both"],
        ).ask()
        engine = engine_choice

    if batch_size is None:
        batch_size = int(
            questionary.text(
                "Batch size (jobs per checkout, 1–10):", default="5"
            ).ask()
            or 5
        )

    if batch_time is None:
        bt_raw = questionary.text(
            "Run for how many minutes? (leave blank to run until queue empty):"
        ).ask()
        batch_time = int(bt_raw) if bt_raw and bt_raw.strip().isdigit() else None

    engines = ["stockfish", "lc0"] if engine == "both" else [engine]
    return engines, batch_size, batch_time


@app.command()
def run(
    engine: Optional[str] = typer.Option(
        None, help="Force engine: stockfish, lc0, or both"
    ),
    batch_size: Optional[int] = typer.Option(None, help="Jobs per checkout (1–10)"),
    batch_time: Optional[int] = typer.Option(
        None, help="Run for this many minutes then stop"
    ),
) -> None:
    """Start the analysis worker loop (interactive if options omitted)."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    engines, batch_size, batch_time = _resolve_run_options(engine, batch_size, batch_time)

    # Validate engine paths
    if "stockfish" in engines and not settings.stockfish_path:
        console.print("[red]Stockfish path not configured. Run setup.")
        raise typer.Exit(1)
    if "lc0" in engines and not settings.lc0_path:
        console.print("[red]Lc0 path not configured. Run setup.")
        raise typer.Exit(1)

    console.rule(f"[bold cyan]Starting worker — engines: {', '.join(engines)}")
    stop_event = threading.Event()

    stats = WorkerStats()
    result_stats: Optional[WorkerStats] = None

    try:
        with worker_display(stats) as display:

            def on_job_start(job):
                total_moves = len(job.pgn.split("\n")) * 2  # rough estimate
                meta = parse_game_meta(job.pgn)
                display.set_job(
                    job.game_id,
                    job.engine,
                    total_moves,
                    matchup=meta.matchup,
                    date=meta.date,
                    event=meta.event,
                )

            def on_progress(ply, total, san="", fen=""):
                display.advance_move(ply, total, san=san, fen=fen)

            def on_job_done(job, success, elapsed):
                # Mirror run_batch's internal accounting onto the display-bound
                # stats so the live UI reflects progress as it happens.
                if success:
                    stats.record_game(job.engine, elapsed)
                else:
                    stats.errors += 1
                display.job_done()

            def on_jobs_claimed(jobs):
                display.add_batch_total(len(jobs))

            result_stats = run_batch(
                settings=settings,
                engines=engines,
                batch_size=batch_size,
                batch_time_minutes=batch_time,
                on_job_start=on_job_start,
                on_job_done=on_job_done,
                on_progress=on_progress,
                on_jobs_claimed=on_jobs_claimed,
                stop_event=stop_event,
            )
    except KeyboardInterrupt:
        stop_event.set()

    final = result_stats or stats
    console.rule("[bold green]Session complete")
    console.print(f"Games processed: [cyan]{final.games_processed}")
    console.print(f"Stockfish: {final.stockfish_count}  Lc0: {final.lc0_count}")
    console.print(f"Avg time/game: {final.avg_seconds_per_game():.1f}s")
    console.print(f"Errors: {final.errors}")


@app.command()
def analyze(
    game_id: str = typer.Argument(help="Game ID to analyse"),
    engine: str = typer.Option("stockfish", help="Engine to use: stockfish or lc0"),
) -> None:
    """Analyse a specific game by game_id."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    console.print(f"Requesting game [cyan]{game_id}[/] with [bold]{engine}…")
    stats = WorkerStats()

    with worker_display(stats) as display:

        def on_progress(ply, total, san="", fen=""):
            display.advance_move(ply, total, san=san, fen=fen)

        def on_jobs_claimed(jobs):
            display.add_batch_total(len(jobs))

        result = run_batch(
            settings=settings,
            engines=[engine],
            batch_size=1,
            game_id=game_id,
            on_progress=on_progress,
            on_jobs_claimed=on_jobs_claimed,
        )

    if result.games_processed == 0:
        console.print(
            "[yellow]No job claimed — game may already be analysed, queued for another engine, or not found."
        )
    else:
        console.print(f"[green]Done! Analysed in {result.total_seconds:.1f}s")


def _resolve_log_path() -> Path:
    """Return the path to ``worker.log`` honouring ``WLW_LOG_DIR``.

    Returns:
        Absolute path; existence is not guaranteed.
    """
    import os

    override = os.environ.get("WLW_LOG_DIR", "").strip()
    base = Path(override) if override else Path(
        platformdirs.user_log_dir("wood-league-worker", "WoodLeague")
    )
    return base / "worker.log"


def _tail_lines(log_path: Path, count: int) -> list[str]:
    """Return the last ``count`` lines of ``log_path`` without a subprocess.

    Uses :class:`collections.deque` so memory usage is bounded by
    ``count`` regardless of file size. Works on Windows, macOS, and Linux
    because no external ``tail`` binary is required.

    Args:
        log_path: Path to the log file. Caller must ensure it exists.
        count: Number of trailing lines to retain.

    Returns:
        List of up to ``count`` lines, in original order, each retaining
        any trailing newline so callers can write them verbatim.
    """
    if count <= 0:
        return []
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, maxlen=count))


def _follow_log(log_path: Path, initial_tail: int) -> None:
    """Print the last ``initial_tail`` lines, then stream new ones forever.

    A polling loop with ``time.sleep(0.5)`` and ``seek`` replaces ``tail
    -f`` so this works on Windows. Stops cleanly on ``KeyboardInterrupt``.

    Args:
        log_path: Path to the log file. Re-opened each poll cycle so the
            primary ``worker.log`` is picked up after a ``run`` truncates
            and recreates it.
        initial_tail: Number of lines to print up front (the same number
            ``tail -n N -f`` would print before streaming).
    """
    import sys

    for line in _tail_lines(log_path, initial_tail):
        sys.stdout.write(line)
    sys.stdout.flush()

    # Track current file identity and position so we can detect truncation
    # or replacement (e.g. when ``run`` resets the file mid-follow).
    try:
        handle = log_path.open("r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        handle = None
    if handle is not None:
        handle.seek(0, 2)  # jump to EOF

    try:
        while True:
            if handle is None:
                if log_path.exists():
                    handle = log_path.open("r", encoding="utf-8", errors="replace")
                else:
                    time.sleep(0.5)
                    continue

            chunk = handle.read()
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()
                continue

            # No new bytes — check for truncation/rotation.
            try:
                size = log_path.stat().st_size
            except FileNotFoundError:
                handle.close()
                handle = None
                time.sleep(0.5)
                continue
            if size < handle.tell():
                # File was truncated; re-open from the beginning.
                handle.close()
                handle = log_path.open("r", encoding="utf-8", errors="replace")
                continue

            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if handle is not None:
            handle.close()


@app.command()
def logs(
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Stream new log lines as they're written."
    ),
    tail: int = typer.Option(
        50, "--tail", "-n", help="How many recent lines to print before following."
    ),
) -> None:
    """Show worker log output.

    With no flags, prints the log file path and the last ``--tail`` lines.
    With ``--follow``, streams new lines as the worker writes them (useful
    in a second terminal while ``run`` is going). Implemented in pure
    Python — no dependency on a Unix ``tail`` binary, so it works on
    Windows too.
    """
    import sys

    log_path = _resolve_log_path()
    console.print(f"[cyan]Log file:[/] {log_path}")
    if not log_path.exists():
        console.print("[yellow]Log file does not exist yet — run the worker first.")
        return

    if follow:
        _follow_log(log_path, tail)
        return

    try:
        for line in _tail_lines(log_path, tail):
            sys.stdout.write(line)
        sys.stdout.flush()
    except OSError as exc:
        console.print(f"[red]Could not read log: {exc}")


@telemetry_app.command("status")
def telemetry_status() -> None:
    """Show the current telemetry consent state."""
    config_path = _telemetry_config_path()
    consent = get_consent(config_path)
    if consent is None:
        console.print("[yellow]Telemetry: not configured (will prompt on next `run`).")
    elif consent:
        console.print("[green]Telemetry: enabled.")
    else:
        console.print("[red]Telemetry: disabled.")
    console.print(f"[dim]Config file: {config_path}")


@telemetry_app.command("enable")
def telemetry_enable() -> None:
    """Opt in to sending anonymous diagnostics to GlitchTip."""
    config_path = _telemetry_config_path()
    set_consent(config_path, True)
    console.print("[green]Telemetry enabled.")


@telemetry_app.command("disable")
def telemetry_disable() -> None:
    """Opt out of sending diagnostics to GlitchTip."""
    config_path = _telemetry_config_path()
    set_consent(config_path, False)
    console.print("[yellow]Telemetry disabled.")


@app.command()
def version() -> None:
    """Print the installed wood-league-worker version."""
    try:
        console.print(_pkg_version("wood-league-worker"))
    except PackageNotFoundError:
        console.print("[yellow]wood-league-worker is not installed as a distribution (running from source).")


@app.command()
def status() -> None:
    """Show queue counts from the API."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    try:
        resp = httpx.get(
            f"{settings.api_url}/api/v1/jobs/status/",
            headers={"X-Api-Key": settings.api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        console.print(f"[red]Failed to fetch status: {exc}")
        raise typer.Exit(1)

    table = Table(title="Queue Status")
    table.add_column("Engine", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Count", justify="right", style="bold")

    for row in data.get("queue", []):
        table.add_row(row["engine"], row["status"], str(row["count"]))

    console.print(table)
