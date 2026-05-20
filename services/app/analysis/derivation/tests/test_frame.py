"""
Title: test_frame.py — mover↔white frame conversion helpers
Description:
    Issue #161 Phase C. Engines emit raw observables in mixed frames (Stockfish
    cp is White-relative; lc0 WDL is mover-relative). The derivation layer
    consistently works in either *mover frame* (for per-move metrics like CPL
    and ΔWin%) or *White frame* (for game-wide volatility windowing). These
    helpers are the only place that flip.

Changelog:
    2026-05-19 (#161/C): Initial.
"""
from __future__ import annotations

from analysis.derivation._frame import (
    cp_in_mover_frame,
    cpl_from_white_cp,
    is_white_ply,
)


def test_white_plies_are_odd() -> None:
    """White moves on plies 1, 3, 5, …; Black on 2, 4, 6, …."""
    assert is_white_ply(1) is True
    assert is_white_ply(2) is False
    assert is_white_ply(3) is True
    assert is_white_ply(10) is False


def test_cp_in_mover_frame_preserves_white_cp() -> None:
    """White's mover-frame cp equals White's white-frame cp (identity)."""
    assert cp_in_mover_frame(white_cp=42, mover_is_white=True) == 42
    assert cp_in_mover_frame(white_cp=-77, mover_is_white=True) == -77


def test_cp_in_mover_frame_negates_for_black() -> None:
    """Black's mover-frame cp is the negation of the white-frame cp."""
    assert cp_in_mover_frame(white_cp=42, mover_is_white=False) == -42
    assert cp_in_mover_frame(white_cp=-77, mover_is_white=False) == 77


def test_cpl_from_white_cp_white_mover() -> None:
    """White CPL = white-frame eval drop, clamped at zero."""
    assert cpl_from_white_cp(before_white=120, after_white=80, mover_is_white=True) == 40
    assert cpl_from_white_cp(before_white=80, after_white=120, mover_is_white=True) == 0


def test_cpl_from_white_cp_black_mover() -> None:
    """Black CPL = white-frame eval *increase*, clamped at zero (Black wants negative cp)."""
    assert cpl_from_white_cp(before_white=-50, after_white=+30, mover_is_white=False) == 80
    assert cpl_from_white_cp(before_white=-100, after_white=-200, mover_is_white=False) == 0


def test_cpl_clamped_non_negative() -> None:
    """CPL is never negative; gains do not credit the mover."""
    assert cpl_from_white_cp(before_white=0, after_white=999, mover_is_white=True) == 0
    assert cpl_from_white_cp(before_white=0, after_white=-999, mover_is_white=False) == 0
