"""
Title: delete_test_games.py — Remove leaked pytest-fixture games from the DB

Description:
    The test suite creates Game rows with an ``id`` like
    ``test-A4-<hex>`` / ``test-A3-<hex>`` / ``test-game-…`` (e.g.
    analysis/tests/test_runpod_dispatch.py). These leaked into the
    shared/production DB when a test run used the main DB config instead
    of the dedicated dev test DB, and surfaced in the "last ten games"
    list after the #141 requeue queued every game (issue #9).

    Real games never use a ``test-`` id prefix (Chess.com sync ids are
    numeric/slug), so ``id__startswith="test-"`` is a safe selector. All
    Game foreign keys are on_delete=CASCADE (participants, move_times,
    analysis_jobs, GameAnalysis→MoveAnalysis, Lc0GameAnalysis→
    Lc0MoveAnalysis), so deleting the Game removes its children too.

    Safety mirrors requeue_all_analysis: requires an explicit
    --dry-run (report only) or --yes (delete). Neither aborts.

Changelog:
    2026-05-17: Initial creation (issue #9).
"""
from __future__ import annotations

import collections
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from games.models import Game
from ingest.models import SystemEvent

_TEST_ID_PREFIX = "test-"
_EVENT_TYPE = "delete_test_games"


def _prefix_breakdown(ids: list[str]) -> dict[str, int]:
    """Group leaked ids by their ``test-<tag>-`` family for the report.

    Parameters:
        ids: the matched Game ids.

    Returns:
        dict[str, int]: count keyed by the first two dash-segments
        (e.g. "test-A4"), so the operator can eyeball what is being
        removed before confirming.
    """
    counter: collections.Counter[str] = collections.Counter()
    for game_id in ids:
        parts = game_id.split("-")
        key = "-".join(parts[:2]) if len(parts) >= 2 else game_id
        counter[key] += 1
    return dict(sorted(counter.items()))


class Command(BaseCommand):
    """Delete pytest-fixture games (id prefix ``test-``) from the DB (#9)."""

    help = (
        "DESTRUCTIVE: delete every Game whose id starts with 'test-' "
        "(leaked pytest fixtures) and its cascaded children. Requires "
        "--dry-run or --yes."
    )

    def add_arguments(self, parser):
        """Register CLI flags.

        Parameters:
            parser (ArgumentParser): Django's argument parser instance.
        """
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted; delete nothing.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Perform the deletion.",
        )

    def handle(self, *args, **options):
        """Delete leaked test-fixture games, or report them on --dry-run.

        Parameters:
            args: Positional arguments (unused).
            options (dict): Parsed CLI options: dry_run, yes.

        Side effects:
            Unless --dry-run: deletes matching Game rows (cascading to
            children) in one transaction and writes a SystemEvent audit
            row. Outputs a summary to stdout.

        Raises:
            CommandError: if neither --dry-run nor --yes is supplied.
        """
        dry_run: bool = options["dry_run"]
        do_it: bool = options["yes"]

        if dry_run == do_it:  # neither, or contradictory both
            raise CommandError(
                "Refusing to run without an explicit mode. Pass "
                "--dry-run to preview, or --yes to delete."
            )

        started_at = timezone.now()
        qs = Game.objects.filter(id__startswith=_TEST_ID_PREFIX)
        matched_ids = list(qs.values_list("id", flat=True))
        breakdown = _prefix_breakdown(matched_ids)

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN: would delete {len(matched_ids)} test- "
                    f"games (+cascaded children). Breakdown: {breakdown}. "
                    f"Sample: {matched_ids[:5]}"
                )
            )
            return

        with transaction.atomic():
            _, deleted_by_model = qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {len(matched_ids)} test- games. "
                f"Cascaded rows: {deleted_by_model}"
            )
        )

        completed_at = timezone.now()
        SystemEvent.objects.create(
            event_type=_EVENT_TYPE,
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
            details=json.dumps(
                {
                    "games_deleted": len(matched_ids),
                    "breakdown": breakdown,
                    "cascaded": deleted_by_model,
                }
            ),
        )
