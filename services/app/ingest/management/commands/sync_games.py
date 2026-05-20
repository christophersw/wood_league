"""
Title: sync_games.py — Django management command for Chess.com game sync
Description:
    Acquires a Postgres advisory lock (cron-overlap protection), runs the
    existing Chess.com sync subprocess (run_sync.py), then auto-enqueues
    AnalysisJobs for newly-ingested games per SiteSettings toggles. After
    the subprocess completes, parses %clk annotations and bulk-creates
    GameMoveTime rows for all games with non-empty PGN and a known
    time_class (idempotent; deletes and rewrites on re-ingest).

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-10: Add advisory lock + auto-enqueue + SystemEvent (Task D1).
    2026-05-11: Post-sync GameMoveTime population (issue #24, Task 7).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from analysis.services.enqueue import enqueue_analysis_job
from core.models import SiteSettings
from games.clock_parser import parse_move_times
from games.models import Game, GameMoveTime
from games.opening_resolver import resolve_opening_id
from ingest.models import SystemEvent
from players.models import Player

# 32-bit module-level constant for the ingest advisory lock.
_INGEST_LOCK_ID = 0x7E571465

_SCRIPT = Path(__file__).resolve().parents[3] / "app" / "ingest" / "run_sync.py"


def _try_acquire_lock(lock_id: int = _INGEST_LOCK_ID) -> bool:
    """Acquire a session-scoped Postgres advisory lock. Returns True on success.

    Args:
        lock_id: The 32-bit integer identifier for the advisory lock.

    Returns:
        bool: True if the lock was acquired; False if already held.
    """
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
        return bool(cur.fetchone()[0])


def _release_lock(lock_id: int = _INGEST_LOCK_ID) -> None:
    """Release the session-scoped advisory lock.

    Args:
        lock_id: The 32-bit integer identifier for the advisory lock to release.

    Returns:
        None
    """
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", [lock_id])


def _stockfish_depth() -> int:
    """Return default depth for new auto-enqueued stockfish jobs.

    Returns:
        int: Stockfish search depth from ANALYSIS_DEPTH setting (default 20).
    """
    return int(getattr(settings, "ANALYSIS_DEPTH", 20))


def _lc0_nodes() -> int:
    """Return default node budget for new auto-enqueued lc0 jobs.

    Returns:
        int: Lc0 node budget from LC0_NODES setting (default 25000).
    """
    return int(getattr(settings, "LC0_NODES", 25000))


def _populate_move_times_for_recent_games(*, since, stdout) -> int:
    """Parse %clk annotations for any Game with non-empty PGN updated since `since`.

    Returns the number of GameMoveTime rows written. Idempotent: existing
    rows for each game are deleted and rewritten so re-ingest of a game
    leaves the table consistent.

    Args:
        since: Optional datetime. If provided, only games created on or after
            this timestamp are processed. Pass None to sweep all games.
        stdout: A file-like object for progress/error output (e.g. self.stdout).

    Returns:
        int: Total number of GameMoveTime rows written across all games.

    Side effects:
        Deletes and re-creates GameMoveTime rows for each processed game.
        Errors for individual games are written to `stdout` and skipped.
    """
    from django.db import transaction

    written = 0
    candidates = Game.objects.filter(
        pgn__gt="",
        time_class__isnull=False,
    )
    if since is not None:
        candidates = candidates.filter(created_at__gte=since)

    for game in candidates.iterator():
        try:
            move_times = parse_move_times(
                game.pgn,
                time_class=game.time_class,
                time_control_base_s=game.time_control_base_s,
                time_control_increment_s=game.time_control_increment_s,
            )
        except Exception as exc:  # noqa: BLE001 — clock parsing is best-effort
            stdout.write(f"move-time parse failed for {game.id}: {exc}\n")
            continue
        if not move_times:
            continue
        with transaction.atomic():
            GameMoveTime.objects.filter(game=game).delete()
            GameMoveTime.objects.bulk_create([
                GameMoveTime(
                    game=game,
                    ply=mt.ply,
                    time_spent_ms=mt.time_spent_ms,
                    clock_after_ms=mt.clock_after_ms,
                )
                for mt in move_times
            ])
            written += len(move_times)
    return written


def _populate_opening_ids_for_recent_games(*, since, stdout) -> int:
    """Resolve and persist ``Game.opening_id`` for games with non-empty PGN.

    Calls ``resolve_opening_id`` for each candidate game and bulk-updates the
    ``opening_id`` FK column in a single queryset ``update`` per game. Only
    rows whose ``opening_id`` is NULL are considered, so the sweep is cheap in
    steady state (#168). To re-resolve already-populated rows (e.g. after the
    resolver improves) use the ``backfill_opening_ids`` management command.

    Args:
        since: Optional datetime. If provided, only games created on or after
            this timestamp are processed. Pass None to sweep all games.
        stdout: A file-like object for progress/error output (e.g. self.stdout).

    Returns:
        int: Total number of games processed (whether or not a match was found).

    Side effects:
        Calls ``resolve_opening_id`` for each candidate game.
        Updates ``Game.opening_id`` in place via Django ORM ``save()``.
        Errors for individual games are written to ``stdout`` and skipped.
    """
    processed = 0
    candidates = Game.objects.filter(pgn__gt="", opening_id__isnull=True)
    if since is not None:
        candidates = candidates.filter(created_at__gte=since)

    for game in candidates.iterator():
        try:
            opening_id = resolve_opening_id(game.pgn)
        except Exception as exc:  # noqa: BLE001 — resolver failure is non-fatal
            stdout.write(f"opening-id resolve failed for {game.id}: {exc}\n")
            continue
        game.opening_id = opening_id
        game.save(update_fields=["opening_id"])
        processed += 1
    return processed


class Command(BaseCommand):
    """Sync Chess.com games (advisory-locked) and auto-enqueue per SiteSettings."""

    help = "Sync games from Chess.com for all (or specified) club members."

    def add_arguments(self, parser):
        """Register command-line arguments.

        Args:
            parser: The ArgumentParser instance to add arguments to.

        Returns:
            None
        """
        parser.add_argument(
            "usernames",
            nargs="*",
            help="Chess.com usernames to sync. Defaults to all club members.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Only sync archives from the last N days.",
        )

    def handle(self, *args, **options):
        """Acquire advisory lock, run sync, auto-enqueue. Release lock on exit.

        Args:
            *args: Positional arguments (unused).
            **options: Parsed command options from add_arguments.

        Returns:
            None

        Side effects:
            Acquires and releases Postgres advisory lock. May create AnalysisJob
            rows and SystemEvent rows.
        """
        if not _try_acquire_lock():
            self.stdout.write(
                "sync_games: advisory lock held; another run in progress, exiting."
            )
            return

        started_at = timezone.now()
        try:
            self._do_sync(options, started_at)
        finally:
            _release_lock()

    def _do_sync(self, options: dict, started_at) -> None:
        """Inner body — keeps lock release in handle().

        Args:
            options: Parsed command options dict.
            started_at: datetime when this sync run began (for new-game detection).

        Returns:
            None

        Side effects:
            Runs run_sync.py subprocess. Creates SystemEvent and AnalysisJob rows.
            Bulk-creates GameMoveTime rows for games with %clk PGN annotations.
        """
        usernames = options["usernames"] or list(
            Player.objects.values_list("username", flat=True)
        )
        if not usernames:
            self.stderr.write("No club members found.")
            return

        self.stdout.write(
            f"Syncing {len(usernames)} member(s): {', '.join(usernames)}"
        )

        SystemEvent.objects.create(
            event_type="game_sync",
            status="running",
            details=f"members={','.join(usernames)}",
        )

        sync_start = time.time()
        # run_sync.py accepts `--usernames=a,b,c` (single comma-joined flag),
        # NOT positional args. Always pass via the flag.
        cmd = [sys.executable, str(_SCRIPT), "--usernames", ",".join(usernames)]
        if options["days"]:
            cmd += ["--days", str(options["days"])]
        # run_sync.py uses `from app.config import get_settings`, so the
        # parent of the `app` package (services/app/) must be on PYTHONPATH.
        sync_env = {**os.environ, "PYTHONPATH": str(_SCRIPT.parents[2])}
        result = subprocess.run(cmd, capture_output=False, env=sync_env)  # noqa: S603

        elapsed = time.time() - sync_start

        if result.returncode != 0:
            SystemEvent.objects.create(
                event_type="game_sync",
                status="failed",
                duration_seconds=elapsed,
                error_message=f"run_sync exited {result.returncode}",
            )
            self.stderr.write(
                f"run_sync exited {result.returncode} after {elapsed:.1f}s"
            )
            return

        # Auto-enqueue newly ingested games per SiteSettings toggles.
        site = SiteSettings.get_solo()
        sf_count = lc_count = 0
        new_games = Game.objects.filter(created_at__gte=started_at)
        for game in new_games:
            if site.auto_enqueue_stockfish:
                if enqueue_analysis_job(
                    game=game, engine="stockfish", depth=_stockfish_depth()
                ):
                    sf_count += 1
            if site.auto_enqueue_lc0:
                if enqueue_analysis_job(
                    game=game, engine="lc0", depth=_lc0_nodes()
                ):
                    lc_count += 1

        # Issue #24: populate per-move clock data for games written by the
        # subprocess. We pass `since=None` for now (full sweep is cheap and
        # idempotent); the backfill command handles bulk historic loads.
        self._run_move_time_post_step()

        # Issue #162: resolve opening_id FK for newly ingested games.
        self._run_opening_id_post_step()

        SystemEvent.objects.create(
            event_type="game_sync",
            status="completed",
            duration_seconds=elapsed,
            details=(
                f"members={','.join(usernames)}; "
                f"new_games={new_games.count()}; "
                f"sf_enqueued={sf_count}; lc0_enqueued={lc_count}"
            ),
        )
        self.stdout.write(
            f"Sync complete in {elapsed:.1f}s — "
            f"auto-enqueued: stockfish={sf_count} lc0={lc_count}"
        )

    def _run_move_time_post_step(self) -> None:
        """Populate GameMoveTime rows post-sync, isolating failures.

        Issue #24: parse %clk annotations for every Game with non-empty PGN
        and a known time_class. Errors are logged and swallowed so the rest
        of the sync pipeline (advisory-lock release, SystemEvent close) is
        never blocked by a clock-parse hiccup.

        Returns:
            None

        Side effects:
            Bulk-creates GameMoveTime rows. May write error or success message
            to self.stdout.
        """
        try:
            written = _populate_move_times_for_recent_games(since=None, stdout=self.stdout)
            self.stdout.write(f"move-time rows written: {written}\n")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(f"move-time post-step failed: {exc}\n")

    def _run_opening_id_post_step(self) -> None:
        """Resolve and persist Game.opening_id for all games with PGN post-sync.

        Issue #162: walks the opening book ply-by-ply via resolve_opening_id
        and stamps each Game row with the deepest matching OpeningBook id.
        Failures for individual games are logged and skipped so the sync
        pipeline (advisory-lock release, SystemEvent close) is never blocked.

        Returns:
            None

        Side effects:
            Updates Game.opening_id via Django ORM save(). May write error or
            success message to self.stdout.
        """
        try:
            processed = _populate_opening_ids_for_recent_games(since=None, stdout=self.stdout)
            self.stdout.write(f"opening-id rows resolved: {processed}\n")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(f"opening-id post-step failed: {exc}\n")
