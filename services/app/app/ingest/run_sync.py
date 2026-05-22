"""
Title: run_sync.py — Chess.com synchronization CLI
Description:
    Command-line entry point for syncing Chess.com player archives to the local database.
    Accepts usernames from CLI or environment, orchestrates game fetching from Chess.com API,
    parses PGNs, and upserts Game and GameParticipant records with real-time progress display.

Changelog:
    2026-05-22: Add --full to bypass the incremental watermark (#204) and
                report archives skipped in the summary.
    2026-05-08: Added file header to meet documentation standards
"""
from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.ingest.sync_service import ChessComSyncService


def _render_bar(current: int, total: int, width: int = 28) -> str:
    """Render a simple ASCII progress bar for archive sync status."""
    if total <= 0:
        return "[no archives]"
    ratio = max(0.0, min(1.0, current / total))
    filled = int(width * ratio)
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def main() -> None:
    """CLI entry point: sync Chess.com player archives to database with progress display."""
    parser = argparse.ArgumentParser(description="Sync Chess.com archives into local database")
    parser.add_argument(
        "--usernames",
        default="",
        help="Comma-separated usernames. If omitted, uses CHESS_COM_USERNAMES from environment.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore the per-player watermark and re-ingest all in-scope archives.",
    )
    args = parser.parse_args()

    settings = get_settings()
    usernames_raw = args.usernames.strip() or settings.chess_com_usernames
    usernames = [u.strip().lower() for u in usernames_raw.split(",") if u.strip()]

    if not usernames:
        raise SystemExit("No usernames provided. Use --usernames or set CHESS_COM_USERNAMES.")

    service = ChessComSyncService()
    results = []

    for username in usernames:
        previous = {"current": -1}

        def progress_callback(cb_username: str, current: int, total: int, stats):
            """Display archive sync progress bar and statistics."""
            if current == previous["current"] and total > 0:
                return
            previous["current"] = current
            bar = _render_bar(current, total)
            if total > 0:
                message = (
                    f"{cb_username:>16} {bar} {current:>3}/{total:<3} "
                    f"inserted={stats.inserted:<5} updated={stats.updated:<5}"
                )
            else:
                message = f"{cb_username:>16} {bar} inserted={stats.inserted:<5} updated={stats.updated:<5}"
            sys.stdout.write("\r" + message)
            sys.stdout.flush()

        result = service.sync_player(
            username, progress_callback=progress_callback, full=args.full
        )
        results.append(result)
        sys.stdout.write("\n")
        sys.stdout.flush()

    for result in results:
        print(
            f"{result.username}: archives={result.archives_scanned} "
            f"skipped={result.archives_skipped} "
            f"inserted={result.inserted} updated={result.updated}"
        )


if __name__ == "__main__":
    main()
