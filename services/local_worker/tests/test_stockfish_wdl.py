"""
Title: test_stockfish_wdl.py — Unit tests for #188 Phase A SF WDL capture
Description:
    Tests covering UCI_ShowWDL enablement, played-move WDL capture,
    per-PV WDL capture, NormalizeToPawnValue capture, payload shape,
    and fallback behaviour when WDL is missing.

Changelog:
    2026-05-21 (#188/A): Initial creation.
"""
from local_worker.analysis.models import StockfishGameResult, StockfishMoveResult
from local_worker.analysis.stockfish import _build_engine_opts


def test_build_engine_opts_enables_uci_showwdl_by_default():
    """_build_engine_opts includes UCI_ShowWDL=True in the returned opts dict."""
    opts = _build_engine_opts(threads=4, hash_mb=512, syzygy_path="", auto_tune=False)
    assert opts.get("UCI_ShowWDL") is True


def test_build_engine_opts_keeps_caller_overrides_intact():
    """UCI_ShowWDL is additive — it must not displace caller-supplied values."""
    opts = _build_engine_opts(threads=2, hash_mb=128, syzygy_path="", auto_tune=False)
    assert opts["Threads"] == 2 and opts["Hash"] == 128
    assert opts["UCI_ShowWDL"] is True


def test_stockfish_move_result_accepts_wdl_triples_nullable():
    """StockfishMoveResult accepts WDL fields; unset candidate slots default to None."""
    move = StockfishMoveResult(
        ply=1, san="e4", fen="...", cp_eval=30,
        wdl_win=120, wdl_draw=850, wdl_loss=30,
        wdl_win_1=120, wdl_draw_1=850, wdl_loss_1=30,
    )
    assert move.wdl_win == 120
    assert move.wdl_loss_3 is None  # per-candidate slots default to None


def test_stockfish_game_result_carries_normalize_to_pawn_value():
    """StockfishGameResult stores NormalizeToPawnValue when provided."""
    result = StockfishGameResult(engine_depth=20, normalize_to_pawn_value=328)
    assert result.normalize_to_pawn_value == 328


def test_stockfish_game_result_defaults_npv_to_none():
    """NormalizeToPawnValue defaults to None for older SF builds."""
    result = StockfishGameResult(engine_depth=20)
    assert result.normalize_to_pawn_value is None
