"""Management command: sync games from Chess.com for all club members."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

from players.models import Player

_SCRIPT = Path(__file__).resolve().parents[3] / "app" / "ingest" / "run_sync.py"


class Command(BaseCommand):
    """Django management command to sync Chess.com games for club members."""

    help = "Sync games from Chess.com for all (or specified) club members."

    def add_arguments(self, parser):
        """Register command-line arguments."""
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
        """Execute game sync for specified or all club members."""
        usernames = options["usernames"] or list(
            Player.objects.values_list("username", flat=True)
        )
        if not usernames:
            self.stderr.write("No club members found.")
            return

        self.stdout.write(f"Syncing {len(usernames)} member(s): {', '.join(usernames)}")

        cmd = [sys.executable, str(_SCRIPT)] + usernames
        if options["days"]:
            cmd += ["--days", str(options["days"])]

        result = subprocess.run(cmd, capture_output=False)  # noqa: S603
        if result.returncode != 0:
            raise SystemExit(result.returncode)
