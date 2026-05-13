"""
Title: analyze.py — ``wood-league-worker analyze`` single-game command
Description:
    Analyses a single game by ``game_id`` using whichever engine the user
    requests, sharing the live Rich display with the worker loop.

Changelog:
    2026-05-12: Extracted from cli.py / commands/run.py (issue #43
        follow-up).
"""
from __future__ import annotations

import typer

from local_worker._shared import console
from local_worker.config import load_settings
from local_worker.display import worker_display
from local_worker.loop import WorkerStats, run_batch


def analyze(
    game_id: str = typer.Argument(help="Game ID to analyse"),
    engine: str = typer.Option("stockfish", help="Engine to use: stockfish or lc0"),
) -> None:
    """Analyse a specific game by ``game_id``."""
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
