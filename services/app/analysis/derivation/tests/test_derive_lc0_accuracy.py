"""
Title: test_derive_lc0_accuracy.py — Per-side Lc0 game accuracy %
Description:
    Issue #164. ``derive_lc0_game`` must surface ``white_accuracy`` and
    ``black_accuracy`` floats (or ``None`` when a side contributes no plies)
    computed by feeding the per-side mover-frame Win% series through the
    shared ``derivation.accuracy.game_accuracy`` helper. Win% is taken as
    ``100 * mu_mover`` — no sigmoid is needed because ``wdl_mu`` is already an
    expected-score probability in [0, 1].

    Per-move accuracy semantics (owner-locked, #164):
      * Ply 1 is skipped from the per-move series — no prior position exists
        from which to compute a Win% drop. ``all_win_pcts_white`` still
        includes its post-move value so subsequent plies' volatility windows
        cover the full game.
      * Best-move replay (ΔWin% = 0) yields ≈ 100 per Lichess's curve.
      * One-sided games leave the inactive side's accuracy as ``None`` so
        downstream UI can distinguish "no data" from "had moves and they
        were terrible".

Changelog:
    2026-05-19 (#164): Initial TDD red — exercises white_accuracy /
        black_accuracy keys not yet emitted by derive_lc0_game.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analysis.derivation.lc0 import derive_lc0_game


@dataclass
class _GameStub:
    """Minimal Game stand-in carrying just the rating fields the orchestrator reads."""
    white_rating: Optional[int]
    black_rating: Optional[int]


def _raw_move(
    ply: int, *, mover_win: int, mover_draw: int, mover_loss: int,
    san: str = "—", fen: str = "—",
) -> dict:
    """Build a minimal raw move entry."""
    return {
        "ply": ply, "san": san, "fen": fen,
        "wdl_win": mover_win, "wdl_draw": mover_draw, "wdl_loss": mover_loss,
        "arrow_uci_1": "e2e4",
    }


def _payload(moves: list[dict], *, draw_rate_reference: float = 0.58) -> dict:
    """Wrap moves in the canonical raw payload envelope."""
    return {
        "worker_id": "w",
        "engine_nodes": 25000,
        "network_name": "TestNet",
        "draw_rate_reference": draw_rate_reference,
        "moves": moves,
    }


def _balanced_game(num_plies: int) -> dict:
    """All-balanced game: every ply emits a symmetric 500/0/500 mover-frame WDL.

    With equal Elos and a near-1.0 raw distribution between win/loss,
    the rescale should keep ``mu_white`` very close to 0.5 for every ply,
    so per-move ΔWin% ≈ 0 and per-move accuracy ≈ 100.
    """
    return _payload([
        _raw_move(p, mover_win=500, mover_draw=0, mover_loss=500)
        for p in range(1, num_plies + 1)
    ])


# ── keyset / shape ─────────────────────────────────────────────────────────────

def test_top_level_dict_includes_accuracy_keys() -> None:
    """white_accuracy and black_accuracy are part of the game-level dict."""
    payload = _balanced_game(10)
    out = derive_lc0_game(payload, _GameStub(1500, 1500))
    assert "white_accuracy" in out
    assert "black_accuracy" in out


# ── perfect / near-perfect play ─────────────────────────────────────────────────

def test_balanced_game_yields_near_100_per_side() -> None:
    """A symmetric, drift-free game scores ≥ 99 per side."""
    out = derive_lc0_game(_balanced_game(12), _GameStub(1500, 1500))
    assert out["white_accuracy"] is not None
    assert out["black_accuracy"] is not None
    assert out["white_accuracy"] >= 99.0
    assert out["black_accuracy"] >= 99.0


# ── single-side blunder asymmetry ──────────────────────────────────────────────

def test_single_black_blunder_pulls_black_below_white() -> None:
    """A catastrophic Black ply collapses Black's accuracy meaningfully below White's.

    Layout: balanced opening (plies 1-3), Black blunder at ply 4 (mover-frame
    50/50/900 — Black now losing badly), then both sides continue from the
    new, lopsided baseline. We assert the asymmetry, not absolute values:
    forcing post-blunder play to look "best" is fiddly because best-move
    semantics depend on the engine's view of the now-skewed position. The
    asymmetry (Black < White by a wide margin) is the real signal.
    """
    moves = [
        _raw_move(1, mover_win=500, mover_draw=0, mover_loss=500),
        _raw_move(2, mover_win=500, mover_draw=0, mover_loss=500),
        _raw_move(3, mover_win=500, mover_draw=0, mover_loss=500),
        _raw_move(4, mover_win=50, mover_draw=50, mover_loss=900),  # Black blunders
        # White (mover) is now winning; emit White-favouring mover-frame.
        _raw_move(5, mover_win=900, mover_draw=50, mover_loss=50),
        # Black (mover) is now losing; emit Black-pessimistic mover-frame.
        _raw_move(6, mover_win=50, mover_draw=50, mover_loss=900),
        _raw_move(7, mover_win=900, mover_draw=50, mover_loss=50),
        _raw_move(8, mover_win=50, mover_draw=50, mover_loss=900),
        _raw_move(9, mover_win=900, mover_draw=50, mover_loss=50),
        _raw_move(10, mover_win=50, mover_draw=50, mover_loss=900),
    ]
    out = derive_lc0_game(_payload(moves), _GameStub(1500, 1500))
    assert out["white_accuracy"] - out["black_accuracy"] >= 10.0


# ── ply-1 exclusion ────────────────────────────────────────────────────────────

def test_ply_1_does_not_raise_and_is_excluded_from_per_move_series() -> None:
    """Ply 1 has no prior wdl_mu — accuracy code must skip it without crashing.

    A 1-ply game has no derivable per-move accuracy at all, so both sides
    return None (no contributing plies).
    """
    payload = _payload([_raw_move(1, mover_win=500, mover_draw=300, mover_loss=200)])
    out = derive_lc0_game(payload, _GameStub(1500, 1500))
    assert out["white_accuracy"] is None
    assert out["black_accuracy"] is None


# ── one-sided games ────────────────────────────────────────────────────────────

def test_one_sided_two_ply_game_leaves_black_none() -> None:
    """A 2-ply game contributes one accuracy sample to Black (ply 2) and none to White.

    Ply 1 is skipped per spec. Ply 2 is Black's first move and has a prior
    position (ply 1's post-state) → contributes to Black's series. White has
    no ply ≥ 3 to contribute, so white_accuracy is None.
    """
    payload = _payload([
        _raw_move(1, mover_win=500, mover_draw=0, mover_loss=500),
        _raw_move(2, mover_win=500, mover_draw=0, mover_loss=500),
    ])
    out = derive_lc0_game(payload, _GameStub(1500, 1500))
    assert out["white_accuracy"] is None
    assert out["black_accuracy"] is not None


def test_empty_moves_yields_none_for_both_sides() -> None:
    """A payload with no moves at all surfaces None / None — never a crash."""
    out = derive_lc0_game(_payload([]), _GameStub(1500, 1500))
    assert out["white_accuracy"] is None
    assert out["black_accuracy"] is None


# ── range guarantee ────────────────────────────────────────────────────────────

def test_accuracy_values_clamp_to_unit_interval_percentage() -> None:
    """Per-side accuracy never escapes [0, 100]."""
    out = derive_lc0_game(_balanced_game(20), _GameStub(2400, 800))
    for key in ("white_accuracy", "black_accuracy"):
        assert out[key] is None or 0.0 <= out[key] <= 100.0
