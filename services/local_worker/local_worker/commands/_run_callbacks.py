"""
Title: _run_callbacks.py — Live-display callback factory for ``run``
Description:
    Houses the closures that bridge :func:`local_worker.loop.run_batch`
    events to the Rich live-display panel.  Lives in its own module so
    that ``commands/run.py`` stays under the Halstead-effort gate.

Changelog:
    2026-05-12: Extracted from commands/run.py (issue #43 follow-up).
"""
from __future__ import annotations

from local_worker.game_meta import parse_game_meta
from local_worker.loop import WorkerStats


def make_display_callbacks(display, stats: WorkerStats) -> dict:
    """Build the per-event callbacks that bind ``run_batch`` to the UI.

    Args:
        display: Live ``worker_display`` context.
        stats: Stats object updated as jobs complete so the live UI
            reflects progress as it happens.

    Returns:
        Dict suitable for ``**``-unpacking into :func:`run_batch`.
    """
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

    def on_progress(ply, total, san="", fen="", **extras):
        display.advance_move(ply, total, san=san, fen=fen, **extras)

    def on_job_done(job, success, elapsed):
        if success:
            stats.record_game(job.engine, elapsed)
        else:
            stats.errors += 1
        display.job_done()

    def on_jobs_claimed(jobs):
        display.add_batch_total(len(jobs))

    return {
        "on_job_start": on_job_start,
        "on_progress": on_progress,
        "on_job_done": on_job_done,
        "on_jobs_claimed": on_jobs_claimed,
    }


__all__ = ["make_display_callbacks"]
