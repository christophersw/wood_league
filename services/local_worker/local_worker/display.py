"""
Title: display.py — Rich terminal display for the worker
Description:
    Provides a WorkerDisplay context manager that renders a Live layout
    with a per-move progress bar, a batch progress bar, and a stats panel.
    Uses Rich's Progress and Layout APIs.

Changelog:
    2026-05-09: Initial creation
    2026-05-13: Added per-ply depth/nodes/seconds to the move-progress label
        and a debug-log "last line" panel (visible only when debug logging
        is enabled). Closes #44.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

import chess
from loguru import logger
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


def _format_nodes(nodes: Optional[int]) -> str:
    """Compactly format a node count (e.g. 1_234_567 → "1.2M").

    Args:
        nodes: Total nodes searched, or None when the engine did not report.

    Returns:
        Short human-readable string, or "" when nodes is None.
    """
    if nodes is None:
        return ""
    if nodes >= 1_000_000:
        return f"{nodes / 1_000_000:.1f}M"
    if nodes >= 1_000:
        return f"{nodes / 1_000:.1f}k"
    return str(nodes)

_INITIAL_FEN = chess.STARTING_FEN

console = Console()


def _make_stats_panel(
    stats: WorkerStats,
    engine: str,
    job_desc: str,
    *,
    matchup: str = "",
    date: str = "",
    event: str = "",
) -> Panel:
    """Build a Rich Panel showing current session statistics.

    Matchup/date/event rows are suppressed when empty so games without those
    PGN tags don't leave dangling labels.
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
    if matchup:
        table.add_row("Matchup", matchup)
    if date:
        table.add_row("Date", date)
    if event:
        table.add_row("Event", event)

    return Panel(table, title="[bold green]Session Stats", border_style="green")


@contextmanager
def worker_display(
    stats: WorkerStats,
    *,
    debug: bool = False,
) -> Generator["DisplayHandle", None, None]:
    """Context manager that renders a live worker display.

    Usage:
        with worker_display(stats, debug=True) as display:
            display.set_job("game-abc", "stockfish", total_moves=80)
            display.advance_move()

    Args:
        stats: WorkerStats shared reference (mutated externally by loop).
        debug: When True, render an extra "Last debug log line" panel and
            attach a loguru sink that feeds it. Useful for spotting when the
            worker has silently hung — if the line stops updating, so has work.

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
        debug_enabled=debug,
    )
    handle._batch_total = 0

    sink_id: Optional[int] = None
    if debug:
        def _debug_sink(message) -> None:
            """Loguru sink that feeds the live "last debug line" panel."""
            record = message.record
            handle.set_debug_line(
                f"{record['level'].name} {record['name']}:"
                f"{record['line']} — {record['message']}"
            )
        sink_id = logger.add(_debug_sink, level="DEBUG", format="{message}")

    try:
        with Live(console=console, refresh_per_second=4) as live:
            handle._live = live
            live.update(handle._render())
            yield handle
    finally:
        if sink_id is not None:
            try:
                logger.remove(sink_id)
            except ValueError:
                pass


class DisplayHandle:
    """Mutable handle for updating the live display from the worker loop."""

    def __init__(
        self,
        stats: WorkerStats,
        batch_progress: Progress,
        move_progress: Progress,
        batch_task,
        move_task,
        debug_enabled: bool = False,
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
        self._current_matchup = ""
        self._current_date = ""
        self._current_event = ""
        self._current_depth: Optional[int] = None
        self._current_nodes: Optional[int] = None
        self._current_seconds: Optional[float] = None
        self._debug_enabled = debug_enabled
        self._last_debug_line = ""

    def set_debug_line(self, line: str) -> None:
        """Update the "Last debug log line" panel content.

        Args:
            line: Pre-formatted single-line log record.
        """
        self._last_debug_line = line
        self._refresh()

    def set_job(
        self,
        game_id: str,
        engine: str,
        total_moves: int,
        *,
        matchup: str = "",
        date: str = "",
        event: str = "",
    ) -> None:
        """Signal that a new job has started.

        Args:
            game_id: Game identifier string.
            engine: Engine being used ('stockfish' or 'lc0').
            total_moves: Total plies in the game (rough estimate; refined by
                advance_move once the engine reports the real ply count).
            matchup: Optional "White vs. Black" string parsed from the PGN.
            date: Optional game date (YYYY-MM-DD) parsed from the PGN.
            event: Optional event/tournament name parsed from the PGN.
        """
        self._current_engine = engine
        self._current_job = game_id
        self._current_san = ""
        self._current_ply = 0
        self._current_total_plies = total_moves
        self._current_fen = _INITIAL_FEN
        self._current_matchup = matchup
        self._current_date = date
        self._current_event = event
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
        *,
        depth: Optional[int] = None,
        nodes: Optional[int] = None,
        seconds: Optional[float] = None,
    ) -> None:
        """Update the per-move progress bar and current position.

        Args:
            ply: Current ply number (1-based).
            total: Total plies in the game.
            san: SAN of the move just analysed (e.g. "Nxe5"). Optional.
            fen: FEN of the resulting position, for the ASCII board panel.
                Optional; defaults to the previously-shown position.
            depth: Engine search depth for this ply, when reported.
            nodes: Total nodes searched for this ply, when reported.
            seconds: Wall-clock time spent analysing this ply, when timed.
        """
        self._current_ply = ply
        self._current_total_plies = total
        if san:
            self._current_san = san
        if fen:
            self._current_fen = fen
        if depth is not None:
            self._current_depth = depth
        if nodes is not None:
            self._current_nodes = nodes
        if seconds is not None:
            self._current_seconds = seconds
        move_no = (ply + 1) // 2
        side = "." if ply % 2 == 1 else "..."
        label = f"[{self._current_engine}] move {move_no}{side} {self._current_san}".strip()
        extras = self._format_ply_extras()
        suffix = f"  ({ply}/{total} plies)" + (f"  {extras}" if extras else "")
        self._move_progress.update(
            self._move_task,
            description=f"{label}{suffix}",
            completed=ply,
            total=total,
        )
        self._refresh()

    def _format_ply_extras(self) -> str:
        """Return a compact "d=… n=… t=…" suffix from cached per-ply stats."""
        parts: list[str] = []
        if self._current_depth is not None:
            parts.append(f"d={self._current_depth}")
        nodes_str = _format_nodes(self._current_nodes)
        if nodes_str:
            parts.append(f"n={nodes_str}")
        if self._current_seconds is not None:
            parts.append(f"t={self._current_seconds:.2f}s/ply")
        return " ".join(parts)

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
        stats_panel = _make_stats_panel(
            self.stats,
            self._current_engine,
            self._current_job,
            matchup=self._current_matchup,
            date=self._current_date,
            event=self._current_event,
        )
        progress_panel = Panel(
            Columns([self._batch_progress, self._move_progress], equal=False, expand=True),
            title="Progress",
            border_style="blue",
        )
        top = Columns([stats_panel, self._board_panel()], equal=False, expand=True)
        layout = Table.grid()
        layout.add_row(top)
        layout.add_row(progress_panel)
        if self._debug_enabled:
            layout.add_row(self._debug_panel())
        return layout

    def _debug_panel(self) -> Panel:
        """Render a one-line panel showing the most recent debug log line.

        The line is shown verbatim so a frozen line is a clear "hung" signal.
        """
        text = Text(self._last_debug_line or "(waiting for first debug line…)", style="dim")
        text.no_wrap = True
        text.overflow = "ellipsis"
        return Panel(text, title="Last debug log line", border_style="yellow")

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())
