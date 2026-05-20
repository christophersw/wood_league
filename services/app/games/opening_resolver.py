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
"""
from __future__ import annotations

import io

import chess.pgn

from openings.services import lookup_opening_entry


def _parse_game(pgn_text: str):
    """Return the parsed game, or ``None`` if the PGN is empty or unparseable."""
    if not pgn_text or not pgn_text.strip():
        return None
    try:
        return chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:  # noqa: BLE001 — defensive
        return None


def resolve_opening_id(pgn_text: str) -> int | None:
    """Return the deepest OpeningBook id reachable from ``pgn_text``.

    Args:
        pgn_text: Raw PGN. Empty / unparseable input yields ``None``.

    Returns:
        Integer ``OpeningBook.id`` of the deepest matching node, or
        ``None`` when no position in the game matched.
    """
    game = _parse_game(pgn_text)
    if game is None:
        return None

    board = game.board()
    deepest: int | None = None
    hit = lookup_opening_entry(board)
    if hit is not None:
        deepest = hit[0]
    for move in game.mainline_moves():
        board.push(move)
        hit = lookup_opening_entry(board)
        if hit is None:
            break
        deepest = hit[0]
    return deepest
