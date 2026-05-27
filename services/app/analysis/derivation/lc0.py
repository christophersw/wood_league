"""
Title: lc0.py — Lc0 derivation orchestrator (#161 Phase D)
Description:
    Public surface for Lc0 derivation. Re-exports the calibration / classify
    primitives ported into ``_calibration`` and provides ``derive_lc0_game``,
    the single entry point used by the lc0 complete-serializer.

    Pipeline for one raw payload:
      1. Resolve White/Black Elo from the ``Game`` (sym fallback when one or
         both ratings are missing — mirrors #159's behaviour).
      2. For each move, rescale the worker-supplied mover-frame raw WDL into
         White's frame; derive ``wdl_*_adj`` + ``wdl_mu`` (White-frame
         expected-score fraction).
      3. Walk consecutive plies to compute ``delta_mu`` and ``delta_d``;
         classify each move via ``classify_draw_aware``.
      4. Aggregate per-side WDL probability means and severity counters.

    Ply 1 has no "before" position, so its ``delta_*`` and ``base_severity`` /
    ``draw_character`` are emitted as ``None`` / ``Best``. Phase F/G consume
    the returned dict directly into ``Lc0GameAnalysis`` / ``Lc0MoveAnalysis``.

Changelog:
    2026-05-19 (#161/C): Stub.
    2026-05-19 (#161/D): Math relocated; orchestrator + golden vectors landed.
"""
from __future__ import annotations

from typing import Any, Optional

from django.conf import settings

from analysis.derivation._calibration import (
    DrawAwareClass,
    RescaledWDL,
    classify_draw_aware,
    rescale_wdl,
)
from analysis.derivation._frame import is_white_ply
from analysis.derivation.accuracy import game_accuracy, move_accuracy
from analysis.derivation.counters import count_severities

# Mover-frame Win% used as the synthetic "before" anchor for windowing's
# initial entry (matches Stockfish's ``win_pct(0) = 50``). Note: this is NOT
# used as a "before" for ply 1's per-move accuracy — that ply is skipped from
# the per-side series per the owner-locked spec in GH #164.
_INITIAL_WIN_PCT_WHITE = 50.0

__all__ = [
    "DrawAwareClass",
    "RescaledWDL",
    "classify_draw_aware",
    "derive_lc0_game",
    "rescale_wdl",
]


def _resolve_elos(game: Any) -> tuple[int, int]:
    """Return (white_elo, black_elo), applying the symmetric-fallback rule.

    Mirrors #159 D1: when either rating is missing, both fall back to
    ``settings.WL_LC0_FALLBACK_ELO`` so contempt is symmetric (zero) rather
    than spuriously biased.

    Args:
        game: ``games.Game`` instance with ``white_rating`` / ``black_rating``.

    Returns:
        ``(white_elo, black_elo)`` as ints.
    """
    fallback = int(settings.WL_LC0_FALLBACK_ELO)
    white = getattr(game, "white_rating", None)
    black = getattr(game, "black_rating", None)
    if white is None or black is None:
        return fallback, fallback
    return int(white), int(black)


def _to_white_frame(
    mover_win: int, mover_draw: int, mover_loss: int, *, mover_is_white: bool,
) -> tuple[int, int, int]:
    """Convert a mover-frame WDL triple into White's frame.

    Args:
        mover_win: Mover-frame win permille.
        mover_draw: Mover-frame draw permille.
        mover_loss: Mover-frame loss permille.
        mover_is_white: True iff the side to move is White.

    Returns:
        ``(white_win, white_draw, white_loss)`` permille.
    """
    if mover_is_white:
        return mover_win, mover_draw, mover_loss
    return mover_loss, mover_draw, mover_win


def _mu_white_from_adj(adj: tuple[int, int, int]) -> float:
    """White-frame expected-score fraction from a rescaled WDL permille triple.

    Args:
        adj: Rescaled ``(win, draw, loss)`` in White's frame.

    Returns:
        ``(win + 0.5 * draw) / total`` in [0, 1]. Returns 0.5 when ``total``
        is zero (degenerate).
    """
    total = adj[0] + adj[1] + adj[2]
    if total <= 0:
        return 0.5
    return (adj[0] + 0.5 * adj[1]) / total


def _d_from_adj(adj: tuple[int, int, int]) -> float:
    """Drawishness fraction (D) from a rescaled WDL permille triple."""
    total = adj[0] + adj[1] + adj[2]
    return adj[1] / total if total > 0 else 0.0


def _derive_one_move(
    move: dict,
    *,
    white_elo: int,
    black_elo: int,
    draw_rate_reference: float,
    prev_mu_white: Optional[float],
    prev_d_white: Optional[float],
) -> dict:
    """Compute the derived fields for one move's raw payload entry.

    Args:
        move: One element of ``raw_payload["moves"]`` (raw lc0 contract).
        white_elo: White player's Elo for the rescale.
        black_elo: Black player's Elo for the rescale.
        draw_rate_reference: Calibrated network draw rate.
        prev_mu_white: White-frame mu of the position *before* this move
            (i.e. previous ply's ``mu_white``), or None at ply 1.
        prev_d_white: Same convention for draw fraction.

    Returns:
        Dict carrying the raw fields verbatim plus all derived fields.
    """
    ply = int(move["ply"])
    mover_is_white = is_white_ply(ply)
    raw_white = _to_white_frame(
        int(move["wdl_win"]), int(move["wdl_draw"]), int(move["wdl_loss"]),
        mover_is_white=mover_is_white,
    )
    rescaled = rescale_wdl(
        *raw_white,
        white_elo=float(white_elo), black_elo=float(black_elo),
        white_to_move=mover_is_white,
        draw_rate_reference=draw_rate_reference,
    )
    adj = rescaled.wdl_white
    mu_white = _mu_white_from_adj(adj)
    d_white = _d_from_adj(adj)
    delta_mu: Optional[float]
    delta_d: Optional[float]
    base: str
    modifier: Optional[str]
    move_acc: Optional[float]
    if prev_mu_white is None or prev_d_white is None:
        delta_mu = None
        delta_d = None
        base = "Best"
        modifier = None
        # Ply 1: no prior position → per-move accuracy is undefined. Skip from
        # the per-side series; ``derive_lc0_game`` checks for None and drops it.
        move_acc = None
    else:
        # mover-frame Δμ: mover's winning-chance loss.
        if mover_is_white:
            delta_mu = max(0.0, prev_mu_white - mu_white)
        else:
            delta_mu = max(0.0, mu_white - prev_mu_white)
        delta_d = d_white - prev_d_white
        classified = classify_draw_aware(delta_mu, delta_d)
        base, modifier = classified.base, classified.modifier
        # Mover-frame Win% before/after, then Lichess curve.
        if mover_is_white:
            mu_before_mover, mu_after_mover = prev_mu_white, mu_white
        else:
            mu_before_mover, mu_after_mover = 1.0 - prev_mu_white, 1.0 - mu_white
        move_acc = move_accuracy(100.0 * mu_before_mover, 100.0 * mu_after_mover)
    return {
        # Raw fields (passed through unchanged).
        "ply": ply,
        "san": move["san"],
        "fen": move["fen"],
        "wdl_win": int(move["wdl_win"]),
        "wdl_draw": int(move["wdl_draw"]),
        "wdl_loss": int(move["wdl_loss"]),
        "arrow_uci_1": move.get("arrow_uci_1") or "",
        "arrow_uci_2": move.get("arrow_uci_2"),
        "arrow_uci_3": move.get("arrow_uci_3"),
        "wdl_win_1": move.get("wdl_win_1"),
        "wdl_draw_1": move.get("wdl_draw_1"),
        "wdl_loss_1": move.get("wdl_loss_1"),
        "wdl_win_2": move.get("wdl_win_2"),
        "wdl_draw_2": move.get("wdl_draw_2"),
        "wdl_loss_2": move.get("wdl_loss_2"),
        "wdl_win_3": move.get("wdl_win_3"),
        "wdl_draw_3": move.get("wdl_draw_3"),
        "wdl_loss_3": move.get("wdl_loss_3"),
        "pv_san_1": move.get("pv_san_1"),
        "pv_san_2": move.get("pv_san_2"),
        "pv_san_3": move.get("pv_san_3"),
        # Derived fields.
        "wdl_win_adj": adj[0],
        "wdl_draw_adj": adj[1],
        "wdl_loss_adj": adj[2],
        "wdl_mu": mu_white,
        "delta_mu": delta_mu,
        "delta_d": delta_d,
        "base_severity": base,
        "draw_character": modifier,
        # ``_mu_white_after`` and ``_d_white_after`` are walked between moves
        # by ``derive_lc0_game`` and stripped before return.
        "_mu_white_after": mu_white,
        "_d_white_after": d_white,
        # Accuracy bookkeeping consumed by ``derive_lc0_game``; both stripped.
        "_move_acc": move_acc,
        "_win_pct_after_white": 100.0 * mu_white,
    }


def _aggregate_side_probs(
    derived_moves: list[dict],
) -> dict[str, float]:
    """Average rescaled WDL probabilities per side across that side's plies.

    Args:
        derived_moves: Output of ``_derive_one_move`` for every move.

    Returns:
        Six-key dict with ``{white,black}_{win,draw,loss}_prob`` in [0, 1].
        A side with no plies contributes 0.0.
    """
    sums = {
        side: {"win": 0.0, "draw": 0.0, "loss": 0.0, "n": 0}
        for side in ("white", "black")
    }
    for move in derived_moves:
        adj_total = (
            move["wdl_win_adj"] + move["wdl_draw_adj"] + move["wdl_loss_adj"]
        ) or 1
        side = "white" if is_white_ply(move["ply"]) else "black"
        sums[side]["win"] += move["wdl_win_adj"] / adj_total
        sums[side]["draw"] += move["wdl_draw_adj"] / adj_total
        sums[side]["loss"] += move["wdl_loss_adj"] / adj_total
        sums[side]["n"] += 1

    def _avg(side: str, key: str) -> float:
        n = sums[side]["n"]
        return sums[side][key] / n if n else 0.0

    return {
        "white_win_prob": _avg("white", "win"),
        "white_draw_prob": _avg("white", "draw"),
        "white_loss_prob": _avg("white", "loss"),
        "black_win_prob": _avg("black", "win"),
        "black_draw_prob": _avg("black", "draw"),
        "black_loss_prob": _avg("black", "loss"),
    }


def _per_side_accuracy(
    derived_moves: list[dict],
) -> tuple[Optional[float], Optional[float]]:
    """Compute per-side game accuracy from per-move accuracy bookkeeping.

    Builds a White-frame Win% sequence ``[50.0, mu_white(1)*100, mu_white(2)*100, …]``
    of length ``num_plies + 1`` so windowing covers the full game, then routes
    each side's non-None per-move accuracies (with their 1-based ply indices)
    through ``accuracy.game_accuracy``. A side with zero contributing plies
    returns ``None`` so downstream UI can distinguish "no data" from "had
    moves and they were terrible".

    Args:
        derived_moves: Output of ``_derive_one_move`` for every move, with
            the private ``_move_acc`` and ``_win_pct_after_white`` keys still
            attached (this function pops them before returning).

    Returns:
        ``(white_accuracy, black_accuracy)`` floats in [0, 100], or ``None``
        when the corresponding side has no contributing plies.
    """
    all_win_pcts_white = [_INITIAL_WIN_PCT_WHITE]
    white_accs: list[float] = []
    white_idx: list[int] = []
    black_accs: list[float] = []
    black_idx: list[int] = []
    for move in derived_moves:
        all_win_pcts_white.append(move.pop("_win_pct_after_white"))
        move_acc = move.pop("_move_acc")
        if move_acc is None:
            continue
        ply = move["ply"]
        if is_white_ply(ply):
            white_accs.append(move_acc)
            white_idx.append(ply)
        else:
            black_accs.append(move_acc)
            black_idx.append(ply)
    white_acc = (
        game_accuracy(white_accs, all_win_pcts=all_win_pcts_white,
                      mover_ply_indices=white_idx)
        if white_accs else None
    )
    black_acc = (
        game_accuracy(black_accs, all_win_pcts=all_win_pcts_white,
                      mover_ply_indices=black_idx)
        if black_accs else None
    )
    return white_acc, black_acc


def derive_lc0_game(raw_payload: dict, game: Any) -> dict:
    """Derive every Lc0Analysis field from a validated raw lc0 payload.

    Args:
        raw_payload: Dict matching the #161 raw lc0 contract (worker_id,
            engine_nodes, network_name, draw_rate_reference, moves[]).
        game: The ``games.Game`` instance the payload is for; supplies the
            White/Black Elo used by the rescale.

    Returns:
        Dict shaped for ``Lc0GameAnalysis`` model creation, with a nested
        ``moves`` list shaped for ``Lc0MoveAnalysis``. Internal walking-state
        keys (those prefixed with ``_``) are stripped before return.
    """
    white_elo, black_elo = _resolve_elos(game)
    draw_rate_reference = float(raw_payload["draw_rate_reference"])
    derived_moves: list[dict] = []
    prev_mu_white: Optional[float] = None
    prev_d_white: Optional[float] = None
    for move in raw_payload["moves"]:
        result = _derive_one_move(
            move,
            white_elo=white_elo, black_elo=black_elo,
            draw_rate_reference=draw_rate_reference,
            prev_mu_white=prev_mu_white, prev_d_white=prev_d_white,
        )
        prev_mu_white = result.pop("_mu_white_after")
        prev_d_white = result.pop("_d_white_after")
        derived_moves.append(result)
    counters = count_severities(
        (m["ply"], m["base_severity"]) for m in derived_moves
    )
    probs = _aggregate_side_probs(derived_moves)
    # Must run AFTER _aggregate_side_probs (which reads no private keys) but
    # BEFORE returning, since it pops _move_acc / _win_pct_after_white off the
    # move dicts that are about to be serialised.
    white_acc, black_acc = _per_side_accuracy(derived_moves)
    return {
        "engine_nodes": int(raw_payload["engine_nodes"]),
        "network_name": raw_payload["network_name"],
        "draw_rate_reference": draw_rate_reference,
        # White-side analysis: WDLCalibrationElo=white_elo,
        # Contempt=white_elo−black_elo, ContemptMode=white_side_analysis.
        # Contempt is negative when White is the underdog (e.g. 1000 vs 1300 → −300).
        "wdl_calibration_elo": white_elo,
        "contempt": white_elo - black_elo,
        **probs,
        "white_blunders": counters.white_blunders,
        "white_mistakes": counters.white_mistakes,
        "white_inaccuracies": counters.white_inaccuracies,
        "black_blunders": counters.black_blunders,
        "black_mistakes": counters.black_mistakes,
        "black_inaccuracies": counters.black_inaccuracies,
        "white_accuracy": white_acc,
        "black_accuracy": black_acc,
        "moves": derived_moves,
    }
