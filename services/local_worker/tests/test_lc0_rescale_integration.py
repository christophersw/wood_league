"""
Title: test_lc0_rescale_integration.py — Integration tests for WDL rescale in analyze_pgn
Description:
    Verifies that analyze_pgn() wires rescale_wdl + classify_draw_aware into
    each move result and that Lc0GameResult carries calibration provenance.
    Uses a minimal in-process fake engine (no lc0 binary required).

Changelog:
    2026-05-19: Initial creation (issue #159 Phase C2)
    2026-05-19: Add FIX-A test (delta_d uses rescaled draw fractions) and
                FIX-B tests (mixed-Elo fallback makes contempt=0) (issue #159)
"""
from __future__ import annotations

from typing import Any

import chess
import chess.engine
import pytest

from local_worker.analysis.lc0 import analyze_pgn

_VALID_BASE = {"Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder"}

_PGN_2PLY = "[Event ?][Result *]\n1. e4 e5 *"


class _RelScore:
    """Relative score stand-in returning a fixed Wdl."""

    def __init__(self, wdl: chess.engine.Wdl) -> None:
        self._wdl = wdl

    def wdl(self, *_a: object, **_k: object) -> chess.engine.Wdl:
        return self._wdl


class _FakePovScore:
    """PovScore stand-in with .pov(color) interface."""

    def __init__(self, wins: int, draws: int, losses: int) -> None:
        self._white = chess.engine.Wdl(wins=wins, draws=draws, losses=losses)
        self._black = chess.engine.Wdl(wins=losses, draws=draws, losses=wins)

    def pov(self, color: chess.Color) -> _RelScore:
        return _RelScore(self._white if color == chess.WHITE else self._black)


def _score(win: int, draw: int, loss: int) -> _FakePovScore:
    """Build a fake PovScore from White-frame WDL permille."""
    return _FakePovScore(win, draw, loss)


class _FakeEngine:
    """Minimal engine double that returns canned WDL without launching lc0.

    Returns empty PVs to avoid san() calls with illegal moves on the
    dynamically-changing board position.
    """

    # Use empty PV lists to avoid illegal-move san() errors when the played
    # move is included in a PV but the board position has advanced.
    _MULTI = [
        {"score": _score(500, 300, 200), "pv": []},
        {"score": _score(480, 300, 220), "pv": []},
        {"score": _score(460, 300, 240), "pv": []},
    ]
    _AFTER = {"score": _score(490, 310, 200)}

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
    ) -> Any:
        if multipv is not None:
            return self._MULTI
        return self._AFTER

    def quit(self) -> None:  # noqa: D102
        pass


def _run(white_elo: int = 900, black_elo: int = 1300) -> Any:
    """Run analyze_pgn on the 2-ply PGN using the in-process fake engine."""
    engine = _FakeEngine()
    return analyze_pgn(
        _PGN_2PLY,
        lc0_path="/dev/null",
        nodes=200,
        engine=engine,
        network_name_override="fake-net",
        draw_rate_reference_override=0.45,
        white_elo=white_elo,
        black_elo=black_elo,
    )


def test_raw_and_adj_wdl_differ():
    """Rescaled WDL must differ from raw WDL when Elo mismatch is large."""
    res = _run()
    assert len(res.moves) == 2
    m = res.moves[0]
    # raw triple
    raw = (m.wdl_win, m.wdl_draw, m.wdl_loss)
    # adj triple
    adj = (m.wdl_win_adj, m.wdl_draw_adj, m.wdl_loss_adj)
    # With 900 vs 1300 Elo gap the rescale should shift the distribution
    assert raw != adj, "Rescaled WDL should differ from raw WDL for large Elo gap"


def test_base_severity_in_valid_set():
    """base_severity must be one of the 6 defined tiers."""
    res = _run()
    for m in res.moves:
        assert m.base_severity in _VALID_BASE, (
            f"Unexpected base_severity={m.base_severity!r}"
        )


def test_game_result_calibration_provenance():
    """Lc0GameResult must carry calibration elo and contempt."""
    res = _run(white_elo=900, black_elo=1300)
    assert res.wdl_calibration_elo == 900
    assert res.contempt == -400   # white_elo - black_elo = 900 - 1300


def test_draw_rate_reference_carried():
    """draw_rate_reference on the game result matches the override supplied."""
    res = _run()
    assert pytest.approx(res.draw_rate_reference, rel=1e-4) == 0.45


# ---------------------------------------------------------------------------
# FIX-A: delta_d must use RESCALED draw fractions, not raw fractions
# ---------------------------------------------------------------------------


class _FakeEngineSignFlip:
    """Fake engine designed to expose the raw-vs-rescaled draw fraction bug.

    For the 2-ply PGN:
      - Ply 1 (White moves, e4): before multipv returns neutral WDL; after
        returns a slightly shifted WDL. Not the focus of this test.
      - Ply 2 (Black moves, e5): before multipv raw draw fraction = 0.20
        (200, 200, 600 in White frame) and after draw fraction = 0.25
        (250, 250, 500 in White frame).

    With white_elo=1600, black_elo=900 the rescale (White stronger) radically
    compresses Black's draw band in the rescaled space. The rescaled draw
    fractions for ply-2 are ~0.015 (before) and ~0.013 (after), yielding
    rescaled delta_d ≈ -0.002.  The raw delta_d = +0.05.  The OLD (broken)
    code would report positive delta_d; the CORRECT code reports negative.
    """

    # Ply-1 (White moves): multipv before e4 and after-e4 single analyse
    _PLY1_MULTI = [
        {"score": _score(500, 300, 200), "pv": []},
        {"score": _score(480, 300, 220), "pv": []},
        {"score": _score(460, 300, 240), "pv": []},
    ]
    _PLY1_AFTER = {"score": _score(490, 300, 210)}

    # Ply-2 (Black moves): multipv before e5 — raw draw frac = 200/1000 = 0.20
    _PLY2_MULTI = [
        {"score": _score(200, 200, 600), "pv": []},
        {"score": _score(180, 200, 620), "pv": []},
        {"score": _score(160, 200, 640), "pv": []},
    ]
    # After e5: raw draw frac = 250/1000 = 0.25 (raw delta_d = +0.05)
    _PLY2_AFTER = {"score": _score(250, 250, 500)}

    def __init__(self) -> None:
        self._multipv_call = 0
        self._single_call = 0

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
    ) -> Any:
        """Return canned WDL, cycling through ply-1 and ply-2 responses."""
        if multipv is not None:
            self._multipv_call += 1
            # First multipv call = ply 1 before, second = ply 2 before
            return self._PLY1_MULTI if self._multipv_call == 1 else self._PLY2_MULTI
        self._single_call += 1
        # First single call = ply 1 after, second = ply 2 after
        return self._PLY1_AFTER if self._single_call == 1 else self._PLY2_AFTER

    def quit(self) -> None:  # noqa: D102
        pass


def test_delta_d_uses_rescaled_draw_fraction():
    """delta_d on each move must reflect RESCALED draw fractions, not raw ones.

    For ply 2 (Black moves e5) with white_elo=1600, black_elo=900:
      - Raw draw fractions: before=0.20, after=0.25  =>  raw delta_d = +0.05
      - Rescaled draw fractions (White much stronger): ~0.015 -> ~0.013
                                                    =>  rescaled delta_d ≈ -0.002

    The OLD (broken) code used raw fractions and would report delta_d ≈ +0.05.
    The CORRECT code uses rescaled fractions and must report delta_d < 0.

    If the implementation is reverted to use raw fractions, this test fails
    because raw_delta_d (0.05) > 0 while rescaled_delta_d < 0.
    """
    engine = _FakeEngineSignFlip()
    res = analyze_pgn(
        _PGN_2PLY,
        lc0_path="/dev/null",
        nodes=200,
        engine=engine,
        network_name_override="fake-net",
        draw_rate_reference_override=0.45,
        white_elo=1600,
        black_elo=900,
    )
    assert len(res.moves) == 2
    ply2 = res.moves[1]  # Black's move (e5)
    # Rescaled delta_d must be negative (less drawish in rescaled space)
    # while raw delta_d would be +0.05 (positive = more drawish in raw space).
    assert ply2.delta_d is not None, "delta_d must be set when draw_rate_reference > 0"
    assert ply2.delta_d < 0, (
        f"delta_d={ply2.delta_d:.4f} — expected negative (rescaled space) "
        f"but got positive (this indicates raw fractions are being used instead of rescaled)"
    )
    # Also assert it's not as large as the raw value (+0.05); it should be near -0.002
    assert abs(ply2.delta_d) < 0.04, (
        f"delta_d magnitude {abs(ply2.delta_d):.4f} too large — "
        f"raw delta_d magnitude is 0.05; rescaled should be near 0.002"
    )


# ---------------------------------------------------------------------------
# FIX-B: Elo fallback — if EITHER side is missing, BOTH fall back together
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "white_elo, black_elo, expected_calibration_elo, expected_contempt",
    [
        # Mixed Elo: white missing (0), black present — both should fall back
        (0, 900, 1100, 0),
        # Mixed Elo: white present, black missing (0) — both should fall back
        (900, 0, 1100, 0),
        # Both present: no fallback, contempt = white - black
        (900, 1300, 900, -400),
    ],
    ids=["white_missing", "black_missing", "both_present"],
)
def test_elo_fallback_symmetry(
    white_elo: int,
    black_elo: int,
    expected_calibration_elo: int,
    expected_contempt: int,
) -> None:
    """Elo fallback must apply to BOTH sides when either is absent.

    When either white_elo or black_elo is 0/missing, the effective Elos for
    BOTH players must fall back to fallback_elo (1100 by default) so that
    contempt == 0 and the rescale remains symmetric.

    Spec ref: plan C2 Step 3 lines 1224-1226.
    """
    engine = _FakeEngine()
    res = analyze_pgn(
        _PGN_2PLY,
        lc0_path="/dev/null",
        nodes=200,
        engine=engine,
        network_name_override="fake-net",
        draw_rate_reference_override=0.45,
        white_elo=white_elo,
        black_elo=black_elo,
        fallback_elo=1100,
    )
    assert res.wdl_calibration_elo == expected_calibration_elo, (
        f"white_elo={white_elo}, black_elo={black_elo}: "
        f"expected wdl_calibration_elo={expected_calibration_elo}, got {res.wdl_calibration_elo}"
    )
    assert res.contempt == expected_contempt, (
        f"white_elo={white_elo}, black_elo={black_elo}: "
        f"expected contempt={expected_contempt}, got {res.contempt}"
    )
