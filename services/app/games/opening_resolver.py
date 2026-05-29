"""
Title: opening_resolver.py — Resolve a PGN to its deepest OpeningBook id
Description:
    Walks a PGN ply by ply, querying ``openings.lookup_opening_entry`` for
    each position, and returns the id of the deepest board that still
    matched the book. Used at game ingest to denormalise
    ``Game.opening_id`` so downstream views can link to the opening
    detail page without re-parsing the PGN.

Changelog:
    2026-05-20: Initial creation (#162).
    2026-05-29 (#226 review): Delegate to games.opening_book_context.book_context
        so the deepest-opening walk lives in exactly one place (was a duplicate
        of book_context's walk that had to be kept in sync by hand).
"""
from __future__ import annotations

from games.opening_book_context import book_context


def resolve_opening_id(pgn_text: str) -> int | None:
    """Return the deepest OpeningBook id reachable from ``pgn_text``.

    Args:
        pgn_text: Raw PGN. Empty / unparseable input yields ``None``.

    Returns:
        Integer ``OpeningBook.id`` of the deepest matching node, or
        ``None`` when no position in the game matched.
    """
    return book_context(pgn_text).opening_id
