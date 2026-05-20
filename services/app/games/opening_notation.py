"""
Title: opening_notation.py — Truncated PGN move list
Description:
    Returns a short SAN move list (``"1. e4 e5 2. Nf3 Nc6 …"``) suitable for
    a search-results cell. Truncates to ``max_plies`` half-moves and
    appends an ellipsis when the game has more.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

import io

import chess.pgn


def _parse_game(pgn_text: str):
    """Return the parsed ``chess.pgn.Game`` or ``None`` on any failure."""
    if not pgn_text or not pgn_text.strip():
        return None
    try:
        return chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:  # noqa: BLE001 — defensive
        return None


def _san_token(ply_index: int, san: str) -> str:
    """Render one ply as either ``"N. san"`` (White) or ``"san"`` (Black)."""
    if ply_index % 2 == 0:
        return f"{(ply_index // 2) + 1}. {san}"
    return san


def opening_notation(pgn_text: str, max_plies: int = 10) -> str:
    """Render the first ``max_plies`` plies of ``pgn_text`` as SAN notation."""
    game = _parse_game(pgn_text)
    if game is None:
        return ""

    board = game.board()
    moves = list(game.mainline_moves())
    visible = moves[:max_plies]
    truncated = len(moves) > len(visible)

    parts: list[str] = []
    for ply_index, move in enumerate(visible):
        parts.append(_san_token(ply_index, board.san(move)))
        board.push(move)

    text = " ".join(parts)
    return f"{text} …" if truncated else text
