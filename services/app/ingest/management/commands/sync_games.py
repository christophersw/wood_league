"""
Title: sync_games.py — Django management command for Chess.com game sync
Description:
    Acquires a Postgres advisory lock (cron-overlap protection), runs the
    existing Chess.com sync subprocess (run_sync.py), then auto-enqueues
    AnalysisJobs for newly-ingested games per SiteSettings toggles.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-10: Add advisory lock + auto-enqueue + SystemEvent (Task D1).
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
from games.models import Game
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
        cmd = [sys.executable, str(_SCRIPT)] + usernames
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
