"""
Title: run_analysis_worker.py — CLI entry point for the Stockfish analysis worker
Description:
    Parses command-line arguments and drives the analysis worker loop.
    Job queue management (enqueue, status) is handled by the Django API;
    this script only runs the analysis worker.

    Usage examples:
      # Run worker using default settings from env:
      python -m stockfish_pipeline.ingest.run_analysis_worker

      # Run worker using a specific Stockfish binary, depth 18, exit when queue empty:
      python -m stockfish_pipeline.ingest.run_analysis_worker --stockfish /path/to/sf --depth 18 --no-poll

      # Run worker with explicit API URL (overrides WORKER_API_URL env var):
      python -m stockfish_pipeline.ingest.run_analysis_worker --api-url https://app.example.com

Changelog:
    2026-05-08 (#1): Remove SQLAlchemy enqueue/status flags; add API URL/key args
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
    """Resolve the path to the Stockfish binary, falling back to common locations.

    Args:
        given: Explicit path from the --stockfish CLI argument (may be empty string).

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
    """Parse CLI arguments and start the analysis worker loop.

    Reads WORKER_API_URL and WORKER_API_KEY from environment variables or
    --api-url / --api-key CLI flags. Exits with code 1 if Stockfish cannot
    be found or if the API URL is not configured.
    """
    from stockfish_pipeline.config import get_settings

    settings = get_settings()

    parser = argparse.ArgumentParser(description="Wood League Chess — Stockfish analysis worker")
    parser.add_argument("--stockfish", default=settings.stockfish_path, help="Path to Stockfish binary")
    parser.add_argument("--depth", type=int, default=settings.analysis_depth, help="Analysis depth (default 20)")
    parser.add_argument("--threads", type=int, default=settings.analysis_threads, help="Stockfish threads per game")
    parser.add_argument("--hash", type=int, default=settings.analysis_hash_mb, dest="hash_mb", help="Stockfish hash table size in MB (default 256)")
    parser.add_argument("--limit", type=int, default=None, help="Stop after processing this many games")
    parser.add_argument("--no-poll", action="store_true", help="Exit when queue is empty instead of polling")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between queue polls (default 5)")
    parser.add_argument("--api-url", default=settings.worker_api_url, help="Django API base URL (overrides WORKER_API_URL)")
    parser.add_argument("--api-key", default=settings.worker_api_key, help="API key (overrides WORKER_API_KEY)")
    args = parser.parse_args()

    if not args.api_url:
        log.error("WORKER_API_URL not set. Pass --api-url or set the environment variable.")
        sys.exit(1)

    if not args.api_key:
        log.error("WORKER_API_KEY not set. Pass --api-key or set the environment variable.")
        sys.exit(1)

    sf_path = _find_stockfish(args.stockfish)
    if not sf_path:
        log.error(
            "Stockfish not found. Install it (e.g. `brew install stockfish`) "
            "or pass --stockfish /path/to/binary"
        )
        sys.exit(1)

    log.info("Using Stockfish: %s", sf_path)
    log.info("API URL: %s", args.api_url)

    from stockfish_pipeline.ingest.analysis_worker import run_worker

    run_worker(
        sf_path,
        api_url=args.api_url,
        api_key=args.api_key,
        depth=args.depth,
        threads=args.threads,
        hash_mb=args.hash_mb,
        poll_interval=0.0 if args.no_poll else args.poll_interval,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
