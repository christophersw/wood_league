"""
Title: run_analysis_worker.py — CLI entry point for the Stockfish analysis worker
Description:
    Parses command-line arguments and drives the analysis worker loop.
    Supports enqueueing unanalyzed games, running analysis against a local or
    configured Stockfish binary, and printing queue status.

    Usage examples:
      # Enqueue all unanalyzed games, then run analysis on this machine:
      python -m stockfish_pipeline.ingest.run_analysis_worker --enqueue

      # Run worker using a specific Stockfish binary:
      python -m stockfish_pipeline.ingest.run_analysis_worker --stockfish /usr/local/bin/stockfish

      # Full pipeline: enqueue + analyze, depth 18, exit when queue empty:
      python -m stockfish_pipeline.ingest.run_analysis_worker --enqueue --stockfish /path/to/sf --depth 18 --no-poll

      # Just show queue status:
      python -m stockfish_pipeline.ingest.run_analysis_worker --status

Changelog:
    2026-05-07 (#1): Add file header and docstrings; fix shutil.os path access
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _find_stockfish(given: str) -> str:
    """Resolve the path to the Stockfish binary, falling back to common install locations.

    Parameters:
        given: explicit path from the --stockfish CLI argument (may be empty string).

    Returns:
        Resolved path string if found, or empty string if Stockfish cannot be located.
    """
    if given:
        return given
    found = shutil.which("stockfish")
    if found:
        return found
    for candidate in ["/usr/local/bin/stockfish", "/usr/bin/stockfish", "/opt/homebrew/bin/stockfish"]:
        if os.path.isfile(candidate):
            return candidate
    return ""


def main() -> None:
    """Parse CLI arguments and run the appropriate worker action.

    Actions (mutually exclusive or composable via flags):
        --status        Print queue status counts and exit.
        --enqueue       Enqueue unanalyzed games before starting the worker.
        --enqueue-only  Enqueue jobs and exit without starting the worker.
        (default)       Start the worker loop against the resolved Stockfish binary.

    Side effects:
        Initializes the database schema, writes analysis results to PostgreSQL,
        and exits with code 1 if Stockfish cannot be found.
    """
    from stockfish_pipeline.config import get_settings

    settings = get_settings()

    parser = argparse.ArgumentParser(description="Wood League Chess — Stockfish analysis worker")
    parser.add_argument("--stockfish", default=settings.stockfish_path, help="Path to Stockfish binary")
    parser.add_argument("--depth", type=int, default=settings.analysis_depth, help="Analysis depth (default 20)")
    parser.add_argument("--threads", type=int, default=settings.analysis_threads, help="Stockfish threads per game")
    parser.add_argument("--hash", type=int, default=settings.analysis_hash_mb, dest="hash_mb", help="Stockfish hash table size in MB (default 256)")
    parser.add_argument("--enqueue", action="store_true", help="Enqueue unanalyzed games before starting")
    parser.add_argument("--enqueue-only", action="store_true", help="Enqueue jobs and exit without running worker")
    parser.add_argument("--enqueue-limit", type=int, default=None, help="Max games to enqueue (default: all)")
    parser.add_argument("--limit", type=int, default=None, help="Stop after processing this many games")
    parser.add_argument("--no-poll", action="store_true", help="Exit when queue is empty instead of polling")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between queue polls (default 5)")
    parser.add_argument("--status", action="store_true", help="Print queue status and exit")
    args = parser.parse_args()

    from stockfish_pipeline.ingest.enqueue_analysis import enqueue_unanalyzed, queue_status
    from stockfish_pipeline.storage.database import init_db

    init_db()

    if args.status:
        counts = queue_status()
        for status, n in sorted(counts.items()):
            print(f"  {status:12s}  {n}")
        return

    if args.enqueue or args.enqueue_only:
        n = enqueue_unanalyzed(depth=args.depth, limit=args.enqueue_limit)
        log.info("Enqueued %d new jobs.", n)

    if args.enqueue_only:
        return

    sf_path = _find_stockfish(args.stockfish)
    if not sf_path:
        log.error(
            "Stockfish not found. Install it (e.g. `brew install stockfish`) "
            "or pass --stockfish /path/to/binary"
        )
        sys.exit(1)

    log.info("Using Stockfish: %s", sf_path)

    from stockfish_pipeline.ingest.analysis_worker import run_worker

    run_worker(
        stockfish_path=sf_path,
        depth=args.depth,
        threads=args.threads,
        hash_mb=args.hash_mb,
        poll_interval=0.0 if args.no_poll else args.poll_interval,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
