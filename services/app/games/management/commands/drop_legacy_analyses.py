"""
Title: drop_legacy_analyses — One-shot cleanup of pre-#161 analysis rows
Description:
    Deletes ``GameAnalysis`` rows whose moves include any NULL
    ``move_win_delta`` (legacy Stockfish output) and ``Lc0GameAnalysis``
    rows whose moves include any NULL ``wdl_win_adj`` (pre-#159 LC0).
    Cascades through child move rows. Dry-run by default.

Changelog:
    2026-05-21 (#186): Initial.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from analysis.models import GameAnalysis, Lc0GameAnalysis


class Command(BaseCommand):
    help = "Drop legacy analyses missing new derived fields (#186)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually delete rows. Without this flag the command is a dry run.",
        )

    def handle(self, *args, **opts):
        apply_changes = bool(opts.get("apply"))
        sf_qs = GameAnalysis.objects.annotate(
            legacy_move_count=Count("moves", filter=Q(moves__move_win_delta__isnull=True))
        ).filter(legacy_move_count__gt=0)
        lc0_qs = Lc0GameAnalysis.objects.annotate(
            legacy_move_count=Count("moves", filter=Q(moves__wdl_win_adj__isnull=True))
        ).filter(legacy_move_count__gt=0)

        sf_count = sf_qs.count()
        lc0_count = lc0_qs.count()

        prefix = "" if apply_changes else "DRY RUN — "
        self.stdout.write(f"{prefix}SF analyses to drop: {sf_count}")
        self.stdout.write(f"{prefix}LC0 analyses to drop: {lc0_count}")

        if not apply_changes:
            self.stdout.write("Re-run with --apply to delete.")
            return

        sf_qs.delete()
        lc0_qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {sf_count} SF + {lc0_count} LC0 analyses."))
