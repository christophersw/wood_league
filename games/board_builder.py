"""
Title: board_builder.py — Chess board SVG frame builder
Description:
    Generates SVG board frames for the game analysis page. Produces one plain board
    SVG per ply and a separate, explicit arrow metadata payload for client-side
    overlay rendering. It also applies move-quality colors to the played-move
    squares so the board matches the analysis palette used elsewhere in the UI.
    This keeps arrow drawing and click handling out of the serialized chess.svg
    markup and makes the browser contract easier to maintain.

Changelog:
    2026-05-05 (#16): Exposed reusable move-quality board colors for main and
                      engine-line board highlights
    2026-05-05 (#16): Applied move-quality colors to main-board move squares
    2026-05-05 (#16): Replaced brittle SVG arrow mutation with explicit overlay
                      metadata for stable client-side rendering and interaction
    2026-05-04 (#16): Rewrote to return frame data dict instead of HTML blob;
                      promoted _build_tier_map to module level for testability.
    2025-xx-xx:       Initial implementation with build_board_viewer_html.
"""

from __future__ import annotations

import io

import chess
import chess.pgn
import chess.svg

from games.services import GameAnalysisData, MoveRow

_BOARD_COLORS = {
    "square light": "#F2E6D0",
    "square dark": "#4A8C62",
    "margin": "#1A1A1A",
    "coord": "#D4A843",
}

_MOVE_CLASSIFICATION_COLORS = {
    "brilliant": "#2C6B4A",
    "best": "#4A6E8A",
    "great": "#4A6554",
    "excellent": "#4A6554",
    "good": "#EFE4CC",
    "inaccuracy": "#E07B7B",
    "mistake": "#CE3A4A",
    "blunder": "#B53541",
}

_ENGINE_BASE_COLORS = {
    "sf": "#A8781B",
    "lc0": "#35586F",
}
_DEFAULT_TIER_OPACITIES = [0.98, 0.84, 0.68]
_UNIFORM_ARROW_STROKE_WIDTH = 11.5
_MAX_SHADE_DELTA = 220.0


def _build_tier_map(by_ply: dict[int, MoveRow], use_cp_equiv: bool) -> dict[int, list]:
    """
    Build a ply-indexed map of arrow tier entries for one engine's analysis.

    Params:
        by_ply (dict): Mapping of ply number → MoveRow from the engine.
        use_cp_equiv (bool): If True, allow cp_equiv to backfill the first score
            when the engine did not store a primary arrow score.

    Returns:
        Dict mapping ply → list of {uci, score} dicts for arrow rendering.
    """
    result: dict[int, list] = {}
    for ply, row in by_ply.items():
        entries = []
        ucis = [row.arrow_uci, row.arrow_uci_2, row.arrow_uci_3]
        scores = [row.arrow_score_1, row.arrow_score_2, row.arrow_score_3]
        if use_cp_equiv and scores[0] is None:
            scores[0] = row.cp_equiv
        for uci, score in zip(ucis, scores):
            if uci:
                entries.append({"uci": uci, "score": score})
        if entries:
            result[ply] = entries
    return result


def _board_overlay_geometry(size: int) -> dict[str, float]:
    """
    Return board-overlay geometry derived from the rendered SVG size.

    Params:
        size (int): Rendered chess.svg board size in pixels.

    Returns:
        Dict with viewBox size, board margin, and square size for overlay drawing.
    """
    board_margin = size / 32.0
    square_size = size * 3.0 / 32.0
    viewbox_size = board_margin * 2.0 + square_size * 8.0
    return {
        "viewbox_size": viewbox_size,
        "board_margin": board_margin,
        "square_size": square_size,
    }


def _mover_relative_score(played_score: float | None, is_white_move: bool) -> float | None:
    """
    Convert a white-relative engine score into mover-relative centipawns.

    Params:
        played_score (float | None): White-relative score for the played move.
        is_white_move (bool): True when the mover is White.

    Returns:
        Score from the mover's perspective, or None when unavailable.
    """
    if played_score is None:
        return None
    return float(played_score) if is_white_move else -float(played_score)


def _format_arrow_delta(engine_key: str, delta: float | None) -> str:
    """
    Format a compact engine-arrow delta for inline label text.

    Params:
        engine_key (str): "sf" or "lc0".
        delta (float | None): Improvement over the played move in cp-equivalent units.

    Returns:
        Human-readable delta text, or an empty string when unavailable.
    """
    if delta is None:
        return ""
    rounded = int(round(delta))
    return f"{rounded:+d}"


def _build_arrow_opacity(delta: float | None, tier_index: int) -> float:
    """
    Convert an arrow delta into a stable visual opacity for overlay rendering.

    Params:
        delta (float | None): Improvement over the played move in cp-equivalent units.
        tier_index (int): Zero-based rank among the engine's top suggestions.

    Returns:
        Opacity value in the inclusive range [0.42, 0.98].
    """
    fallback = _DEFAULT_TIER_OPACITIES[min(tier_index, len(_DEFAULT_TIER_OPACITIES) - 1)]
    if delta is None:
        return fallback

    normalized = max(-1.0, min(1.0, float(delta) / _MAX_SHADE_DELTA))
    scaled = (normalized + 1.0) / 2.0
    opacity = 0.42 + (scaled * 0.56)
    return round(max(0.42, min(0.98, opacity)), 3)


def _build_arrow_entries_for_engine(
    abs_ply: int,
    relative_ply: int,
    tier_map: dict[int, list] | None,
    played_scores: dict[int, float],
    engine_key: str,
    is_white_move: bool,
) -> list[dict]:
    """
    Build clickable overlay-arrow metadata for one engine at one ply.

    Params:
        abs_ply (int): Absolute ply index in the source PGN.
        relative_ply (int): One-based ply index within the rendered game frames.
        tier_map (dict[int, list] | None): Engine candidate moves keyed by ply.
        played_scores (dict[int, float]): Played-move scores keyed by ply.
        engine_key (str): "sf" or "lc0".
        is_white_move (bool): True when the mover for this ply is White.

    Returns:
        A list of overlay metadata dicts, one per suggested move.
    """
    if tier_map is None:
        return []

    tier_entries = tier_map.get(abs_ply) or tier_map.get(relative_ply) or []
    if not tier_entries:
        return []

    base_color = _ENGINE_BASE_COLORS[engine_key]
    played_score = played_scores.get(abs_ply)
    if played_score is None:
        played_score = played_scores.get(relative_ply)
    played_mover = _mover_relative_score(played_score, is_white_move)

    top_score = tier_entries[0].get("score") if tier_entries else None
    engine_label = "Stockfish" if engine_key == "sf" else "Lc0"
    overlay_entries: list[dict] = []

    for tier_index, entry in enumerate(tier_entries):
        move_uci = entry.get("uci", "")
        if not move_uci or len(move_uci) < 4:
            continue

        score = entry.get("score")
        delta = None
        if played_mover is not None and score is not None:
            delta = float(score) - played_mover
        elif tier_index > 0 and top_score is not None and score is not None:
            delta = float(score) - float(top_score)

        delta_text = _format_arrow_delta(engine_key, delta)
        tooltip = f"{engine_label} #{tier_index + 1}: {move_uci}"
        if delta_text:
            tooltip += f" ({delta_text})"

        overlay_entries.append({
            "engine": engine_key,
            "engine_label": engine_label,
            "tier": tier_index + 1,
            "request_ply": max(0, relative_ply - 1),
            "move_uci": move_uci,
            "from_sq": move_uci[:2],
            "to_sq": move_uci[2:4],
            "color": base_color,
            "opacity": _build_arrow_opacity(delta, tier_index),
            "stroke_width": _UNIFORM_ARROW_STROKE_WIDTH,
            "delta": round(float(delta), 2) if delta is not None else None,
            "delta_text": delta_text,
            "title": tooltip,
        })

    return overlay_entries


def board_colors_for_move_classification(classification: str | None) -> dict[str, str]:
    """
    Return board colors with last-move squares tinted for a move classification.

    Params:
        classification (str | None): Human-readable move quality such as
            "best", "great", or "blunder".

    Returns:
        Board color mapping for chess.svg.board(). When the classification is
        unknown or empty, the default board palette is returned unchanged.
    """
    if not classification:
        return _BOARD_COLORS

    normalized_classification = classification.strip().lower()
    highlight_color = _MOVE_CLASSIFICATION_COLORS.get(normalized_classification)
    if not highlight_color:
        return _BOARD_COLORS

    return {
        **_BOARD_COLORS,
        "square light lastmove": highlight_color,
        "square dark lastmove": highlight_color,
    }


def build_board_frames(
    data: GameAnalysisData,
    size: int = 480,
    orientation: str = "white",
) -> dict:
    """
    Generate all SVG board frames for a game and return structured data for template rendering.

    Produces one plain board frame per ply (including the start position at ply 0)
    plus explicit engine-arrow overlay metadata. Returns a dict suitable for
    JSON-encoding and embedding in the board partial template.

    Params:
        data (GameAnalysisData): Assembled game analysis data.
        size (int): Board SVG size in pixels (default 480).
        orientation (str): "white" or "black" perspective.

    Returns:
        Dict with keys:
            frames (list[str]): SVG strings, one per ply (index 0 = start position).
            arrows_by_ply (dict): Ply → list of overlay arrow metadata dicts.
            san_list (list[str]): SAN move strings in game order.
            total_frames (int): Number of frames (= number of moves + 1).
            top_player (str): Player name shown at top of board.
            top_sym (str): Chess piece symbol for top player.
            top_side (str): "White" or "Black" for top player.
            bottom_player (str): Player name shown at bottom.
            bottom_sym (str): Chess piece symbol for bottom player.
            bottom_side (str): "White" or "Black" for bottom player.
            has_sf (bool): Whether Stockfish analysis is present.
            has_lc0 (bool): Whether Lc0 analysis is present.
    """
    flipped = orientation == "black"
    game = chess.pgn.read_game(io.StringIO(data.pgn))
    if game is None:
        board = chess.Board()
        start_svg = chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS)
        return {
            "frames": [start_svg],
            "arrows_by_ply": {},
            "san_list": [],
            "total_frames": 1,
            "top_player": data.black if not flipped else data.white,
            "top_sym": "♟" if not flipped else "♙",
            "top_side": "Black" if not flipped else "White",
            "bottom_player": data.white if not flipped else data.black,
            "bottom_sym": "♙" if not flipped else "♟",
            "bottom_side": "White" if not flipped else "Black",
            "has_sf": data.has_sf,
            "has_lc0": data.has_lc0,
            "overlay_geometry": _board_overlay_geometry(size),
        }

    board = game.board()
    start_ply_offset = board.ply()
    moves_played: list[chess.Move] = list(game.mainline_moves())

    sf_by_ply: dict[int, MoveRow] = {row.ply: row for row in data.moves}
    lc0_by_ply: dict[int, MoveRow] = (
        {row.ply: row for row in data.lc0_moves} if data.lc0_moves else {}
    )

    sf_tier_map = _build_tier_map(sf_by_ply, use_cp_equiv=False) if sf_by_ply else None
    lc0_tier_map = _build_tier_map(lc0_by_ply, use_cp_equiv=True) if lc0_by_ply else None

    sf_played: dict[int, float] = {
        ply: row.cp_eval for ply, row in sf_by_ply.items() if row.cp_eval is not None
    }
    lc0_played: dict[int, float] = {
        ply: row.cp_equiv for ply, row in lc0_by_ply.items() if row.cp_equiv is not None
    }

    san_list: list[str] = []
    arrows_by_ply: dict[int, list] = {}
    frames: list[str] = []
    overlay_geometry = _board_overlay_geometry(size)

    # Frame 0: start position
    frames.append(chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS))

    board = game.board()
    for ply_i, move in enumerate(moves_played, start=1):
        abs_ply = ply_i + start_ply_offset
        move_row = sf_by_ply.get(abs_ply) or sf_by_ply.get(ply_i)
        san_list.append(board.san(move))
        is_white_move = board.turn == chess.WHITE
        board.push(move)

        sf_overlay_entries = _build_arrow_entries_for_engine(
            abs_ply=abs_ply,
            relative_ply=ply_i,
            tier_map=sf_tier_map,
            played_scores=sf_played,
            engine_key="sf",
            is_white_move=is_white_move,
        )
        lc0_overlay_entries = _build_arrow_entries_for_engine(
            abs_ply=abs_ply,
            relative_ply=ply_i,
            tier_map=lc0_tier_map,
            played_scores=lc0_played,
            engine_key="lc0",
            is_white_move=is_white_move,
        )
        if sf_overlay_entries or lc0_overlay_entries:
            arrows_by_ply[ply_i] = sf_overlay_entries + lc0_overlay_entries

        svg = chess.svg.board(
            board,
            size=size,
            lastmove=move,
            flipped=flipped,
            colors=board_colors_for_move_classification(
                move_row.classification if move_row else None
            ),
        )
        frames.append(svg)

    top_player = data.black if not flipped else data.white
    top_sym = "♟" if not flipped else "♙"
    top_side = "Black" if not flipped else "White"
    bottom_player = data.white if not flipped else data.black
    bottom_sym = "♙" if not flipped else "♟"
    bottom_side = "White" if not flipped else "Black"

    return {
        "frames": frames,
        "arrows_by_ply": arrows_by_ply,
        "san_list": san_list,
        "total_frames": len(frames),
        "top_player": top_player,
        "top_sym": top_sym,
        "top_side": top_side,
        "bottom_player": bottom_player,
        "bottom_sym": bottom_sym,
        "bottom_side": bottom_side,
        "has_sf": data.has_sf,
        "has_lc0": data.has_lc0,
        "overlay_geometry": overlay_geometry,
    }
