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
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from games.clock_parser import parse_move_times
from games.models import Game, GameMoveTime


_BATCH_SIZE = 500


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
        """
        dry_run: bool = options["dry_run"]
        limit: int | None = options["limit"]

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
