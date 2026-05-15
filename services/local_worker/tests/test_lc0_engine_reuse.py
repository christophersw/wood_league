"""
Title: test_lc0_engine_reuse.py — Engine reuse across jobs (issue #117)
Description:
    Pins the behaviour added by issue #117: when ``analyze_pgn(engine=...)``
    is supplied, the function must skip ``popen_uci``/``configure`` entirely
    and never invoke ``engine.quit`` on the caller-owned process. The NN
    cache is intentionally left warm across games — that's a pure speedup
    and not a correctness issue — so no per-game reset is required.

Changelog:
    2026-05-15: Initial creation (issue #117).
"""
from __future__ import annotations

from typing import Any

import chess
import chess.engine
import pytest

from local_worker.analysis import lc0 as lc0_module
from local_worker.analysis.lc0 import analyze_pgn


_PGN_4PLY = "1. e4 e5 2. Nf3 Nc6 *"


class _ReusableFakeEngine:
    """In-process stand-in that records lifecycle calls.

    Returns a canned MultiPV info dict so ``_analyze_one_move`` reads it
    without exploding. Each analyse() call appends to ``analyse_calls``;
    ``ucinewgame()`` and ``quit()`` set explicit flags so tests can assert
    they were (or were not) invoked.
    """

    def __init__(self) -> None:
        self.analyse_calls: int = 0
        self.ucinewgame_calls: int = 0
        self.quit_calls: int = 0
        self.configure_calls: int = 0

    def _canned_info(self, multipv: int | None) -> Any:
        """Build a non-empty info shape ``_analyze_one_move`` accepts."""
        wdl = chess.engine.Wdl(wins=400, draws=400, losses=200)

        class _Rel:
            def wdl(self_inner, *_a: object, **_k: object) -> chess.engine.Wdl:
                return wdl

        class _Pov:
            def pov(self_inner, _color: chess.Color) -> _Rel:
                return _Rel()

        score = _Pov()
        if multipv is None:
            return {"score": score}
        # Empty PVs so ``best_move_uci`` resolves to "" and the lc0
        # ``board.san()`` calls short-circuit instead of asserting on a
        # canned move that becomes illegal in later positions. The point
        # of this test is the lifecycle of the engine, not PV semantics.
        return [
            {"score": score, "pv": []},
            {"score": score, "pv": []},
            {"score": score, "pv": []},
        ]

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
    ) -> Any:
        self.analyse_calls += 1
        return self._canned_info(multipv)

    def ucinewgame(self) -> None:
        self.ucinewgame_calls += 1

    def configure(self, opts: dict[str, str]) -> None:
        self.configure_calls += 1

    def quit(self) -> None:
        self.quit_calls += 1


def test_reused_engine_skips_popen_uci(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #117: passing ``engine=`` must not launch a new lc0 process.

    Replaces ``SimpleEngine.popen_uci`` with a poison value so any
    accidental cold-start path fails the test instead of silently
    spawning a real binary.
    """
    def _explode(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError(
            "popen_uci must not be called when engine= is supplied (#117)"
        )

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", _explode)
    engine = _ReusableFakeEngine()

    result = analyze_pgn(
        pgn_text=_PGN_4PLY,
        lc0_path="/fake/lc0",
        nodes=10,
        backend="cuda-fp16",
        engine=engine,
        network_name_override="Net-test",
    )

    assert result is not None
    assert engine.configure_calls == 0, "configure must not run on reused engine"
    assert engine.quit_calls == 0, "caller owns the engine; analyze must not quit it"


def test_reused_engine_handles_multiple_calls() -> None:
    """Two successive analyze_pgn calls reuse the same engine cleanly.

    Mirrors the batch drain loop: same engine, multiple games, no quit
    or relaunch in between.
    """
    engine = _ReusableFakeEngine()

    for _ in range(2):
        analyze_pgn(
            pgn_text=_PGN_4PLY,
            lc0_path="/fake/lc0",
            nodes=10,
            backend="cuda-fp16",
            engine=engine,
            network_name_override="Net-test",
        )

    assert engine.quit_calls == 0
    assert engine.configure_calls == 0
    # Two games × four plies × two analyse() calls per ply (MultiPV + after)
    # = 16; the PV-reuse fast path is skipped because our fake returns
    # empty PVs.
    assert engine.analyse_calls >= 8


def test_reused_engine_uses_network_name_override() -> None:
    """The caller-provided network name is propagated into the result."""
    engine = _ReusableFakeEngine()

    result = analyze_pgn(
        pgn_text=_PGN_4PLY,
        lc0_path="/fake/lc0",
        nodes=10,
        backend="cuda-fp16",
        engine=engine,
        network_name_override="MyNet-1024",
    )

    assert result.network_name == "MyNet-1024"


def test_launch_engine_quits_on_configure_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``_configure_engine`` raises, the spawned subprocess must be quit.

    Otherwise a configure-time crash would leak the lc0 process.
    """
    spawned: list[_ReusableFakeEngine] = []

    def _fake_popen(*_args: object, **_kwargs: object) -> _ReusableFakeEngine:
        eng = _ReusableFakeEngine()
        spawned.append(eng)
        return eng  # type: ignore[return-value]

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("simulated configure failure")

    monkeypatch.setattr(
        chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen)
    )
    monkeypatch.setattr(lc0_module, "_configure_engine", _boom)

    with pytest.raises(RuntimeError, match="simulated configure failure"):
        lc0_module.launch_engine(
            lc0_path="/fake/lc0",
            weights_path="",
            syzygy_path="",
            backend="cuda-fp16",
        )

    assert len(spawned) == 1
    assert spawned[0].quit_calls == 1, "leaked subprocess on configure failure"
