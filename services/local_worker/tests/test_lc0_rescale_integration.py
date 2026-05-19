"""
Title: test_lc0_rescale_integration.py — Integration tests for WDL rescale in analyze_pgn
Description:
    Verifies that analyze_pgn() wires rescale_wdl + classify_draw_aware into
    each move result and that Lc0GameResult carries calibration provenance.
    Uses a minimal in-process fake engine (no lc0 binary required).

Changelog:
    2026-05-19: Initial creation (issue #159 Phase C2)
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
