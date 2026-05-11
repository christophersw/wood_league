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

import chess
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
from rich.text import Text

from local_worker.loop import WorkerStats

_INITIAL_FEN = chess.STARTING_FEN

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
    handle._batch_total = 0

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
        self._current_san = ""
        self._current_ply = 0
        self._current_total_plies = 0
        self._current_fen = _INITIAL_FEN
        self._batch_total = 0

    def set_job(self, game_id: str, engine: str, total_moves: int) -> None:
        """Signal that a new job has started.

        Args:
            game_id: Game identifier string.
            engine: Engine being used ('stockfish' or 'lc0').
            total_moves: Total plies in the game (rough estimate; refined by
                advance_move once the engine reports the real ply count).
        """
        self._current_engine = engine
        self._current_job = game_id
        self._current_san = ""
        self._current_ply = 0
        self._current_total_plies = total_moves
        self._current_fen = _INITIAL_FEN
        self._move_progress.update(
            self._move_task,
            description=f"[{engine}] {game_id} — waiting for first move…",
            total=total_moves,
            completed=0,
            visible=True,
        )
        self._batch_progress.advance(self._batch_task, 0)
        self._refresh()

    def advance_move(
        self,
        ply: int,
        total: int,
        san: str = "",
        fen: str = "",
    ) -> None:
        """Update the per-move progress bar and current position.

        Args:
            ply: Current ply number (1-based).
            total: Total plies in the game.
            san: SAN of the move just analysed (e.g. "Nxe5"). Optional.
            fen: FEN of the resulting position, for the ASCII board panel.
                Optional; defaults to the previously-shown position.
        """
        self._current_ply = ply
        self._current_total_plies = total
        if san:
            self._current_san = san
        if fen:
            self._current_fen = fen
        move_no = (ply + 1) // 2
        side = "." if ply % 2 == 1 else "..."
        label = f"[{self._current_engine}] move {move_no}{side} {self._current_san}".strip()
        self._move_progress.update(
            self._move_task,
            description=f"{label}  ({ply}/{total} plies)",
            completed=ply,
            total=total,
        )
        self._refresh()

    def set_batch_total(self, total: int) -> None:
        """Set the absolute total for the batch progress bar.

        Args:
            total: New absolute job count for this run.
        """
        self._batch_total = total
        self._batch_progress.update(self._batch_task, total=total)
        self._refresh()

    def add_batch_total(self, delta: int) -> None:
        """Increase the batch total by ``delta`` (used as more jobs are claimed).

        Args:
            delta: Number of additional jobs claimed in the latest checkout.
        """
        if delta <= 0:
            return
        self._batch_total += delta
        self._batch_progress.update(self._batch_task, total=self._batch_total)
        self._refresh()

    def job_done(self) -> None:
        """Signal that the current job has finished."""
        self._move_progress.update(self._move_task, visible=False)
        self._batch_progress.advance(self._batch_task, 1)
        self._refresh()

    def _board_panel(self) -> Panel:
        """Render the current board as an ASCII panel.

        Returns:
            Rich Panel containing the board (white pieces uppercase, black
            lowercase, dots for empty squares — works in any terminal).
        """
        try:
            board = chess.Board(self._current_fen)
        except ValueError:
            board = chess.Board()
        body = Text(str(board), style="white")
        title = "Board" if not self._current_san else f"After {self._current_san}"
        return Panel(body, title=title, border_style="magenta", expand=False)

    def _render(self):
        stats_panel = _make_stats_panel(self.stats, self._current_engine, self._current_job)
        progress_panel = Panel(
            Columns([self._batch_progress, self._move_progress], equal=False, expand=True),
            title="Progress",
            border_style="blue",
        )
        top = Columns([stats_panel, self._board_panel()], equal=False, expand=True)
        layout = Table.grid()
        layout.add_row(top)
        layout.add_row(progress_panel)
        return layout

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())
