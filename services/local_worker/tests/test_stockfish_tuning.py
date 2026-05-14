"""
Title: test_stockfish_tuning.py — Unit tests for the Stockfish auto-tuner
Description:
    Covers the heuristic Threads/Hash derivation, the psutil-missing fallback
    path, the analyze_pgn auto_tune toggle, and the caller-override-wins
    contract for threads/hash_mb. No Stockfish binary is required — the
    engine layer is patched via a fake SimpleEngine.

Changelog:
    2026-05-13: Initial creation (issue #67 subtask B).
"""
from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from local_worker.analysis.stockfish_tuning import get_tuned_opts


# ---------------------------------------------------------------------------
# get_tuned_opts heuristics
# ---------------------------------------------------------------------------

def test_heuristic_threads_leaves_one_core_free():
    """Threads = cpu_count - 1, with mocked cpu_count."""
    fake_vm = SimpleNamespace(available=8 * 1024 * 1024 * 1024)  # 8 GB
    with patch("os.cpu_count", return_value=8), \
         patch("psutil.virtual_memory", return_value=fake_vm):
        opts = get_tuned_opts()
    assert opts["Threads"] == "7"


def test_heuristic_hash_is_quarter_of_free_ram_capped_at_2gb():
    """Hash = min(2048, free_ram_mb // 4)."""
    # 4 GB free → 1024 MB hash (under cap)
    fake_vm = SimpleNamespace(available=4 * 1024 * 1024 * 1024)
    with patch("os.cpu_count", return_value=4), \
         patch("psutil.virtual_memory", return_value=fake_vm):
        opts = get_tuned_opts()
    assert opts["Hash"] == "1024"

    # 32 GB free → 8192 → capped at 2048
    fake_vm = SimpleNamespace(available=32 * 1024 * 1024 * 1024)
    with patch("os.cpu_count", return_value=4), \
         patch("psutil.virtual_memory", return_value=fake_vm):
        opts = get_tuned_opts()
    assert opts["Hash"] == "2048"


def test_heuristic_threads_falls_back_to_one_when_cpu_count_is_none():
    """cpu_count() returning None must not raise; Threads collapses to 1."""
    fake_vm = SimpleNamespace(available=2 * 1024 * 1024 * 1024)
    with patch("os.cpu_count", return_value=None), \
         patch("psutil.virtual_memory", return_value=fake_vm):
        opts = get_tuned_opts()
    assert opts["Threads"] == "1"


def test_heuristic_does_not_set_use_nnue():
    """Tuner must never touch UseNNUE — Stockfish defaults are correct."""
    fake_vm = SimpleNamespace(available=4 * 1024 * 1024 * 1024)
    with patch("os.cpu_count", return_value=2), \
         patch("psutil.virtual_memory", return_value=fake_vm):
        opts = get_tuned_opts()
    assert "UseNNUE" not in opts


def test_psutil_missing_returns_fallback_hash_budget():
    """When psutil import fails, fallback assumes 1024 MB free → Hash=256."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("simulated missing psutil")
        return real_import(name, *args, **kwargs)

    # Drop any cached psutil module so the import inside _detect_free_ram_mb
    # actually runs through our fake_import.
    sys.modules.pop("psutil", None)
    try:
        with patch("os.cpu_count", return_value=4), \
             patch.object(builtins, "__import__", side_effect=fake_import):
            opts = get_tuned_opts()
    finally:
        # Re-import psutil for any subsequent tests that need it.
        import psutil  # noqa: F401
    # Fallback free RAM = 1024 MB → 1024 // 4 = 256 MB hash
    assert opts["Hash"] == "256"
    assert opts["Threads"] == "3"


# ---------------------------------------------------------------------------
# analyze_pgn auto_tune integration
# ---------------------------------------------------------------------------

_PGN_4PLY = "[Event ?][Result *]\n1. e4 e5 2. Nf3 Nc6 *"


def _fake_engine_factory(captured_opts: dict) -> MagicMock:
    """Build a MagicMock that mimics chess.engine.SimpleEngine.popen_uci.

    Every call to .configure() records its argument into captured_opts.
    .analyse() returns a minimal score-bearing payload so analyze_pgn can
    walk the moves without exercising a real binary.
    """
    import chess

    fake_engine = MagicMock()

    def _capture_configure(opts):
        captured_opts.clear()
        captured_opts.update(opts)

    fake_engine.configure.side_effect = _capture_configure

    def _fake_analyse(board, limit, multipv=None):
        info = {
            "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
            "pv": list(board.legal_moves)[:1],
        }
        if multipv is not None:
            return [info]
        return info

    fake_engine.analyse.side_effect = _fake_analyse
    fake_engine.quit.return_value = None
    return fake_engine


def test_analyze_pgn_auto_tune_true_merges_tuner_opts(monkeypatch):
    """auto_tune=True calls get_tuned_opts and merges into engine.configure."""
    from local_worker.analysis import stockfish as sf_mod

    captured: dict = {}
    fake_engine = _fake_engine_factory(captured)
    monkeypatch.setattr(
        sf_mod.chess.engine.SimpleEngine, "popen_uci",
        classmethod(lambda cls, path: fake_engine),
    )
    monkeypatch.setattr(
        sf_mod, "get_tuned_opts",
        lambda: {"Threads": "9", "Hash": "777"},
    )
    sf_mod.analyze_pgn(_PGN_4PLY, "/fake/sf", depth=1, auto_tune=True)
    assert captured["Threads"] == "9"
    assert captured["Hash"] == "777"


def test_analyze_pgn_auto_tune_false_bypasses_tuner(monkeypatch):
    """auto_tune=False must not call get_tuned_opts."""
    from local_worker.analysis import stockfish as sf_mod

    captured: dict = {}
    fake_engine = _fake_engine_factory(captured)
    monkeypatch.setattr(
        sf_mod.chess.engine.SimpleEngine, "popen_uci",
        classmethod(lambda cls, path: fake_engine),
    )
    tuner_called = {"n": 0}

    def _spy_tuner():
        tuner_called["n"] += 1
        return {"Threads": "99", "Hash": "9999"}

    monkeypatch.setattr(sf_mod, "get_tuned_opts", _spy_tuner)
    sf_mod.analyze_pgn(_PGN_4PLY, "/fake/sf", depth=1, auto_tune=False)
    assert tuner_called["n"] == 0
    # Falls back to the safe defaults baked into analyze_pgn.
    assert captured["Threads"] == 4
    assert captured["Hash"] == 512


def test_analyze_pgn_caller_threads_and_hash_override_tuner(monkeypatch):
    """Caller-supplied threads/hash_mb take priority over tuner output."""
    from local_worker.analysis import stockfish as sf_mod

    captured: dict = {}
    fake_engine = _fake_engine_factory(captured)
    monkeypatch.setattr(
        sf_mod.chess.engine.SimpleEngine, "popen_uci",
        classmethod(lambda cls, path: fake_engine),
    )
    monkeypatch.setattr(
        sf_mod, "get_tuned_opts",
        lambda: {"Threads": "9", "Hash": "777"},
    )
    sf_mod.analyze_pgn(
        _PGN_4PLY, "/fake/sf",
        depth=1, threads=2, hash_mb=64, auto_tune=True,
    )
    assert captured["Threads"] == 2
    assert captured["Hash"] == 64
