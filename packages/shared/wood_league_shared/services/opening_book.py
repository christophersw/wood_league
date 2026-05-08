"""
Title: opening_book.py — Chess opening lookup service
Description:
    Lookup service for chess opening names using the Lichess openings dataset.
    On first run, ingests the TSV files from a configurable data directory into
    the opening_book table. All subsequent lookups hit the DB via a process-level
    in-memory cache. This is the superset of stockfish_pipeline and app versions,
    including lookup_opening_entry() and matched_opening_from_pgn() from the app.

Changelog:
    2026-05-07: Merged superset from stockfish_pipeline and app into shared library
"""

from __future__ import annotations

import csv
import io
import logging
from functools import lru_cache
from pathlib import Path

import chess
import chess.pgn
from sqlalchemy import func, select

from wood_league_shared.storage.database import get_session, init_db
from wood_league_shared.storage.models import OpeningBook

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "openings"


# ---------------------------------------------------------------------------
# Ingest TSV files → opening_book table
# ---------------------------------------------------------------------------

def ingest_opening_book(data_dir: Path | None = None) -> int:
    """Parse TSV files and upsert rows into the opening_book table.

    Parameters:
        data_dir (Path | None): Directory containing .tsv opening files.
            Defaults to the package-relative data/openings/ directory.

    Returns:
        int: The number of rows in the table after ingest.

    Side effects:
        Calls init_db() and writes OpeningBook rows to the database.
    """
    init_db()
    source_dir = data_dir or _DATA_DIR

    # Read TSV data and compute EPDs.
    entries: dict[str, tuple[str, str, str]] = {}  # epd → (eco, name, pgn)
    for tsv_file in sorted(source_dir.glob("*.tsv")):
        with open(tsv_file, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            for row in reader:
                eco = (row.get("eco") or "").strip()
                name = (row.get("name") or "").strip()
                pgn_text = (row.get("pgn") or "").strip()
                if not pgn_text or not name:
                    continue
                game = chess.pgn.read_game(io.StringIO(pgn_text))
                if game is None:
                    continue
                board = game.board()
                for move in game.mainline_moves():
                    board.push(move)
                epd = board.epd()
                existing = entries.get(epd)
                if existing is None or len(name) > len(existing[1]):
                    entries[epd] = (eco, name, pgn_text)

    with get_session() as session:
        existing_epds = {
            r[0] for r in session.execute(select(OpeningBook.epd)).all()
        }
        new_rows = []
        for epd, (eco, name, pgn_text) in entries.items():
            if epd not in existing_epds:
                new_rows.append(OpeningBook(eco=eco, name=name, pgn=pgn_text, epd=epd))
        if new_rows:
            session.add_all(new_rows)
            session.commit()
            log.info("Inserted %d new opening book entries", len(new_rows))

        total = session.scalar(select(func.count(OpeningBook.id))) or 0
    return total


def ensure_opening_book() -> None:
    """Ensure the opening_book table is populated (idempotent).

    Side effects:
        Calls init_db() and may call ingest_opening_book() if the table is empty.
    """
    init_db()
    with get_session() as session:
        count = session.scalar(select(func.count(OpeningBook.id))) or 0
    if count == 0:
        ingest_opening_book()


# ---------------------------------------------------------------------------
# In-memory cache loaded from DB
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_book_entries() -> dict[str, tuple[int, str, str]]:
    """Return {epd: (id, eco, name)} from the opening_book table.

    Returns:
        dict[str, tuple[int, str, str]]: EPD-keyed dict of (id, eco, name) tuples.

    Side effects:
        Calls ensure_opening_book() on first invocation. Result is cached.
    """
    ensure_opening_book()
    book: dict[str, tuple[int, str, str]] = {}
    with get_session() as session:
        rows = session.execute(
            select(OpeningBook.id, OpeningBook.epd, OpeningBook.eco, OpeningBook.name)
        ).all()
    for opening_id, epd, eco, name in rows:
        book[epd] = (opening_id, eco, name)
    return book


@lru_cache(maxsize=1)
def _load_book() -> dict[str, tuple[str, str]]:
    """Return {epd: (eco, name)} from the opening_book table.

    Returns:
        dict[str, tuple[str, str]]: EPD-keyed dict of (eco, name) tuples.

    Side effects:
        Calls _load_book_entries() on first invocation. Result is cached.
    """
    return {
        epd: (eco, name)
        for epd, (_, eco, name) in _load_book_entries().items()
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_opening(board: chess.Board) -> tuple[str, str] | None:
    """Return (eco, name) for the current board position, or None.

    Parameters:
        board (chess.Board): A python-chess Board at the position to look up.

    Returns:
        tuple[str, str] | None: (eco, name) if found, None otherwise.
    """
    return _load_book().get(board.epd())


def lookup_opening_entry(board: chess.Board) -> tuple[int, str, str] | None:
    """Return (id, eco, name) for the current board position, or None.

    Parameters:
        board (chess.Board): A python-chess Board at the position to look up.

    Returns:
        tuple[int, str, str] | None: (id, eco, name) if found, None otherwise.
    """
    return _load_book_entries().get(board.epd())


def matched_opening_from_pgn(
    pgn_text: str,
    max_ply: int = 20,
) -> tuple[int, str, str] | None:
    """Return the most specific opening-book entry reached in a PGN.

    Parameters:
        pgn_text (str): PGN text to play through.
        max_ply (int): Maximum number of half-moves to examine. Defaults to 20.

    Returns:
        tuple[int, str, str] | None: (id, eco, name) of the deepest matched
            opening, or None if no opening was matched.
    """
    pgn_text = str(pgn_text or "").strip()
    if not pgn_text:
        return None

    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return None

    board = game.board()
    best: tuple[int, str, str] | None = None
    for i, move in enumerate(game.mainline_moves(), start=1):
        board.push(move)
        hit = lookup_opening_entry(board)
        if hit is not None:
            best = hit
        if i >= max_ply:
            break

    return best


def opening_at_each_ply(pgn_text: str, max_ply: int = 10) -> list[tuple[str, str]]:
    """Play through a PGN and return the best-known opening name at each ply.

    Returns a list of length min(total_moves, max_ply) + 1 (index 0 = start pos).
    Each element is (eco, name). If no opening matches at a ply, the previous
    ply's value is carried forward. The start position defaults to ("", "Starting Position").

    Parameters:
        pgn_text (str): PGN text to play through.
        max_ply (int): Maximum number of half-moves to examine. Defaults to 10.

    Returns:
        list[tuple[str, str]]: List of (eco, name) tuples indexed by ply.
    """
    book = _load_book()
    pgn_text = str(pgn_text or "").strip()
    if not pgn_text:
        return [("", "Starting Position")]

    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return [("", "Starting Position")]

    board = game.board()
    current: tuple[str, str] = book.get(board.epd(), ("", "Starting Position"))
    result: list[tuple[str, str]] = [current]

    for i, move in enumerate(game.mainline_moves(), start=1):
        board.push(move)
        hit = book.get(board.epd())
        if hit is not None:
            current = hit
        result.append(current)
        if i >= max_ply:
            break

    return result


def search_openings(query: str, limit: int = 50) -> list[tuple[str, str]]:
    """Case-insensitive substring search against the DB.

    Parameters:
        query (str): Substring to search for in opening names.
        limit (int): Maximum number of results to return. Defaults to 50.

    Returns:
        list[tuple[str, str]]: List of (eco, name) tuples matching the query.
    """
    ensure_opening_book()
    with get_session() as session:
        rows = session.execute(
            select(OpeningBook.eco, OpeningBook.name)
            .where(OpeningBook.name.ilike(f"%{query}%"))
            .order_by(OpeningBook.name)
            .limit(limit)
        ).all()
    return [(eco, name) for eco, name in rows]


def backfill_lichess_openings(batch_size: int = 500) -> int:
    """Backfill the lichess_opening column on games that have PGN but no lichess_opening.

    Parameters:
        batch_size (int): Number of games to commit per batch. Defaults to 500.

    Returns:
        int: The number of games updated.

    Side effects:
        Updates Game.lichess_opening for matching rows and commits to the database.
    """
    from wood_league_shared.storage.models import Game

    updated = 0

    with get_session() as session:
        games = session.execute(
            select(Game.id, Game.pgn)
            .where(Game.pgn != "", Game.lichess_opening.is_(None))
        ).all()

        for game_id, pgn_text in games:
            pgn_text = (pgn_text or "").strip()
            if not pgn_text:
                continue

            best = matched_opening_from_pgn(pgn_text, max_ply=20)

            if best:
                _, eco, name = best
                label = f"{eco} {name}".strip() if eco else name
                session.query(Game).filter(Game.id == game_id).update(
                    {"lichess_opening": label}
                )
                updated += 1

            if updated % batch_size == 0 and updated > 0:
                session.commit()

        session.commit()

    log.info("Backfilled lichess_opening on %d games", updated)
    return updated
