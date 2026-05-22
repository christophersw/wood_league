"""
Title: stockfish.py — Stockfish derivation orchestrator (#161 Phase E / #188 Phase C)
Description:
    Public surface for Stockfish derivation. Ports the CPL-based band ladder
    + top-tier (Brilliant/Great/Best) resolver from
    ``local_worker.analysis.math`` verbatim — thresholds and label vocabulary
    come from ``derivation.thresholds`` so a retune is a one-file edit.

    Pipeline for one raw payload (#188 Phase C):
      1. Walk moves in ply order, chaining two "before" channels:
           - ``before_white`` (cp) for CPL and the sigmoid fallback.
           - ``before_white_mu`` (White-frame WDL_mu) for the WDL path.
      2. Per move: derive CPL via ``_frame.cpl_from_white_cp`` (cp-based on
         both paths); then branch:
           - WDL path: mover-frame triple → White-frame via _sf_wdl_mover_to_white;
             compute mu; feed mu*100 into the Lichess accuracy curve; populate
             wdl_*_adj as the frame-mirror identity.
           - Sigmoid fallback: win_pct(cp) drives accuracy; _adj stays null.
      3. Aggregate per-side accuracy (via ``accuracy.game_accuracy``), ACPL,
         and severity counters.

    Limitations of the Phase E / Phase C scope:
      * SEE-based capture/sacrifice detection is not part of the raw contract
        (boards are reconstructed app-side), so ``is_capture_or_sacrifice`` is
        ``False`` for now and Brilliant is unreachable. Surfacing SEE is a
        follow-up — left intentional for Phase E's scope.
      * WDL path: classifier gap uses raw mu-gap × NPV × 2.
      * Sigmoid fallback only fires when the engine did not emit WDL.

Changelog:
    2026-05-19 (#161/C): Stub.
    2026-05-19 (#161/E): Math ported; orchestrator + golden vectors landed.
    2026-05-21 (#188/B): raw SF WDL triples + NPV pass through derive_sf_game
        unchanged.
    2026-05-21 (#188/C): _derive_one_move rewritten to use WDL_mu on the WDL
        path; new helpers _sf_wdl_mover_to_white, _sf_wdl_mu_white,
        _gap_from_arrow_wdl_mu added. CPL stays cp-based. Sigmoid fallback
        retained for missing-WDL builds.
"""
from __future__ import annotations

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

# Classifier gap source (#188 Phase D): the second-best gap is a native cp
# subtraction of the worker's persisted candidate centipawns (arrow_cp_*),
# via _gap_from_candidate_cp. No sigmoid/WDL reconstruction.


# ── #188 Phase C: SF native WDL math ─────────────────────────────────────
# Frame note: SF emits WDL in the side-to-move (mover) frame.  To put it in
# White's frame for a Black move, swap W↔L (draws are symmetric).


def _sf_wdl_mover_to_white(
    win: int, draw: int, loss: int, *, mover_is_white: bool,
) -> tuple[int, int, int]:
    """Rotate a mover-frame WDL triple to White's frame.

    SF emits WDL in the side-to-move frame.  For a White move, White's frame
    IS the mover's frame (identity).  For a Black move, W and L are swapped
    so the triple reflects expected score from White's perspective.

    Args:
        win: Mover-frame W in milli-units (0–1000).
        draw: Mover-frame D in milli-units (0–1000).
        loss: Mover-frame L in milli-units (0–1000).
        mover_is_white: True iff the mover at the searched position is White.

    Returns:
        (W_white, D_white, L_white) in milli-units.
    """
    if mover_is_white:
        return (win, draw, loss)
    return (loss, draw, win)


def _sf_wdl_mu_white(win: int, draw: int, loss: int) -> float:  # noqa: ARG001
    """Expected-score fraction in [0, 1] from a White-frame WDL triple.

    Computes the standard chess expected-score formula: Win + Draw/2, scaled
    to [0, 1] from milli-units.  The ``loss`` parameter is unused (included
    for a symmetric, self-documenting call site).

    Args:
        win: White-frame W in milli-units.
        draw: White-frame D in milli-units.
        loss: White-frame L in milli-units (unused; kept for symmetric call).

    Returns:
        ``(W + D/2) / 1000``, a float in [0.0, 1.0].
    """
    return (win + draw / 2.0) / 1000.0


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


def _gap_from_candidate_cp(
    arrow_cp_1: Optional[float],
    arrow_cp_2: Optional[float],
    *,
    mover_is_white: bool,
) -> Optional[float]:
    """Native cp ``second_best_gap`` from the top-2 candidate centipawns (#188 Phase D).

    The worker now persists each candidate's White-frame cp (``arrow_cp_*``);
    the classifier wants the mover-frame gap "how much better is the best line
    than the second". Convert each candidate to the mover's frame, then subtract.

    Frame note (#156-class hazard): candidate cps are White-frame. For a Black
    mover the better line is the *more negative* White-frame cp, so negate before
    subtracting.

    Args:
        arrow_cp_1: White-frame cp of the top candidate.
        arrow_cp_2: White-frame cp of the second candidate.
        mover_is_white: True iff the mover at this position is White.

    Returns:
        Non-negative mover-frame cp gap, or None when either candidate cp is
        missing (classifier then floors the top tier to "Best", as with MultiPV<2).
    """
    if arrow_cp_1 is None or arrow_cp_2 is None:
        return None
    mover_cp_1 = arrow_cp_1 if mover_is_white else -arrow_cp_1
    mover_cp_2 = arrow_cp_2 if mover_is_white else -arrow_cp_2
    return max(0.0, mover_cp_1 - mover_cp_2)


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


def _wdl_path(
    move: dict,
    *,
    mover_is_white: bool,
    before_white_mu: float,
) -> tuple[int, int, int, float, float, float]:
    """Compute WDL-path Win%/mu outputs for one move (no side-effects).

    Phase C scope: this path only changes the *accuracy* source (mover Win%
    from WDL_mu instead of the cp sigmoid) and populates the White-frame
    ``wdl_*_adj`` triple. The classifier's second-best gap is NOT computed
    here — the caller derives it natively from candidate cps via
    ``_gap_from_candidate_cp`` on both the WDL and fallback paths.

    Args:
        move: Raw move dict.
        mover_is_white: True iff the mover is White.
        before_white_mu: White-frame WDL_mu of the position before this move.

    Returns:
        Tuple of (wdl_win_adj, wdl_draw_adj, wdl_loss_adj,
                  win_pct_before_mover, win_pct_after_mover, mu_after_white).
        ``mu_after_white`` doubles as the stored mu and the game-walk mu.
    """
    wdl_win_w, wdl_draw_w, wdl_loss_w = _sf_wdl_mover_to_white(
        move["wdl_win"], move["wdl_draw"], move["wdl_loss"],
        mover_is_white=mover_is_white,
    )
    mu_after_white = _sf_wdl_mu_white(wdl_win_w, wdl_draw_w, wdl_loss_w)
    wp_before = (before_white_mu if mover_is_white else (1.0 - before_white_mu)) * 100.0
    wp_after = (mu_after_white if mover_is_white else (1.0 - mu_after_white)) * 100.0
    return (wdl_win_w, wdl_draw_w, wdl_loss_w, wp_before, wp_after, mu_after_white)


def _derive_one_move(
    move: dict,
    *,
    before_white: int = 0,
    before_white_mu: float = 0.5,
) -> dict:
    """Compute every derived field for one raw Stockfish move entry (#188 Phase C).

    When WDL is present, mover Win% comes from ``wdl_mu * 100`` (``_wdl_path``)
    instead of the cp sigmoid, and the White-frame ``wdl_*_adj`` triple is
    populated. CPL stays cp-based. The classifier's second-best gap is a native
    cp subtraction of the worker's candidate centipawns (``_gap_from_candidate_cp``)
    on BOTH paths — #188 Phase D.

    Args:
        move: One element of ``raw_payload["moves"]`` (#161/#188 SF raw contract).
        before_white: White-frame cp eval before this move (CPL + fallback Win%).
        before_white_mu: White-frame WDL_mu before this move (WDL path only).

    Returns:
        Dict with raw passthrough fields, derived fields, and walking-state
        keys (``_cp_after_white``, ``_mu_after_white``, ``_move_acc``,
        ``_win_pct_after_white``).  Walking-state keys are stripped by
        ``derive_sf_game``.
    """
    ply = int(move["ply"])
    mover_is_white = is_white_ply(ply)
    cp_after_white = _saturated_cp(move.get("cp_eval"), move.get("mate_in"))
    cpl_mover = cpl(
        before_white=before_white, after_white=cp_after_white,
        mover_is_white=mover_is_white,
    )

    have_wdl = (
        move.get("wdl_win") is not None
        and move.get("wdl_draw") is not None
        and move.get("wdl_loss") is not None
    )

    # Declared once so both branches assign without re-annotating (mypy).
    wdl_win_adj: Optional[int]
    wdl_draw_adj: Optional[int]
    wdl_loss_adj: Optional[int]
    wdl_mu_white: Optional[float]
    if have_wdl:
        (
            wdl_win_adj, wdl_draw_adj, wdl_loss_adj,
            win_pct_before_mover, win_pct_after_mover, wdl_mu_white,
        ) = _wdl_path(
            move,
            mover_is_white=mover_is_white,
            before_white_mu=before_white_mu,
        )
        # On the WDL path the White-frame mu drives both the stored value and
        # the game-accuracy walk.
        mu_for_walk = wdl_mu_white
    else:
        mover_cp_before = before_white if mover_is_white else -before_white
        mover_cp_after = cp_after_white if mover_is_white else -cp_after_white
        win_pct_before_mover = win_pct(mover_cp_before)
        win_pct_after_mover = win_pct(mover_cp_after)
        wdl_win_adj = wdl_draw_adj = wdl_loss_adj = None
        wdl_mu_white = None
        mu_for_walk = win_pct(cp_after_white) / 100.0

    # Classifier gap is cp-based on both paths, now from the worker's native
    # candidate centipawns (arrow_cp_*). Independent of which path produced the
    # accuracy. Falls back to None (→ "Best" floor) when candidate cps are absent.
    gap = _gap_from_candidate_cp(
        move.get("arrow_cp_1"), move.get("arrow_cp_2"),
        mover_is_white=mover_is_white,
    )

    move_acc = move_accuracy(win_pct_before_mover, win_pct_after_mover)
    classification = classify_sf_move(
        cpl_mover=cpl_mover,
        second_best_gap=gap,
        mover_win_pct=win_pct_before_mover,
        is_capture_or_sacrifice=False,
    )
    win_pct_after_white = (
        wdl_mu_white * 100.0 if wdl_mu_white is not None else win_pct(cp_after_white)
    )

    return {
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
        # #188 Phase D: candidate White-frame cp passthrough (gap source).
        "arrow_cp_1": move.get("arrow_cp_1"),
        "arrow_cp_2": move.get("arrow_cp_2"),
        "arrow_cp_3": move.get("arrow_cp_3"),
        # #188 Phase C: White-frame WDL (frame-mirror only; null on fallback).
        "wdl_win_adj": wdl_win_adj,
        "wdl_draw_adj": wdl_draw_adj,
        "wdl_loss_adj": wdl_loss_adj,
        "cpl": cpl_mover,
        "move_win_delta": win_pct_before_mover - win_pct_after_mover,
        "classification": classification,
        "best_move": move.get("arrow_uci_1") or "",
        "_cp_after_white": cp_after_white,
        "_mu_after_white": mu_for_walk,
        "_move_acc": move_acc,
        "_win_pct_after_white": win_pct_after_white,
        # Per-move derived scalar. NOT a DB column on MoveAnalysis (no migration
        # needed). Recompute from wdl_*_adj on read if persistence is needed later.
        "wdl_mu": wdl_mu_white,
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
    """Derive every Stockfish-analysis field from a validated raw payload (#188 Phase C).

    The walk threads two "before" channels:
      * ``before_white`` (cp) for the cp-based CPL ladder and the sigmoid
        fallback when WDL is missing.
      * ``before_white_mu`` (WDL_mu in White's frame) for the WDL path.

    Args:
        raw_payload: Dict matching the #161 + #188 raw Stockfish contract.
        game: ``games.Game`` instance; reserved for future Elo-aware
            adjustments (ignored in Phase C).

    Returns:
        Dict shaped for ``GameAnalysis`` model creation, with a nested
        ``moves`` list shaped for ``MoveAnalysis``. Walking-state keys
        (those prefixed with ``_``) are stripped before return.
    """
    derived_moves: list[dict] = []
    before_white = 0
    before_white_mu = 0.5  # mu of the starting position (matches cp=0 assumption).
    # NPV is persisted as reproducibility metadata only — no derivation path
    # reads it (the candidate gap stays cp-based via arrow scores).
    npv = raw_payload.get("normalize_to_pawn_value")
    all_win_pcts_white: list[float] = [_initial_win_pct_white()]
    for move in raw_payload["moves"]:
        result = _derive_one_move(
            move,
            before_white=before_white,
            before_white_mu=before_white_mu,
        )
        before_white = result.pop("_cp_after_white")
        before_white_mu = result.pop("_mu_after_white")
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
        # #188: pass NPV through for persistence; nullable for older SF builds.
        "normalize_to_pawn_value": npv,
        **aggregates,
        "moves": derived_moves,
    }
