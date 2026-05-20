"""
Title: backfill_opening_ids.py — Backfill Game.opening_id for legacy rows
Description:
    Iterates ``Game`` rows where ``opening_id IS NULL`` and writes the
    resolver's best match. Idempotent; safe to re-run. Used after the
    #162 migration that added the FK.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from games.models import Game
from games.opening_resolver import resolve_opening_id


class Command(BaseCommand):
    """Backfill the denormalised Game.opening_id column."""

    help = "Backfill Game.opening_id for rows where it is NULL."

    def add_arguments(self, parser):
        """Register CLI flags."""
        parser.add_argument(
            "--batch", type=int, default=500,
            help="Rows fetched per page (default 500).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Compute matches but do not write.",
        )

    def handle(self, *args, **opts):
        """Run the backfill, logging counts to stdout."""
        batch = opts["batch"]
        dry = opts["dry_run"]
        resolved, unresolved, errors = self._run(batch, dry)
        self.stdout.write(
            f"done: resolved={resolved} unresolved={unresolved} "
            f"errors={errors} dry_run={dry}"
        )

    def _run(self, batch: int, dry: bool) -> tuple[int, int, int]:
        """Walk null-opening Games in pages, return (resolved, unresolved, errors)."""
        resolved = unresolved = errors = 0
        qs = Game.objects.filter(opening_id__isnull=True).only("id", "pgn")
        total = qs.count()
        self.stdout.write(f"backfill_opening_ids: {total} rows to process")
        for start in range(0, total, batch):
            for game in list(qs[start:start + batch]):
                r, u, e = self._resolve_one(game, dry)
                resolved += r
                unresolved += u
                errors += e
        return resolved, unresolved, errors

    def _resolve_one(self, game, dry: bool) -> tuple[int, int, int]:
        """Resolve one game; return one-hot (resolved, unresolved, errors)."""
        try:
            oid = resolve_opening_id(game.pgn or "")
        except Exception as exc:  # noqa: BLE001 — log & skip per row
            self.stderr.write(f"game={game.id}: {exc}")
            return (0, 0, 1)
        if oid is None:
            return (0, 1, 0)
        if not dry:
            Game.objects.filter(pk=game.pk).update(opening_id=oid)
        return (1, 0, 0)
