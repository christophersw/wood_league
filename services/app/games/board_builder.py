"""
Title: board_builder.py — Chess board SVG frame builder
Description:
    Generates SVG board frames for the game analysis page. Produces one plain board
    SVG per ply and a separate, explicit arrow metadata payload for client-side
    overlay rendering. It also applies move-quality colors to the played-move
    squares so the board matches the analysis palette used elsewhere in the UI.
    This keeps arrow drawing and click handling out of the serialized chess.svg
    markup and makes the browser contract easier to maintain.

    Single calling convention (v2 only):
      build_board_frames(pgn=…, sf_moves=…, lc0_moves=…, orientation=…)
        Accepts SfMoveRow / Lc0MoveRow dataclasses (from services_v2).
        Returns frames["frames"] as a list indexed by ply where each entry is a
        dict {svg, arrows: [{engine, uci, tier, label, color, opacity, stroke_width}]}.
    The legacy positional GameAnalysisData overload was retired in #209 (Task 10).

Changelog:
    2026-05-26 (#209): Task 10 — deleted legacy build_board_frames branch and all
                       helpers exclusive to it: _build_tier_map,
                       _build_arrow_entries_for_engine, _resolve_tier_entries,
                       _legacy_tier_context, _legacy_frame_loop, _build_frames_legacy,
                       _build_single_arrow_entry, _format_arrow_delta,
                       _compute_arrow_delta, _player_layout. Also dropped the
                       _UNIFORM_ARROW_STROKE_WIDTH and _ENGINE_LABELS module constants
                       and the dead ``from games.services import GameAnalysisData,
                       MoveRow`` import. build_board_frames is now a single
                       keyword-only-options entry point; passing a non-str first arg
                       raises TypeError immediately.
    2026-05-26 (#209): Task 7 atomic cutover — _v2_player_layout now emits the
                       same flat-key contract as legacy _player_layout
                       (top_player/top_sym/top_side/bottom_*). _build_frames_v2
                       spreads those keys directly instead of nesting under
                       player_layout.
    2026-05-26 (#210): Reverted Task 7 flat-key spread: _build_frames_v2 now
                       returns player_layout as a nested dict (Option C) so the
                       runtime shape matches the spec contract. Downstream
                       consumers (views.py board_partial) read from
                       player_layout.top_* / player_layout.bottom_*.
    2026-05-26 (#209): _arrow_label drops engine prefix; SF arg is now mover-frame
                       cp delta (not absolute eval). Added _wdl_mu and
                       _lc0_candidate_delta_mu so LC0 arrows get per-candidate
                       Win% deltas. _arrow_entries_from_row emits color, opacity,
                       stroke_width on every arrow. (Task 2 + Task 2.5.)
    2026-05-21 (#186): Added new pgn/sf_moves/lc0_moves keyword-based entry point;
                       fixed ply-association bug — arrows now keyed by row.ply
                       instead of positional index; added _arrow_label() and label
                       field on v2 arrow entries.
    2026-05-05 (#16): Exposed reusable move-quality board colors for main and
                      engine-line board highlights
    2026-05-05 (#16): Applied move-quality colors to main-board move squares
    2026-05-05 (#16): Replaced brittle SVG arrow mutation with explicit overlay
                      metadata for stable client-side rendering and interaction
    2026-05-04 (#16): Rewrote to return frame data dict instead of HTML blob.
    2025-xx-xx:       Initial implementation with build_board_viewer_html.
"""

from __future__ import annotations

import io

import chess
import chess.pgn
import chess.svg

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
_MAX_SHADE_DELTA = 220.0


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


def _v2_player_layout(pgn: str, orientation: str) -> dict:
    """
    Compute the top/bottom-side player layout for a v2 board render.

    Reads the PGN headers White / Black for names (None if absent) and decides
    which side sits on top vs. bottom based on the requested orientation.
    Unicode pieces: ♟ for the side at the top (far from viewer), ♙ for the
    side at the bottom (near viewer).

    Params:
        pgn (str):         The PGN string (may be empty).
        orientation (str): "white" or "black".

    Returns:
        Dict with keys:
            top_player, bottom_player: str | None — name from PGN header.
            top_sym, bottom_sym:       str — unicode chess piece for that side.
            top_side, bottom_side:     "White" | "Black" — side label.
    """
    game = chess.pgn.read_game(io.StringIO(pgn or ""))
    white_name = game.headers.get("White") if game is not None else None
    black_name = game.headers.get("Black") if game is not None else None
    flipped = orientation == "black"
    return {
        "top_player":    black_name if not flipped else white_name,
        "top_sym":       "♟" if not flipped else "♙",
        "top_side":      "Black" if not flipped else "White",
        "bottom_player": white_name if not flipped else black_name,
        "bottom_sym":    "♙" if not flipped else "♟",
        "bottom_side":   "White" if not flipped else "Black",
    }


def _build_frames_v2(
    pgn: str,
    sf_moves: list,
    lc0_moves: list,
    size: int,
    orientation: str,
) -> dict:
    """
    Build board frames using the new SfMoveRow / Lc0MoveRow dataclasses.

    Fixes the ply-association bug: analysis rows are keyed by row.ply and
    looked up after each board.push() using board.ply(), so a LC0 set that
    starts at ply 3 never bleeds its arrows into ply 1 or ply 2.

    Returns a dict where frames["frames"] is a list indexed by ply (0 = start).
    Each entry is a self-contained dict with keys:
        svg            (str):       Board SVG for this ply's position.
        arrows         (list[dict]): Engine arrow suggestions.
        ply            (int):       0-based ply index.
        san            (str|None):  SAN move that reached this ply (None for ply 0).
        last_move_uci  (str|None):  UCI move that reached this ply (None for ply 0).
        classification (str|None):  SF move classification or None.
    The arrows list contains one entry per suggested engine move with keys:
        engine (str): "sf" or "lc0"
        uci    (str): UCI move string for the suggestion (e.g. "g1f3")
        tier   (int): 1-based rank among the engine's suggestions

    Params:
        pgn      (str):  PGN text for the game.
        sf_moves (list): SfMoveRow list, may be empty.
        lc0_moves(list): Lc0MoveRow list, may be empty.
        size     (int):  Board SVG pixel size.
        orientation (str): "white" or "black".

    Returns:
        dict with keys: frames, san_list, total_frames, overlay_geometry,
        player_layout (nested dict with top_player/top_sym/top_side/bottom_*),
        has_sf, has_lc0.
    """
    flipped = orientation == "black"
    game = chess.pgn.read_game(io.StringIO(pgn))
    overlay_geometry = _board_overlay_geometry(size)
    player_keys = _v2_player_layout(pgn, orientation)

    if game is None:
        board = chess.Board()
        start_svg = chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS)
        return {
            "frames": [{
                "svg": start_svg,
                "arrows": [],
                "ply": 0,
                "san": None,
                "last_move_uci": None,
                "classification": None,
            }],
            "san_list": [],
            "total_frames": 1,
            "overlay_geometry": overlay_geometry,
            "player_layout": player_keys,
            "has_sf": bool(sf_moves),
            "has_lc0": bool(lc0_moves),
        }

    # Index rows by ply for O(1) lookup — this is the ply-alignment fix.
    sf_by_ply: dict[int, object] = {row.ply: row for row in (sf_moves or [])}
    lc0_by_ply: dict[int, object] = {row.ply: row for row in (lc0_moves or [])}

    board = game.board()
    moves_played: list[chess.Move] = list(game.mainline_moves())

    # Frame 0 — start position, no arrows (no move has been played yet).
    start_svg = chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS)
    frames: list[dict] = [{
        "svg": start_svg,
        "arrows": [],
        "ply": 0,
        "san": None,
        "last_move_uci": None,
        "classification": None,
    }]
    san_list: list[str] = []

    for move in moves_played:
        san_str = board.san(move)
        san_list.append(san_str)
        uci_str = move.uci()
        is_white_move = board.turn == chess.WHITE
        board.push(move)
        current_ply = board.ply()

        sf_row = sf_by_ply.get(current_ply)
        lc0_row = lc0_by_ply.get(current_ply)

        arrows: list[dict] = []
        if sf_row is not None:
            arrows.extend(_arrow_entries_from_row("sf", sf_row, is_white_move))
        if lc0_row is not None:
            arrows.extend(_arrow_entries_from_row("lc0", lc0_row, is_white_move))

        sf_classification = getattr(sf_row, "classification", None)
        svg = chess.svg.board(
            board,
            size=size,
            lastmove=move,
            flipped=flipped,
            colors=board_colors_for_move_classification(sf_classification),
        )
        frames.append({
            "svg": svg,
            "arrows": arrows,
            "ply": current_ply,
            "san": san_str,
            "last_move_uci": uci_str,
            "classification": sf_classification,
        })

    return {
        "frames": frames,
        "san_list": san_list,
        "total_frames": len(frames),
        "overlay_geometry": overlay_geometry,
        "player_layout": player_keys,
        "has_sf": bool(sf_by_ply),
        "has_lc0": bool(lc0_by_ply),
    }


_UNICODE_MINUS = "−"


def _arrow_label(engine_key: str, delta_cp: float | None, delta_mu: float | None) -> str:
    """
    Build a compact eval-only label for a v2-path arrow.

    The arrow tag conveys the engine by colour, so the label is eval text with no
    engine prefix: SF shows the candidate's mover-relative cp delta vs the played
    move in pawns to two decimals (e.g. "+0.34" or "−0.10"); LC0 shows the per-
    candidate Win% delta vs the played move in whole percentage points
    (e.g. "+12%" or "−7%").

    Both args carry **deltas vs the played move**, not absolute evals. Passing an
    absolute eval will format silently but mean the wrong thing — call sites must
    compute the delta first.

    Params:
        engine_key (str):          "sf" or "lc0".
        delta_cp   (float | None): For SF: the mover-relative cp delta
                                   (candidate cp − played cp) to render in pawns.
        delta_mu   (float | None): For LC0: (candidate_mu − played_mu).

    Returns:
        Formatted label string, or "" when the required value is absent.
    """
    if engine_key == "sf" and delta_cp is not None:
        pawns = delta_cp / 100.0
        sign = "+" if pawns >= 0 else _UNICODE_MINUS
        return f"{sign}{abs(pawns):.2f}"
    if engine_key == "lc0" and delta_mu is not None:
        delta_pct = delta_mu * 100.0
        sign = "+" if delta_pct >= 0 else _UNICODE_MINUS
        return f"{sign}{abs(delta_pct):.0f}%"
    return ""


def _wdl_mu(win: int | None, draw: int | None, loss: int | None) -> float | None:
    """Expected-score fraction (0..1) from a milli-unit WDL triple, or None.

    Params:
        win  (int | None): Win count (milli-units, mover frame).
        draw (int | None): Draw count (milli-units, mover frame).
        loss (int | None): Loss count (milli-units, mover frame).

    Returns:
        (win + draw/2) / (win + draw + loss), or None when any input is None or
        the total is non-positive.
    """
    if win is None or draw is None or loss is None:
        return None
    total = win + draw + loss
    if total <= 0:
        return None
    return (win + (draw / 2.0)) / total


def _lc0_candidate_delta_mu(row: object, tier: int) -> float | None:
    """Candidate-tier expected-score delta vs the played move (mover frame), or None.

    Uses the raw per-candidate WDL (``wdl_*_{tier}``) and the raw played WDL
    (``wdl_win/draw/loss``), both mover-frame, so a candidate better for the
    mover reads positive.

    Params:
        row  (object): Lc0MoveRow with raw played + per-candidate WDL triples.
        tier (int):    1, 2, or 3.

    Returns:
        candidate_mu − played_mu, or None when either is unavailable.
    """
    cand = _wdl_mu(
        getattr(row, f"wdl_win_{tier}", None),
        getattr(row, f"wdl_draw_{tier}", None),
        getattr(row, f"wdl_loss_{tier}", None),
    )
    played = _wdl_mu(
        getattr(row, "wdl_win", None),
        getattr(row, "wdl_draw", None),
        getattr(row, "wdl_loss", None),
    )
    if cand is None or played is None:
        return None
    return cand - played


def _arrow_entries_from_row(engine_key: str, row: object, is_white_move: bool) -> list[dict]:
    """
    Extract flat arrow metadata dicts from a single analysis row.

    Each arrow's ``label`` is the candidate's signed delta vs the move actually
    played, mover-relative: SF passes the mover-frame delta (candidate cp − played
    cp) to ``_arrow_label`` (not the absolute eval); LC0 uses per-candidate WDL via
    ``_lc0_candidate_delta_mu`` so each candidate gets its own label instead of the
    played-move delta_mu repeated three times.

    Each arrow also carries ``color`` (engine base hex), ``opacity`` (encoding tier
    rank and delta magnitude), and ``stroke_width`` (constant 7, matching the
    legacy default the JS still expects).

    Params:
        engine_key    (str):    "sf" or "lc0".
        row           (object): SfMoveRow or Lc0MoveRow instance.
        is_white_move (bool):   True when the mover for this ply is White.

    Returns:
        List of arrow dicts: {engine, uci, tier, label, color, opacity, stroke_width}.
    """
    ucis = [
        getattr(row, "arrow_uci_1", None),
        getattr(row, "arrow_uci_2", None),
        getattr(row, "arrow_uci_3", None),
    ]
    base_color = _ENGINE_BASE_COLORS[engine_key]
    entries: list[dict] = []

    for tier_index, uci in enumerate(ucis):
        if not (uci and len(uci) >= 4):
            continue

        # If cp/WDL inputs are missing, the arrow is still emitted (the JS draws
        # it from the UCI alone) — label and opacity just fall back to "" / None.
        if engine_key == "sf":
            cand_cp = getattr(row, f"arrow_cp_{tier_index + 1}", None)
            played_cp = getattr(row, "cp_eval", None)
            label = ""
            delta_for_opacity: float | None = None
            if cand_cp is not None and played_cp is not None:
                # arrow_cp_* and cp_eval are both white-frame (#197); flip to mover-frame
                # so the delta sign matches what the side-to-move sees.
                delta_mover = _mover_relative_score(cand_cp - played_cp, is_white_move)
                label = _arrow_label("sf", delta_mover, None)
                delta_for_opacity = delta_mover
        else:
            delta_mu = _lc0_candidate_delta_mu(row, tier_index + 1)
            label = _arrow_label("lc0", None, delta_mu)
            # Scale mu delta (0..1 unit) into cp-equivalent for opacity shading.
            delta_for_opacity = (delta_mu * 100.0) if delta_mu is not None else None

        entries.append({
            "engine": engine_key,
            "uci": uci,
            "tier": tier_index + 1,
            "label": label,
            "color": base_color,
            "opacity": _build_arrow_opacity(delta_for_opacity, tier_index),
            "stroke_width": 7,
        })
    return entries


def build_board_frames(
    pgn: str,
    sf_moves: list,
    lc0_moves: list,
    *,
    orientation: str = "white",
    size: int = 480,
) -> dict:
    """
    Render board frames + per-frame engine arrows for the analysis page.

    Single keyword-only-options signature. The legacy positional
    ``GameAnalysisData`` overload was retired in #209 (Task 10).

    Params:
        pgn (str):              Game PGN text (may be empty).
        sf_moves (list):        Stockfish move rows (SfMoveRow), indexed by ply.
        lc0_moves (list):       LC0 move rows (Lc0MoveRow), indexed by ply.
        orientation (str):      "white" (default) or "black".
        size (int):             Rendered board pixel size (default 480).

    Returns:
        dict: {frames, overlay_geometry, player_layout, has_sf, has_lc0,
               san_list, total_frames}.  player_layout is a nested dict with
               keys top_player, top_sym, top_side, bottom_player, bottom_sym,
               bottom_side.
    """
    if not isinstance(pgn, str):
        raise TypeError(
            f"build_board_frames now requires keyword args; got positional non-str pgn "
            f"({type(pgn).__name__}). Legacy GameAnalysisData signature was removed in #209."
        )
    return _build_frames_v2(pgn, sf_moves, lc0_moves, size=size, orientation=orientation)
