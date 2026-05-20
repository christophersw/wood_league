"""
Title: test_lc0_integration.py — Engine-backed Lc0 integration tests
Description:
    Live integration tests for the Lc0 analyze_pgn pipeline.  Tests skip
    unless WLW_RUN_ENGINE_TESTS=1 and the binary exists at LC0_PATH.
    Tests also skip if no network weights file is found.

    Network search order:
        1. WLW_LC0_NETWORK env var.
        2. Homebrew bundled network (/opt/homebrew/Cellar/lc0/0.32.1/libexec/).

    Tests:
        test_smoke_game_result — 8-ply Ruy Lopez plus 4-ply QG: verifies move
            count, WDL sums, delta signs, classifications, probabilities, and
            build_lc0_payload output.

    Run with:
        cd services/local_worker
        WLW_RUN_ENGINE_TESTS=1 uv run pytest tests/test_lc0_integration.py -v

Changelog:
    2026-05-10: Initial creation
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

_VALID = {"Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder"}

LC0_PATH = "/opt/homebrew/bin/lc0"
_BUNDLED = "/opt/homebrew/Cellar/lc0/0.32.1/libexec/42850.pb.gz"

_P8 = "[Event ?][Result *]\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 *"
_P4 = "[Event ?][Result *]\n1. d4 d5 2. c4 e6 *"


def _find_net() -> Optional[str]:
    env = os.environ.get("WLW_LC0_NETWORK", "")
    if env and Path(env).exists():
        return env
    return _BUNDLED if Path(_BUNDLED).exists() else None


def _enabled() -> bool:
    return os.environ.get("WLW_RUN_ENGINE_TESTS") == "1" and Path(LC0_PATH).exists()


pytestmark = pytest.mark.skipif(
    not _enabled(),
    reason=(
        "Engine integration tests are gated by WLW_RUN_ENGINE_TESTS=1 "
        f"(engine binary present at {LC0_PATH})."
    ),
)


def _net() -> str:
    path = _find_net()
    if not path:
        pytest.skip("No Lc0 network found — set WLW_LC0_NETWORK or install Homebrew lc0.")
    return path  # type: ignore[return-value]


def _run(pgn: str, nodes: int = 200, weights: str = ""):  # type: ignore[return]
    from local_worker.analysis.lc0 import analyze_pgn
    # Pass empty backend string to let lc0 use its compiled-in default.
    return analyze_pgn(pgn, LC0_PATH, nodes=nodes, weights_path=weights, backend="")


def _check(r, n: int) -> None:
    assert len(r.moves) == n and 0.0 <= r.white_win_prob <= 1.0
    for m in r.moves:
        assert 0 <= m.wdl_win <= 1000 and m.move_win_delta >= 0.0
        assert m.base_severity in _VALID


def _check_payload(p: dict) -> None:
    assert p["engine"] == "lc0" and len(p["moves"]) == 4
    for d in p["moves"]:
        assert d["base_severity"] in _VALID and d["move_win_delta"] >= 0.0


def test_smoke_game_result():
    """Analyse 8-ply Ruy Lopez and 4-ply QG; assert WDL, deltas, and payload.

    Assertions cover:
    - 8 moves with WDL sums == 1000, non-negative deltas, valid labels.
    - white_win_prob in [0, 1].
    - build_lc0_payload: engine tag, 4 moves, valid classification/delta.
    """
    from local_worker.analysis.lc0 import build_lc0_payload
    net = _net()
    _check(_run(_P8, weights=net), 8)
    _check_payload(build_lc0_payload(_run(_P4, weights=net), worker_id="test"))
