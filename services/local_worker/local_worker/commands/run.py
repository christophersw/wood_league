"""
Title: run.py — ``wood-league-worker run`` analysis loop command
Description:
    Drives the long-running analysis loop: prompts for engine selection,
    batch size, and time limit if those flags were omitted, then attaches
    the live Rich display callbacks (built in
    :mod:`local_worker.commands._run_callbacks`) to :func:`run_batch`.

Changelog:
    2026-05-12: Extracted from cli.py (issue #43 follow-up).
    2026-05-12: Callbacks split into ``_run_callbacks.py`` to satisfy
        the Halstead-effort gate.
    2026-05-14: Wire RunPod self-stop hook after queue drain (#81).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import questionary
import typer

from local_worker._shared import console
from local_worker.commands._run_callbacks import make_display_callbacks
from local_worker.config import Settings, load_settings
from local_worker.display import worker_display
from local_worker.logging_setup import is_debug_logging
from local_worker.loop import WorkerStats, run_batch
from local_worker.runpod_lifecycle import resolve_pod_id, stop_self

logger = logging.getLogger(__name__)


def _resolve_run_options(
    engine: Optional[str],
    batch_size: Optional[int],
    batch_time: Optional[int],
) -> tuple[list[str], int, Optional[int]]:
    """Resolve run command options, prompting interactively if needed.

    Args:
        engine: Engine choice from CLI or ``None`` to prompt.
        batch_size: Batch size from CLI or ``None`` to prompt.
        batch_time: Batch time in minutes from CLI or ``None`` to prompt.

    Returns:
        Tuple of (engines list, batch_size, batch_time_minutes).
    """
    if engine is None:
        engine = questionary.select(
            "Which engines should this worker process?",
            choices=["stockfish", "lc0", "both"],
        ).ask()

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


def _validate_engine_paths(engines: list[str], settings: Settings) -> None:
    """Ensure each requested engine has a configured binary path.

    Args:
        engines: List of engine names selected for this run.
        settings: Persisted worker settings to consult.

    Raises:
        typer.Exit: With code 1 if any requested engine is missing a path.
    """
    if "stockfish" in engines and not settings.stockfish_path:
        console.print("[red]Stockfish path not configured. Run setup.")
        raise typer.Exit(1)
    if "lc0" in engines and not settings.lc0_path:
        console.print("[red]Lc0 path not configured. Run setup.")
        raise typer.Exit(1)


def _print_session_summary(final: WorkerStats) -> None:
    """Print the post-session totals line group.

    Args:
        final: Stats object populated by :func:`run_batch`.
    """
    console.rule("[bold green]Session complete")
    console.print(f"Games processed: [cyan]{final.games_processed}")
    console.print(f"Stockfish: {final.stockfish_count}  Lc0: {final.lc0_count}")
    console.print(f"Avg time/game: {final.avg_seconds_per_game():.1f}s")
    console.print(f"Errors: {final.errors}")


def _maybe_stop_runpod(settings: Settings) -> None:
    """If self-stop is enabled and creds/pod-id resolved, ask RunPod to stop this pod.

    Args:
        settings: Loaded worker settings carrying the self-stop flag and creds.

    Returns:
        None. Logs at INFO on attempt and at WARNING when prerequisites are
        missing; never raises.
    """
    if not settings.runpod_self_stop_enabled:
        return
    if not settings.runpod_api_key:
        logger.warning("runpod self-stop enabled but WLW_RUNPOD_API_KEY is empty; skipping")
        return
    pod_id = resolve_pod_id(settings)
    if not pod_id:
        logger.warning("runpod self-stop enabled but no pod id resolvable; skipping")
        return
    stop_self(pod_id, settings.runpod_api_key)


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
    _validate_engine_paths(engines, settings)

    console.rule(f"[bold cyan]Starting worker — engines: {', '.join(engines)}")
    stop_event = threading.Event()
    stats = WorkerStats()
    result_stats: Optional[WorkerStats] = None

    try:
        try:
            with worker_display(stats, debug=is_debug_logging()) as display:
                callbacks = make_display_callbacks(display, stats)
                result_stats = run_batch(
                    settings=settings,
                    engines=engines,
                    batch_size=batch_size,
                    batch_time_minutes=batch_time,
                    stop_event=stop_event,
                    **callbacks,
                )
        except KeyboardInterrupt:
            stop_event.set()

        _print_session_summary(result_stats or stats)
    finally:
        _maybe_stop_runpod(settings)
