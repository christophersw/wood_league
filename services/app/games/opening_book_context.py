"""
Title: opening_book_context.py — Resolve a game's opening + leading book plies
Description:
    Single PGN walk that returns the deepest matched OpeningBook entry
    (id, eco, common name) plus the number of leading half-moves that are
    still "book" (opening theory). This is the canonical break-on-first-miss
    walk for the whole app: games.opening_resolver.resolve_opening_id now
    delegates here, so the resolved opening, the book depth used by the
    analysis charts, and the "This Move" panel all derive from one place.

Changelog:
    2026-05-29: Initial creation (#226).
    2026-05-29 (#226 review): Add book_context_from_game so callers holding an
        already-parsed game skip a redundant re-parse; opening_resolver now
        delegates to this module (one walk, not two).
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


def book_context_from_game(game: chess.pgn.Game | None) -> BookContext:
    """Resolve the deepest opening + leading book-ply count from a parsed game.

    Prefer this over :func:`book_context` when the caller already holds a
    parsed ``chess.pgn.Game`` — it avoids a redundant PGN re-parse. The walk
    pushes moves onto a fresh ``game.board()`` and never mutates ``game``.

    Args:
        game (chess.pgn.Game | None): Parsed game, or None for a no-book result.

    Returns:
        BookContext: Deepest matched opening identity and the leading book depth.
            Walk stops at the first position with no book entry (after the start).
    """
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


def book_context(pgn_text: str) -> BookContext:
    """Parse raw PGN and resolve the deepest opening + leading book-ply count.

    Thin wrapper over :func:`book_context_from_game` that owns the parse.

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
    return book_context_from_game(game)
