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
"""
from __future__ import annotations

import threading
from typing import Optional

import questionary
import typer
from rich.console import Console
from rich.table import Table

from local_worker.config import Settings, load_settings, save_settings
from local_worker.detector import (
    detect_hardware,
    detect_lc0_backend,
    find_lc0,
    find_stockfish,
    suggest_stockfish_settings,
)
from local_worker.display import worker_display
from local_worker.loop import WorkerStats, run_batch

app = typer.Typer(
    name="wood-league-worker",
    help="Local analysis worker for the Wood League chess platform.",
    no_args_is_help=True,
)
console = Console()


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

    syzygy_path = (
        questionary.text(
            "Syzygy tablebase path (leave blank to skip):",
            default=settings.syzygy_path or "",
        ).ask()
        or ""
    )

    threads, hash_mb, sf_depth, lc0_nodes = _prompt_engine_settings(sf_settings, settings)

    new_settings = Settings(
        api_url=api_url.rstrip("/"),
        api_key=api_key,
        stockfish_path=sf_path,
        lc0_path=lc0_path,
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

    try:
        with worker_display(stats) as display:

            def on_job_start(job):
                total_moves = len(job.pgn.split("\n")) * 2  # rough estimate
                display.set_job(job.game_id, job.engine, total_moves)

            def on_progress(ply, total):
                display.advance_move(ply, total)

            def on_job_done(job, success, elapsed):
                display.job_done()

            run_batch(
                settings=settings,
                engines=engines,
                batch_size=batch_size,
                batch_time_minutes=batch_time,
                on_job_start=on_job_start,
                on_job_done=on_job_done,
                on_progress=on_progress,
                stop_event=stop_event,
            )
    except KeyboardInterrupt:
        stop_event.set()

    console.rule("[bold green]Session complete")
    console.print(f"Games processed: [cyan]{stats.games_processed}")
    console.print(f"Stockfish: {stats.stockfish_count}  Lc0: {stats.lc0_count}")
    console.print(f"Avg time/game: {stats.avg_seconds_per_game():.1f}s")
    console.print(f"Errors: {stats.errors}")


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

        def on_progress(ply, total):
            display.advance_move(ply, total)

        result = run_batch(
            settings=settings,
            engines=[engine],
            batch_size=1,
            game_id=game_id,
            on_progress=on_progress,
        )

    if result.games_processed == 0:
        console.print(
            "[yellow]No job claimed — game may already be analysed, queued for another engine, or not found."
        )
    else:
        console.print(f"[green]Done! Analysed in {result.total_seconds:.1f}s")


@app.command()
def status() -> None:
    """Show queue counts from the API."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    import httpx

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
