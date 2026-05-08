"""Lookup service for chess opening names using the Lichess openings dataset.

On first run, ingests the TSV files from data/openings/ into the ``opening_book``
table.  All subsequent lookups hit the DB via a process-level in-memory cache.
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

from app.storage.database import get_session, init_db
from app.storage.models import OpeningBook

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "openings"


# ---------------------------------------------------------------------------
# Ingest TSV files → opening_book table
# ---------------------------------------------------------------------------

def ingest_opening_book() -> int:
    """Parse TSV files and upsert rows into the opening_book table.

    Returns the number of rows in the table after ingest.
    """
    init_db()

    # Read TSV data and compute EPDs.
    entries: dict[str, tuple[str, str, str]] = {}  # epd → (eco, name, pgn)
    for tsv_file in sorted(_DATA_DIR.glob("*.tsv")):
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
    """Ensure the opening_book table is populated (idempotent)."""
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
    """Load cached opening book entries indexed by EPD position string."""
    """Return {epd: (id, eco, name)} from the opening_book table."""
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
    """Load cached opening book (ECO, name) pairs indexed by EPD."""
    """Return {epd: (eco, name)} from the opening_book table."""
    return {
        epd: (eco, name)
        for epd, (_, eco, name) in _load_book_entries().items()
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_opening(board: chess.Board) -> tuple[str, str] | None:
    """Return (eco, name) for the current board position, or None."""
    return _load_book().get(board.epd())


def lookup_opening_entry(board: chess.Board) -> tuple[int, str, str] | None:
    """Return (id, eco, name) for the current board position, or None."""
    return _load_book_entries().get(board.epd())


def matched_opening_from_pgn(
    pgn_text: str,
    max_ply: int = 20,
) -> tuple[int, str, str] | None:
    """Return the most specific opening-book entry reached in a PGN."""
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
    """Case-insensitive substring search against the DB. Returns [(eco, name), ...]."""
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

    Returns the number of games updated.
    """
    from app.storage.models import Game

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
