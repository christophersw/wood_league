"""Management command: run the Stockfish analysis worker."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

_SCRIPT = Path(__file__).resolve().parents[3] / "app" / "ingest" / "run_analysis_worker.py"


class Command(BaseCommand):
    """Django management command to run Stockfish engine analysis worker."""

    help = "Run the Stockfish analysis worker (processes pending analysis_jobs)."

    def add_arguments(self, parser):
        """Register command-line arguments."""
        parser.add_argument("--once", action="store_true", help="Process one job then exit.")

    def handle(self, *args, **options):
        """Start Stockfish worker process."""
        cmd = [sys.executable, str(_SCRIPT)]
        if options["once"]:
            cmd.append("--once")
        self.stdout.write(f"Starting Stockfish worker: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=False)  # noqa: S603
        if result.returncode != 0:
            raise SystemExit(result.returncode)
