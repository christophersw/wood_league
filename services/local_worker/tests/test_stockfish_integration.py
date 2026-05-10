"""
Title: test_stockfish_integration.py — Engine-backed Stockfish integration tests
Description:
    Live integration tests for the Stockfish analyze_pgn pipeline.  Tests skip
    unless WLW_RUN_ENGINE_TESTS=1 and the binary exists at STOCKFISH_PATH.

    Tests:
        test_smoke_game_result — 8-ply opening: verifies move count, accuracy
            bounds, ACPL, and classifications; then verifies build_stockfish_payload
            on a 4-ply game.
        test_mate_distance_penalty_nonzero — sub-optimal mate play must incur
            CPL >= MATE_PER_EXTRA_PLY (50 cp) from the mate-distance heuristic.

    Run with:
        cd services/local_worker
        WLW_RUN_ENGINE_TESTS=1 uv run pytest tests/test_stockfish_integration.py -v

Changelog:
    2026-05-10: Initial creation
"""
from __future__ import annotations

import os
from pathlib import Path

import chess
import chess.engine
import pytest

from tests._shared import VALID_CLASSIFICATIONS as _VALID

STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"

_P8 = "[Event ?][Result *]\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 *"
_P4 = "[Event ?][Result *]\n1. d4 d5 2. c4 e6 *"


def _enabled() -> bool:
    return os.environ.get("WLW_RUN_ENGINE_TESTS") == "1" and Path(STOCKFISH_PATH).exists()


pytestmark = pytest.mark.skipif(
    not _enabled(),
    reason=(
        "Engine integration tests are gated by WLW_RUN_ENGINE_TESTS=1 "
        f"(engine binary present at {STOCKFISH_PATH})."
    ),
)


def _run(pgn: str, depth: int = 8):  # type: ignore[return]
    from local_worker.analysis.stockfish import analyze_pgn
    return analyze_pgn(pgn, STOCKFISH_PATH, depth=depth, threads=1, hash_mb=16)


def _check(r, n: int) -> None:
    assert len(r.moves) == n and 0.0 <= r.white_accuracy <= 100.0
    assert 0.0 <= r.black_accuracy <= 100.0 and r.white_acpl >= 0
    for m in r.moves:
        assert m.classification in _VALID


def _check_payload(p: dict) -> None:
    assert p["engine"] == "stockfish" and len(p["moves"]) == 4
    for d in p["moves"]:
        assert d["classification"] in _VALID and d["cpl"] >= 0


# ---------------------------------------------------------------------------
# Test 1 — Smoke: analysis result and payload
# ---------------------------------------------------------------------------


def test_smoke_game_result():
    """Analyse 8-ply Ruy Lopez and 4-ply QG; assert structure and payload."""
    from local_worker.analysis.stockfish import build_stockfish_payload
    _check(_run(_P8), 8)
    _check_payload(build_stockfish_payload(_run(_P4), worker_id="test"))


# ---------------------------------------------------------------------------
# Test 2 — Mate-distance heuristic
# ---------------------------------------------------------------------------


def test_mate_distance_penalty_nonzero():
    """Sub-optimal mate play incurs CPL >= MATE_PER_EXTRA_PLY (50 cp).

    White Kg6, Qa1 vs Black Kh8: Qg7# is the best move (mate-in-1).
    Playing Qa6+ instead leaves a mate-in-2 (after Kg8 then Qg6#).
    The mate-distance heuristic must add at least 50 cp penalty.
    """
    from local_worker.analysis._mate_distance import MATE_PER_EXTRA_PLY
    from local_worker.analysis.stockfish import _analyze_one_move

    board = chess.Board("7k/8/6K1/8/8/8/8/Q7 w - - 0 1")
    eng = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
    try:
        eng.configure({"Threads": 1, "Hash": 16})
        _, _a, _w, cpl, _ww = _analyze_one_move(
            board, chess.Move.from_uci("a1a6"),
            chess.WHITE, eng, chess.engine.Limit(depth=12),
        )
    finally:
        eng.quit()
    assert cpl >= MATE_PER_EXTRA_PLY
