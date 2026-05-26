"""
Title: board_builder.py — Chess board SVG frame builder
Description:
    Generates SVG board frames for the game analysis page. Produces one plain board
    SVG per ply and a separate, explicit arrow metadata payload for client-side
    overlay rendering. It also applies move-quality colors to the played-move
    squares so the board matches the analysis palette used elsewhere in the UI.
    This keeps arrow drawing and click handling out of the serialized chess.svg
    markup and makes the browser contract easier to maintain.

    Two calling conventions are supported:
      Legacy: build_board_frames(data: GameAnalysisData, size=480, orientation=…)
        Returns the original structure with frames as SVG strings and arrows_by_ply
        as a separate dict keyed by ply.
      New:    build_board_frames(pgn=…, sf_moves=…, lc0_moves=…, orientation=…)
        Accepts SfMoveRow / Lc0MoveRow dataclasses (from services_v2).
        Returns frames["frames"] as a list indexed by ply where each entry is a
        dict {svg, arrows: [{engine, uci, tier, label, color, opacity, stroke_width}]}.

Changelog:
    2026-05-26 (#209): _arrow_label drops engine prefix; SF arg is now mover-frame
                       cp delta (not absolute eval). Added _wdl_mu and
                       _lc0_candidate_delta_mu so LC0 arrows get per-candidate
                       Win% deltas. _arrow_entries_from_row emits color, opacity,
                       stroke_width on every arrow. (Task 2 + Task 2.5.)
    2026-05-21 (#186): Added new pgn/sf_moves/lc0_moves keyword-based entry point;
                       fixed ply-association bug — arrows now keyed by row.ply
                       instead of positional index; _build_tier_map and
                       _build_arrow_entries_for_engine updated to read arrow_uci_1
                       for new dataclasses (arrow_uci for legacy MoveRow);
                       added _arrow_label() and label field on v2 arrow entries.
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


def _build_tier_map(by_ply: dict, use_cp_equiv: bool) -> dict[int, list]:
    """
    Build a ply-indexed map of arrow tier entries for one engine's analysis.

    Supports both legacy MoveRow (arrow_uci attribute) and new SfMoveRow /
    Lc0MoveRow dataclasses (arrow_uci_1 attribute).

    Params:
        by_ply (dict): Mapping of ply number → row object from the engine.
        use_cp_equiv (bool): If True, allow cp_equiv to backfill the first score
            when the engine did not store a primary arrow score (legacy MoveRow only).

    Returns:
        Dict mapping ply → list of {uci, score} dicts for arrow rendering.
    """
    result: dict[int, list] = {}
    for ply, row in by_ply.items():
        entries = []
        # New dataclasses use arrow_uci_1; legacy MoveRow uses arrow_uci.
        primary_uci = row.arrow_uci_1 if hasattr(row, "arrow_uci_1") else row.arrow_uci
        ucis = [primary_uci, row.arrow_uci_2, row.arrow_uci_3]
        # White-frame candidate centipawns (#197). Converted to the mover frame
        # at the comparison site in _build_arrow_entries_for_engine.
        scores = [row.arrow_cp_1, row.arrow_cp_2, row.arrow_cp_3]
        if use_cp_equiv and scores[0] is None and hasattr(row, "cp_equiv"):
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


def _compute_arrow_delta(
    score: float | None,
    tier_index: int,
    played_mover: float | None,
    top_score: float | None,
) -> float | None:
    """
    Compute the improvement delta for a single arrow candidate.

    Returns the delta vs the played move for tier-1 arrows, or vs the top
    suggestion for lower-tier arrows. Returns None when scores are unavailable.

    Params:
        score       (float | None): Candidate move score.
        tier_index  (int):          Zero-based tier index (0 = top suggestion).
        played_mover(float | None): Mover-relative score of the move that was played.
        top_score   (float | None): Score of the top suggestion.

    Returns:
        float | None: Improvement delta, or None if unavailable.
    """
    if score is None:
        return None
    if played_mover is not None:
        return float(score) - played_mover
    if tier_index > 0 and top_score is not None:
        return float(score) - float(top_score)
    return None


def _build_single_arrow_entry(
    engine_key: str,
    engine_label: str,
    base_color: str,
    tier_index: int,
    relative_ply: int,
    move_uci: str,
    delta: float | None,
) -> dict:
    """
    Build one overlay-arrow metadata dict for the client renderer.

    Params:
        engine_key   (str):         "sf" or "lc0".
        engine_label (str):         Human-readable label ("Stockfish" or "Lc0").
        base_color   (str):         Hex colour for the engine.
        tier_index   (int):         Zero-based rank of this arrow.
        relative_ply (int):         One-based ply within the rendered game.
        move_uci     (str):         UCI move string (at least 4 chars).
        delta        (float | None): Improvement over played move or top suggestion.

    Returns:
        dict with keys engine, engine_label, tier, request_ply, move_uci,
        from_sq, to_sq, color, opacity, stroke_width, delta, delta_text, title.
    """
    delta_text = _format_arrow_delta(engine_key, delta)
    tooltip = f"{engine_label} #{tier_index + 1}: {move_uci}"
    if delta_text:
        tooltip += f" ({delta_text})"
    return {
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
    }


_ENGINE_LABELS: dict[str, str] = {"sf": "Stockfish", "lc0": "Lc0"}


def _resolve_tier_entries(tier_map: dict[int, list], abs_ply: int, relative_ply: int) -> list:
    """
    Look up tier entries for a ply, trying abs_ply first then relative_ply.

    Params:
        tier_map     (dict): Ply → tier-entry list mapping.
        abs_ply      (int):  Absolute ply in the source game.
        relative_ply (int):  One-based ply within the rendered frames.

    Returns:
        list: Tier entries (may be empty).
    """
    entries = tier_map.get(abs_ply)
    if entries is None:
        entries = tier_map.get(relative_ply)
    return entries or []


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
    if not tier_map:
        return []

    tier_entries = _resolve_tier_entries(tier_map, abs_ply, relative_ply)
    if not tier_entries:
        return []

    base_color = _ENGINE_BASE_COLORS[engine_key]
    played_score = played_scores.get(abs_ply) or played_scores.get(relative_ply)
    played_mover = _mover_relative_score(played_score, is_white_move)
    # Candidate cps are White-frame (#197); convert to the mover frame so deltas
    # against the (mover-frame) played score are sign-correct for Black moves.
    top_score = _mover_relative_score(tier_entries[0].get("score"), is_white_move)
    engine_label = _ENGINE_LABELS[engine_key]
    overlay_entries: list[dict] = []

    for tier_index, entry in enumerate(tier_entries):
        move_uci = entry.get("uci", "")
        if len(move_uci) >= 4:
            cand_score = _mover_relative_score(entry.get("score"), is_white_move)
            delta = _compute_arrow_delta(cand_score, tier_index, played_mover, top_score)
            overlay_entries.append(
                _build_single_arrow_entry(
                    engine_key, engine_label, base_color, tier_index, relative_ply, move_uci, delta,
                )
            )

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
        has_sf, has_lc0.
    """
    flipped = orientation == "black"
    game = chess.pgn.read_game(io.StringIO(pgn))
    overlay_geometry = _board_overlay_geometry(size)

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


def _player_layout(data: GameAnalysisData, flipped: bool) -> dict:
    """
    Build the player-label fields for the legacy return dict.

    Params:
        data    (GameAnalysisData): Game data with white/black player names.
        flipped (bool):             True when board is shown from Black's perspective.

    Returns:
        Dict with top_player, top_sym, top_side, bottom_player, bottom_sym,
        bottom_side keys.
    """
    return {
        "top_player":    data.black if not flipped else data.white,
        "top_sym":       "♟" if not flipped else "♙",
        "top_side":      "Black" if not flipped else "White",
        "bottom_player": data.white if not flipped else data.black,
        "bottom_sym":    "♙" if not flipped else "♟",
        "bottom_side":   "White" if not flipped else "Black",
    }


def _legacy_tier_context(data: GameAnalysisData) -> tuple:
    """
    Build tier maps and played-score dicts from a legacy GameAnalysisData.

    Params:
        data (GameAnalysisData): Assembled game analysis with MoveRow lists.

    Returns:
        Tuple of (sf_by_ply, lc0_by_ply, sf_tier_map, lc0_tier_map,
                  sf_played, lc0_played).
    """
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
    return sf_by_ply, lc0_by_ply, sf_tier_map, lc0_tier_map, sf_played, lc0_played


def _legacy_frame_loop(
    game: chess.pgn.Game,
    sf_by_ply: dict,
    sf_tier_map: dict | None,
    lc0_tier_map: dict | None,
    sf_played: dict,
    lc0_played: dict,
    size: int,
    flipped: bool,
    start_ply_offset: int,
) -> tuple:
    """
    Walk game moves and build SVG frames + arrows for the legacy path.

    Params:
        game              (chess.pgn.Game): Parsed game object.
        sf_by_ply         (dict):           SF rows keyed by ply.
        sf_tier_map       (dict | None):    SF arrow tiers.
        lc0_tier_map      (dict | None):    LC0 arrow tiers.
        sf_played         (dict):           SF played-move scores.
        lc0_played        (dict):           LC0 played-move scores.
        size              (int):            Board SVG pixel size.
        flipped           (bool):           True for Black's perspective.
        start_ply_offset  (int):            First ply offset of the game.

    Returns:
        Tuple of (frames: list[str], san_list: list[str],
                  arrows_by_ply: dict[int, list]).
    """
    board = game.board()
    moves_played = list(game.mainline_moves())
    san_list: list[str] = []
    arrows_by_ply: dict[int, list] = {}
    frames: list[str] = [chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS)]

    for ply_i, move in enumerate(moves_played, start=1):
        abs_ply = ply_i + start_ply_offset
        move_row = sf_by_ply.get(abs_ply) or sf_by_ply.get(ply_i)
        san_list.append(board.san(move))
        is_white_move = board.turn == chess.WHITE
        board.push(move)

        sf_entries = _build_arrow_entries_for_engine(
            abs_ply=abs_ply, relative_ply=ply_i, tier_map=sf_tier_map,
            played_scores=sf_played, engine_key="sf", is_white_move=is_white_move,
        )
        lc0_entries = _build_arrow_entries_for_engine(
            abs_ply=abs_ply, relative_ply=ply_i, tier_map=lc0_tier_map,
            played_scores=lc0_played, engine_key="lc0", is_white_move=is_white_move,
        )
        if sf_entries or lc0_entries:
            arrows_by_ply[ply_i] = sf_entries + lc0_entries

        frames.append(chess.svg.board(
            board, size=size, lastmove=move, flipped=flipped,
            colors=board_colors_for_move_classification(
                move_row.classification if move_row else None
            ),
        ))

    return frames, san_list, arrows_by_ply


def _build_frames_legacy(data: GameAnalysisData, size: int, orientation: str) -> dict:
    """
    Build board frames using the legacy GameAnalysisData / MoveRow contract.

    Produces SVG strings (not dicts) in frames[], and arrows_by_ply as a
    separate top-level key.  This is the shape that views.py::board_partial
    currently consumes.

    Params:
        data        (GameAnalysisData): Assembled game analysis.
        size        (int):              Board SVG size in pixels.
        orientation (str):              "white" or "black".

    Returns:
        dict with frames (list[str]), arrows_by_ply, san_list, total_frames,
        top_player / bottom_player layout keys, has_sf, has_lc0,
        overlay_geometry.
    """
    flipped = orientation == "black"
    game = chess.pgn.read_game(io.StringIO(data.pgn))
    overlay_geometry = _board_overlay_geometry(size)
    layout = _player_layout(data, flipped)

    if game is None:
        board = chess.Board()
        start_svg = chess.svg.board(board, size=size, flipped=flipped, colors=_BOARD_COLORS)
        return {
            "frames": [start_svg], "arrows_by_ply": {}, "san_list": [],
            "total_frames": 1, "has_sf": data.has_sf, "has_lc0": data.has_lc0,
            "overlay_geometry": overlay_geometry, **layout,
        }

    sf_by_ply, _, sf_tier_map, lc0_tier_map, sf_played, lc0_played = _legacy_tier_context(data)
    start_ply_offset = game.board().ply()
    frames, san_list, arrows_by_ply = _legacy_frame_loop(
        game, sf_by_ply, sf_tier_map, lc0_tier_map, sf_played, lc0_played,
        size, flipped, start_ply_offset,
    )

    return {
        "frames": frames, "arrows_by_ply": arrows_by_ply, "san_list": san_list,
        "total_frames": len(frames), "has_sf": data.has_sf, "has_lc0": data.has_lc0,
        "overlay_geometry": overlay_geometry, **layout,
    }


def build_board_frames(
    data: GameAnalysisData | None = None,
    size: int = 480,
    orientation: str = "white",
    *,
    pgn: str | None = None,
    sf_moves: list | None = None,
    lc0_moves: list | None = None,
) -> dict:
    """
    Generate all SVG board frames for a game and return structured data for
    template rendering.

    Supports two calling conventions:

    Legacy (existing views):
        build_board_frames(data, size=480, orientation="white")
        data must be a GameAnalysisData instance.
        Returns the original dict with frames as SVG strings and a separate
        arrows_by_ply dict keyed by ply.

    New (services_v2 dataclasses):
        build_board_frames(pgn=…, sf_moves=…, lc0_moves=…, orientation="white")
        sf_moves / lc0_moves are SfMoveRow / Lc0MoveRow lists (may be empty/None).
        Returns a dict where frames["frames"] is a list indexed by ply (0 = start),
        each entry being a dict {svg, arrows: [{engine, uci, tier}]}.

    Params:
        data        (GameAnalysisData | None): Legacy assembled game analysis.
        size        (int):  Board SVG size in pixels (default 480).
        orientation (str):  "white" or "black" perspective.
        pgn         (str):  PGN text — triggers new calling convention.
        sf_moves    (list): SfMoveRow list for new convention.
        lc0_moves   (list): Lc0MoveRow list for new convention.

    Returns:
        Legacy path: dict with frames (list[str]), arrows_by_ply, san_list,
            total_frames, top_player/bottom_player, has_sf, has_lc0,
            overlay_geometry.
        New path: dict with frames (list[dict]), san_list, total_frames,
            overlay_geometry, has_sf, has_lc0.
    """
    if pgn is not None:
        return _build_frames_v2(
            pgn=pgn, sf_moves=sf_moves or [], lc0_moves=lc0_moves or [],
            size=size, orientation=orientation,
        )
    if data is None:
        raise ValueError("build_board_frames requires either data or pgn=")
    return _build_frames_legacy(data, size, orientation)
