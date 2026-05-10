"""
Title: display.py — Rich terminal display for the worker
Description:
    Provides a WorkerDisplay context manager that renders a Live layout
    with a per-move progress bar, a batch progress bar, and a stats panel.
    Uses Rich's Progress and Layout APIs.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from local_worker.loop import WorkerStats

console = Console()


def _make_stats_panel(stats: WorkerStats, engine: str, job_desc: str) -> Panel:
    """Build a Rich Panel showing current session statistics.

    Args:
        stats: Current WorkerStats.
        engine: Currently active engine name.
        job_desc: Short description of the current job.

    Returns:
        A Rich Panel renderable.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", justify="right")
    table.add_column(style="white")

    table.add_row("Games processed", str(stats.games_processed))
    table.add_row("Stockfish", str(stats.stockfish_count))
    table.add_row("Lc0", str(stats.lc0_count))
    table.add_row("Avg time/game", f"{stats.avg_seconds_per_game():.1f}s")
    table.add_row("Errors", str(stats.errors))
    table.add_row("Active engine", engine)
    table.add_row("Current job", job_desc)

    return Panel(table, title="[bold green]Session Stats", border_style="green")


@contextmanager
def worker_display(stats: WorkerStats) -> Generator["DisplayHandle", None, None]:
    """Context manager that renders a live worker display.

    Usage:
        with worker_display(stats) as display:
            display.set_job("game-abc", "stockfish", total_moves=80)
            display.advance_move()

    Args:
        stats: WorkerStats shared reference (mutated externally by loop).

    Yields:
        A DisplayHandle for updating the display.
    """
    batch_progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )
    move_progress = Progress(
        TextColumn("[cyan]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
    )

    batch_task = batch_progress.add_task("[bold]Batch progress", total=None)
    move_task = move_progress.add_task("Analysing moves", total=100, visible=False)

    handle = DisplayHandle(
        stats=stats,
        batch_progress=batch_progress,
        move_progress=move_progress,
        batch_task=batch_task,
        move_task=move_task,
    )

    with Live(console=console, refresh_per_second=4) as live:
        handle._live = live
        live.update(handle._render())
        yield handle


class DisplayHandle:
    """Mutable handle for updating the live display from the worker loop."""

    def __init__(
        self,
        stats: WorkerStats,
        batch_progress: Progress,
        move_progress: Progress,
        batch_task,
        move_task,
    ) -> None:
        self.stats = stats
        self._batch_progress = batch_progress
        self._move_progress = move_progress
        self._batch_task = batch_task
        self._move_task = move_task
        self._live: Optional[Live] = None
        self._current_engine = ""
        self._current_job = "idle"

    def set_job(self, game_id: str, engine: str, total_moves: int) -> None:
        """Signal that a new job has started.

        Args:
            game_id: Game identifier string.
            engine: Engine being used ('stockfish' or 'lc0').
            total_moves: Total plies in the game.
        """
        self._current_engine = engine
        self._current_job = game_id
        self._move_progress.update(
            self._move_task,
            description=f"[{engine}] {game_id}",
            total=total_moves,
            completed=0,
            visible=True,
        )
        self._batch_progress.advance(self._batch_task, 0)
        self._refresh()

    def advance_move(self, ply: int, total: int) -> None:
        """Update the per-move progress bar.

        Args:
            ply: Current ply number (1-based).
            total: Total plies in the game.
        """
        self._move_progress.update(self._move_task, completed=ply, total=total)
        self._refresh()

    def job_done(self) -> None:
        """Signal that the current job has finished."""
        self._move_progress.update(self._move_task, visible=False)
        self._batch_progress.advance(self._batch_task, 1)
        self._refresh()

    def _render(self):
        stats_panel = _make_stats_panel(self.stats, self._current_engine, self._current_job)
        columns = Columns([self._batch_progress, self._move_progress], equal=False, expand=True)
        layout = Table.grid()
        layout.add_row(stats_panel)
        layout.add_row(Panel(columns, title="Progress", border_style="blue"))
        return layout

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())
