"""
Title: opening_book_context.py — Resolve a game's opening + leading book plies
Description:
    Single PGN walk that returns the deepest matched OpeningBook entry
    (id, eco, common name) plus the number of leading half-moves that are
    still "book" (opening theory). Mirrors games.opening_resolver's
    break-on-first-miss walk so the resolved opening stays consistent with
    the denormalised Game.opening FK, while also reporting the book depth
    used by the analysis charts and the "This Move" panel.

Changelog:
    2026-05-29: Initial creation (#226).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import chess.pgn

from openings.services import lookup_opening_entry


@dataclass(frozen=True)
class BookContext:
    """Resolved opening identity + leading book depth for one game.

    Attributes:
        opening_id (int | None): Deepest matched OpeningBook id, or None.
        eco (str): ECO code of the deepest match ("" when unmatched).
        name (str): Common name of the deepest match ("" when unmatched).
        book_ply_count (int): Count of leading half-moves that are book
            theory (1-indexed ply of the deepest match). 0 means no move was
            in book — either nothing matched, or only the initial position did.
    """

    opening_id: int | None
    eco: str
    name: str
    book_ply_count: int


_NO_BOOK = BookContext(opening_id=None, eco="", name="", book_ply_count=0)


def book_context(pgn_text: str) -> BookContext:
    """Walk a PGN and resolve the deepest opening + leading book-ply count.

    Args:
        pgn_text (str): Raw PGN. Empty/unparseable input yields a no-book result.

    Returns:
        BookContext: Deepest matched opening identity and the leading book depth.
            Walk stops at the first position with no book entry (after the start),
            matching games.opening_resolver.resolve_opening_id semantics.
    """
    if not pgn_text or not pgn_text.strip():
        return _NO_BOOK
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:  # noqa: BLE001 — defensive against malformed PGN
        return _NO_BOOK
    if game is None:
        return _NO_BOOK

    board = game.board()
    deepest: tuple[int, str, str] | None = lookup_opening_entry(board)
    book_ply_count = 0
    for ply, move in enumerate(game.mainline_moves(), start=1):
        board.push(move)
        hit = lookup_opening_entry(board)
        if hit is None:
            break
        deepest = hit
        book_ply_count = ply

    if deepest is None:
        return _NO_BOOK
    opening_id, eco, name = deepest
    return BookContext(
        opening_id=opening_id, eco=eco, name=name, book_ply_count=book_ply_count
    )
