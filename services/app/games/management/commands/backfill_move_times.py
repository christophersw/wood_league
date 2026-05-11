"""
Title: backfill_move_times.py — One-shot backfill of GameMoveTime rows
Description:
    Sweeps every Game with non-empty pgn and a known time_class, parses
    the %clk annotations via games.clock_parser.parse_move_times, and
    bulk-creates GameMoveTime rows. Idempotent: rewrites existing rows
    per game inside a transaction. Pre-2020 daily games (no %clk) are
    skipped silently.

Changelog:
    2026-05-11: Initial creation (issue #24).
    2026-05-11: Add SystemEvent logging + post-write sanity checks (issue #24).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from games.clock_parser import parse_move_times
from games.models import Game, GameMoveTime
from ingest.models import SystemEvent


_BATCH_SIZE = 500


def _run_sanity_checks() -> list[str]:
    """Verify GameMoveTime invariants post-backfill.

    Two checks per spec:
      1. Daily games: sum(time_spent_ms) <= (end_time - start_time) * 1000.
      2. Live games: last clock_after_ms >= 0.

    Returns a list of human-readable violation messages (empty if all-clear).
    """
    violations: list[str] = []

    # Check 1: daily games' total think time should not exceed wall-clock.
    daily_games = Game.objects.filter(
        time_class="daily",
        move_times__isnull=False,
        started_at_utc__isnull=False,
    ).distinct()
    for game in daily_games.iterator():
        total_ms = GameMoveTime.objects.filter(game=game).aggregate(
            total=Sum("time_spent_ms")
        )["total"] or 0
        wall_clock_ms = int((game.played_at - game.started_at_utc).total_seconds() * 1000)
        if total_ms > wall_clock_ms:
            violations.append(
                f"daily game {game.id}: sum(time_spent_ms)={total_ms} > "
                f"wall_clock_ms={wall_clock_ms}"
            )

    # Check 2: live games' final clock_after_ms should be >= 0.
    live_negative = (
        GameMoveTime.objects.filter(
            game__time_class__in=["bullet", "blitz", "rapid"],
            clock_after_ms__lt=0,
        )
        .values_list("game_id", "ply", "clock_after_ms")[:50]
    )
    for game_id, ply, clk in live_negative:
        violations.append(f"live game {game_id} ply {ply}: clock_after_ms={clk}")

    return violations


class Command(BaseCommand):
    """Django management command to backfill GameMoveTime rows from PGN data."""

    help = "Backfill GameMoveTime rows from existing Game.pgn data."

    def add_arguments(self, parser):
        """
        Register CLI flags for the command.

        Parameters:
            parser (ArgumentParser): Django's argument parser instance.
        """
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse + report counts without writing.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of games to process (useful for smoke testing).",
        )

    def handle(self, *args, **options):
        """
        Iterate Games, parse PGN clock annotations, and bulk-write GameMoveTime rows.

        Parameters:
            args: Positional arguments (unused).
            options (dict): Parsed CLI options including 'dry_run' and 'limit'.

        Side effects:
            Writes or deletes GameMoveTime rows in the database unless --dry-run.
            Outputs progress and summary to stdout.
            Writes a SystemEvent row at completion.
        """
        dry_run: bool = options["dry_run"]
        limit: int | None = options["limit"]
        started_at = timezone.now()

        qs = Game.objects.filter(pgn__gt="", time_class__isnull=False).order_by("id")
        if limit is not None:
            qs = qs[:limit]

        games_seen = 0
        rows_written = 0
        rows_planned = 0
        failures = 0

        for game in qs.iterator(chunk_size=_BATCH_SIZE):
            games_seen += 1
            try:
                move_times = parse_move_times(
                    game.pgn,
                    time_class=game.time_class,
                    time_control_base_s=game.time_control_base_s,
                    time_control_increment_s=game.time_control_increment_s,
                )
            except Exception as exc:  # noqa: BLE001 — best-effort parse
                failures += 1
                self.stdout.write(
                    self.style.WARNING(f"  parse failed for {game.id}: {exc}")
                )
                continue
            if not move_times:
                continue
            if dry_run:
                rows_planned += len(move_times)
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
                rows_written += len(move_times)

        # Run sanity checks (skip if dry-run, since no rows were written).
        sanity_violations: list[str] = []
        if not dry_run:
            sanity_violations = _run_sanity_checks()
            for line in sanity_violations:
                self.stdout.write(self.style.WARNING(f"  sanity violation: {line}"))

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN: scanned {games_seen} games, would write {rows_planned} rows, "
                    f"{failures} parse failures."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Backfill complete: scanned {games_seen} games, wrote {rows_written} rows, "
                    f"{failures} parse failures."
                )
            )

        # Write SystemEvent for audit trail.
        completed_at = timezone.now()
        duration_seconds = (completed_at - started_at).total_seconds()
        details_payload = {
            "dry_run": dry_run,
            "games_seen": games_seen,
            "rows_written": rows_written if not dry_run else 0,
            "rows_planned": rows_planned if dry_run else 0,
            "parse_failures": failures,
            "sanity_violations": sanity_violations if not dry_run else [],
        }
        SystemEvent.objects.create(
            event_type="backfill_move_times",
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            details=json.dumps(details_payload),
        )
