"""
Title: stockfish.py — Stockfish derivation orchestrator (#161 Phase E)
Description:
    Public surface for Stockfish derivation. Ports the CPL-based band ladder
    + top-tier (Brilliant/Great/Best) resolver from
    ``local_worker.analysis.math`` verbatim — thresholds and label vocabulary
    come from ``derivation.thresholds`` so a retune is a one-file edit.

    Pipeline for one raw payload:
      1. Walk moves in ply order, chaining each move's ``cp_eval`` (white-frame
         post-move) into the next move's "before" eval.
      2. Per move: derive CPL via ``_frame.cpl_from_white_cp``; compute
         mover-frame ``move_win_delta`` from sigmoid Win%; classify via
         ``classify_sf_move``.
      3. Aggregate per-side accuracy (via ``accuracy.game_accuracy``), ACPL,
         and severity counters.

    Limitations of the Phase E scope:
      * ``second_best_gap`` is derived from raw mover-frame Win% candidates
        in the payload (``arrow_score_1/2/3``) and converted to a cp-equivalent
        gap via the inverse Lichess sigmoid. When fewer than two candidates
        are present, ``second_best_gap`` is ``None`` and the top-tier resolver
        falls through to ``"Best"`` — same behaviour the worker exhibits
        today on MultiPV<2.
      * SEE-based capture/sacrifice detection is not part of the raw contract
        (boards are reconstructed app-side), so ``is_capture_or_sacrifice`` is
        ``False`` for now and Brilliant is unreachable. Surfacing SEE is a
        follow-up — left intentional for Phase E's scope.

Changelog:
    2026-05-19 (#161/C): Stub.
    2026-05-19 (#161/E): Math ported; orchestrator + golden vectors landed.
    2026-05-21 (#188/B): raw SF WDL triples + NPV pass through derive_sf_game
        unchanged. Phase C will switch the accuracy/classification math to
        feed off wdl_mu derived from these triples.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from analysis.derivation import thresholds
from analysis.derivation._frame import cpl_from_white_cp, is_white_ply
from analysis.derivation.accuracy import (
    game_accuracy,
    move_accuracy,
    win_pct,
)
from analysis.derivation.counters import count_severities

__all__ = [
    "MATE_SCORE",
    "classify_sf_move",
    "cpl",
    "derive_sf_game",
]

# Mate scores are flattened to ±MATE_SCORE in cp before entering the band
# ladder; the sigmoid saturates near 0/100, so finer mate distance does not
# change classification.
MATE_SCORE = 10000

# Inverse Lichess sigmoid: cp(p) = -ln(100/p - 1) / k. Used solely to turn an
# arrow-score Win% gap into the cp-equivalent gap that the classifier wants.
_WIN_PCT_K = 0.00368208


def cpl(
    *, before_white: int, after_white: int, mover_is_white: bool,
) -> int:
    """Centipawn loss in the mover's frame, clamped to non-negative.

    Thin re-export of ``_frame.cpl_from_white_cp`` under the engine-named
    spelling so consumers (Phase G serializer, Phase F migration) can import
    from one module.

    Args:
        before_white: White-frame cp eval *before* the move.
        after_white: White-frame cp eval *after* the move.
        mover_is_white: True iff the side that just moved is White.

    Returns:
        Non-negative integer CPL.
    """
    return cpl_from_white_cp(
        before_white=before_white,
        after_white=after_white,
        mover_is_white=mover_is_white,
    )


def _resolve_top_tier(
    *,
    second_best_gap: Optional[float],
    mover_win_pct: float,
    is_capture_or_sacrifice: bool,
) -> str:
    """Brilliant / Great / Best resolver for a move in the top quality bucket.

    Args:
        second_best_gap: cp gap between best and second-best legal moves
            (None when MultiPV<2). Phase E supplies a sigmoid-derived gap
            from the raw arrow-score Win% pair.
        mover_win_pct: Mover-frame Win% before the move.
        is_capture_or_sacrifice: SEE result; Phase E always supplies False.

    Returns:
        ``"Brilliant"``, ``"Great"``, or ``"Best"``.
    """
    if second_best_gap is None:
        return "Best"
    if (
        second_best_gap >= thresholds.SF_BRILLIANT_GAP
        and mover_win_pct < thresholds.SF_BRILLIANT_WINPCT_CEILING
        and is_capture_or_sacrifice
    ):
        return "Brilliant"
    if second_best_gap >= thresholds.SF_GREAT_GAP:
        return "Great"
    return "Best"


def classify_sf_move(
    *,
    cpl_mover: int,
    second_best_gap: Optional[float],
    mover_win_pct: float,
    is_capture_or_sacrifice: bool,
) -> str:
    """Classify a Stockfish move per the band ladder (verbatim from worker math).

    Order (first match wins): Brilliant → Great → Best → Excellent →
    Inaccuracy → Mistake → Blunder. Thresholds live in
    ``derivation.thresholds``; bumping them retunes every later analysis.

    Args:
        cpl_mover: Non-negative centipawn loss in the mover's frame.
        second_best_gap: cp gap between best and second-best legal move
            (None when MultiPV<2 or unavailable).
        mover_win_pct: Mover-frame Win% before the move (0-100).
        is_capture_or_sacrifice: SEE-derived flag; True only for
            negative-SEE captures.

    Returns:
        One of the labels in ``thresholds.SEVERITY_LABELS``.
    """
    if cpl_mover < thresholds.SF_EXCELLENT_CPL:
        return _resolve_top_tier(
            second_best_gap=second_best_gap,
            mover_win_pct=mover_win_pct,
            is_capture_or_sacrifice=is_capture_or_sacrifice,
        )
    if cpl_mover < thresholds.SF_INACCURACY_CPL:
        return "Excellent"
    if cpl_mover < thresholds.SF_MISTAKE_CPL:
        return "Inaccuracy"
    if cpl_mover < thresholds.SF_BLUNDER_CPL:
        return "Mistake"
    return "Blunder"


def _cp_from_win_pct(pct: float) -> float:
    """Invert the Lichess sigmoid: recover cp from a Win% in (0, 100).

    Used only to convert the raw arrow-score Win% gap (mover-frame) into the
    cp gap the band ladder expects. Saturated inputs (≤0 / ≥100) return
    ±MATE_SCORE so the inverse never explodes.

    Args:
        pct: Mover-frame Win% in [0, 100].

    Returns:
        Mover-frame cp value (signed). Saturation returns ±MATE_SCORE.
    """
    if pct <= 0.0:
        return -float(MATE_SCORE)
    if pct >= 100.0:
        return float(MATE_SCORE)
    # cp = -ln(100/p - 1) / k. p in (0, 100); k = sigmoid coefficient.
    return -math.log(100.0 / pct - 1.0) / _WIN_PCT_K


def _gap_from_arrow_scores(
    arrow_score_1: Optional[float], arrow_score_2: Optional[float],
) -> Optional[float]:
    """Compute a cp-equivalent ``second_best_gap`` from two arrow scores.

    Args:
        arrow_score_1: Mover-frame Win% for the top candidate.
        arrow_score_2: Mover-frame Win% for the second candidate.

    Returns:
        Non-negative cp gap between the two, or None when either is missing.
    """
    if arrow_score_1 is None or arrow_score_2 is None:
        return None
    cp_1 = _cp_from_win_pct(float(arrow_score_1))
    cp_2 = _cp_from_win_pct(float(arrow_score_2))
    return max(0.0, cp_1 - cp_2)


def _saturated_cp(cp_eval: Optional[int], mate_in: Optional[int]) -> int:
    """Resolve the displayed cp for a move, flattening mate distance.

    The new SF raw contract carries ``cp_eval`` (always present, white-frame)
    *and* ``mate_in`` (signed mate distance or null). When ``mate_in`` is
    populated we override cp with ±MATE_SCORE so the sigmoid saturates
    correctly — matching what the worker does today.

    Args:
        cp_eval: White-frame cp evaluation, post-move.
        mate_in: Signed mate distance (positive = White mates), or None.

    Returns:
        Saturated white-frame cp value.
    """
    if mate_in is not None and mate_in != 0:
        return MATE_SCORE if mate_in > 0 else -MATE_SCORE
    return int(cp_eval or 0)


def _derive_one_move(
    move: dict,
    *,
    before_white: int,
) -> dict:
    """Compute every derived field for one raw Stockfish move entry.

    Args:
        move: One element of ``raw_payload["moves"]`` (#161 SF raw contract).
        before_white: White-frame cp eval of the position *before* this move
            (i.e. the previous ply's ``cp_eval``, or starting eval at ply 1).

    Returns:
        Dict carrying raw fields verbatim plus all derived fields.
    """
    ply = int(move["ply"])
    mover_is_white = is_white_ply(ply)
    cp_after_white = _saturated_cp(move.get("cp_eval"), move.get("mate_in"))

    cpl_mover = cpl(
        before_white=before_white, after_white=cp_after_white,
        mover_is_white=mover_is_white,
    )

    # Win% in the mover's frame: convert the white-frame eval first.
    mover_cp_before = before_white if mover_is_white else -before_white
    mover_cp_after = cp_after_white if mover_is_white else -cp_after_white
    win_pct_before_mover = win_pct(mover_cp_before)
    win_pct_after_mover = win_pct(mover_cp_after)
    move_win_delta_mover = win_pct_before_mover - win_pct_after_mover
    move_acc = move_accuracy(win_pct_before_mover, win_pct_after_mover)

    gap = _gap_from_arrow_scores(
        move.get("arrow_score_1"), move.get("arrow_score_2"),
    )
    classification = classify_sf_move(
        cpl_mover=cpl_mover,
        second_best_gap=gap,
        mover_win_pct=win_pct_before_mover,
        is_capture_or_sacrifice=False,  # SEE deferred — see module docstring.
    )

    return {
        # Raw passthrough.
        "ply": ply,
        "san": move["san"],
        "fen": move["fen"],
        "cp_eval": int(move["cp_eval"]) if move.get("cp_eval") is not None else 0,
        "mate_in": move.get("mate_in"),
        "arrow_uci_1": move.get("arrow_uci_1") or "",
        "arrow_uci_2": move.get("arrow_uci_2"),
        "arrow_uci_3": move.get("arrow_uci_3"),
        "arrow_score_1": move.get("arrow_score_1"),
        "arrow_score_2": move.get("arrow_score_2"),
        "arrow_score_3": move.get("arrow_score_3"),
        "pv_san_1": move.get("pv_san_1"),
        "pv_san_2": move.get("pv_san_2"),
        "pv_san_3": move.get("pv_san_3"),
        # #188 Phase B: raw WDL passthrough. Phase C populates _adj from these.
        "wdl_win": move.get("wdl_win"),
        "wdl_draw": move.get("wdl_draw"),
        "wdl_loss": move.get("wdl_loss"),
        "wdl_win_1": move.get("wdl_win_1"),
        "wdl_draw_1": move.get("wdl_draw_1"),
        "wdl_loss_1": move.get("wdl_loss_1"),
        "wdl_win_2": move.get("wdl_win_2"),
        "wdl_draw_2": move.get("wdl_draw_2"),
        "wdl_loss_2": move.get("wdl_loss_2"),
        "wdl_win_3": move.get("wdl_win_3"),
        "wdl_draw_3": move.get("wdl_draw_3"),
        "wdl_loss_3": move.get("wdl_loss_3"),
        # Phase B leaves _adj null; Phase C populates as frame-mirror identity.
        "wdl_win_adj": None,
        "wdl_draw_adj": None,
        "wdl_loss_adj": None,
        # Derived.
        "cpl": cpl_mover,
        "move_win_delta": move_win_delta_mover,
        "classification": classification,
        "best_move": move.get("arrow_uci_1") or "",
        # Walking state (stripped by ``derive_sf_game``).
        "_cp_after_white": cp_after_white,
        "_move_acc": move_acc,
        "_win_pct_after_white": win_pct(cp_after_white),
    }


def _initial_win_pct_white() -> float:
    """Win% of the initial position from White's frame (0 cp → 50%)."""
    return win_pct(0)


def _build_game_aggregates(
    derived_moves: list[dict],
    all_win_pcts: list[float],
) -> dict:
    """Compute per-side accuracy / ACPL / counters for the game-level dict.

    Args:
        derived_moves: Output of ``_derive_one_move`` for every move, in order.
        all_win_pcts: White-frame Win% sequence of length ``num_plies + 1``.

    Returns:
        Dict with the eight game-level derived fields plus six counter fields.
    """
    white_accs: list[float] = []
    black_accs: list[float] = []
    white_cpls: list[int] = []
    black_cpls: list[int] = []
    white_idx: list[int] = []
    black_idx: list[int] = []
    for move in derived_moves:
        if is_white_ply(move["ply"]):
            white_accs.append(move["_move_acc"])
            white_cpls.append(move["cpl"])
            white_idx.append(move["ply"])
        else:
            black_accs.append(move["_move_acc"])
            black_cpls.append(move["cpl"])
            black_idx.append(move["ply"])
    counters = count_severities(
        (m["ply"], m["classification"]) for m in derived_moves
    )

    def _avg(nums: list[int]) -> float:
        return float(sum(nums)) / len(nums) if nums else 0.0

    return {
        "white_accuracy": game_accuracy(
            white_accs, all_win_pcts=all_win_pcts, mover_ply_indices=white_idx,
        ),
        "black_accuracy": game_accuracy(
            black_accs, all_win_pcts=all_win_pcts, mover_ply_indices=black_idx,
        ),
        "white_acpl": _avg(white_cpls),
        "black_acpl": _avg(black_cpls),
        "white_blunders": counters.white_blunders,
        "white_mistakes": counters.white_mistakes,
        "white_inaccuracies": counters.white_inaccuracies,
        "black_blunders": counters.black_blunders,
        "black_mistakes": counters.black_mistakes,
        "black_inaccuracies": counters.black_inaccuracies,
    }


def derive_sf_game(raw_payload: dict, game: Any) -> dict:  # noqa: ARG001
    """Derive every Stockfish-analysis field from a validated raw payload.

    Args:
        raw_payload: Dict matching the #161 raw Stockfish contract (worker_id,
            engine_depth, engine_name, moves[]).
        game: ``games.Game`` instance; reserved for future Elo-aware
            adjustments (ignored by Phase E).

    Returns:
        Dict shaped for ``GameAnalysis`` model creation, with a nested
        ``moves`` list shaped for ``MoveAnalysis``. Walking-state keys
        (those prefixed with ``_``) are stripped before return.
    """
    derived_moves: list[dict] = []
    # The first move's "before" eval is the starting position (0 cp).
    before_white = 0
    all_win_pcts_white: list[float] = [_initial_win_pct_white()]
    for move in raw_payload["moves"]:
        result = _derive_one_move(move, before_white=before_white)
        before_white = result.pop("_cp_after_white")
        move_acc = result.pop("_move_acc")
        win_pct_after_white = result.pop("_win_pct_after_white")
        all_win_pcts_white.append(win_pct_after_white)
        result["_move_acc"] = move_acc  # restored for the aggregator
        derived_moves.append(result)
    aggregates = _build_game_aggregates(derived_moves, all_win_pcts_white)
    for move in derived_moves:
        move.pop("_move_acc", None)
    return {
        "engine_depth": int(raw_payload["engine_depth"]),
        "summary_cp": before_white,  # White-frame cp of the terminal position.
        # #188 Phase B: pass NPV through for persistence; nullable for older SF builds.
        "normalize_to_pawn_value": raw_payload.get("normalize_to_pawn_value"),
        **aggregates,
        "moves": derived_moves,
    }
