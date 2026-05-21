"""
Title: test_stockfish_wdl.py — Unit tests for #188 Phase A SF WDL capture
Description:
    Tests covering UCI_ShowWDL enablement, played-move WDL capture,
    per-PV WDL capture, NormalizeToPawnValue capture, payload shape,
    and fallback behaviour when WDL is missing.

Changelog:
    2026-05-21 (#188/A): Initial creation.
"""
import chess
import chess.engine
from unittest.mock import MagicMock

from local_worker.analysis.models import StockfishGameResult, StockfishMoveResult
from local_worker.analysis.stockfish import _build_engine_opts, _build_move_result


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


def test_build_move_result_carries_played_wdl_triple():
    """_build_move_result populates played-move and candidate WDL fields correctly."""
    move = _build_move_result(
        san="e4", fen_before="...", cp_eval_after_white=30, mate_in_white=None,
        arrows=["e7e5", "c7c5", ""], arrow_scores=[55.0, 52.0, None],
        pv_sans=["[\"e5\"]", None, None],
        wdl_played=(120, 850, 30),
        wdl_candidates=[(120, 850, 30), (110, 860, 30), (None, None, None)],
    )
    assert (move.wdl_win, move.wdl_draw, move.wdl_loss) == (120, 850, 30)
    assert (move.wdl_win_1, move.wdl_draw_1, move.wdl_loss_1) == (120, 850, 30)
    assert move.wdl_loss_3 is None


def test_build_move_result_handles_missing_wdl():
    """_build_move_result handles (None, None, None) WDL gracefully."""
    move = _build_move_result(
        san="e4", fen_before="...", cp_eval_after_white=30, mate_in_white=None,
        arrows=["e7e5"], arrow_scores=[55.0], pv_sans=[None],
        wdl_played=(None, None, None),
        wdl_candidates=[(None, None, None)],
    )
    assert move.wdl_win is None and move.wdl_draw is None and move.wdl_loss is None
    assert move.wdl_win_1 is None


def test_extract_arrows_and_pvs_returns_wdl_candidates():
    """Each PV slot contributes a mover-frame WDL triple."""
    from local_worker.analysis.stockfish import _extract_arrows_and_pvs

    board = chess.Board()
    # Build a fake info_list with python-chess PovScore + PovWdl objects.
    score = chess.engine.PovScore(chess.engine.Cp(30), chess.WHITE)
    wdl_white = chess.engine.PovWdl(chess.engine.Wdl(120, 850, 30), chess.WHITE)
    info = {"pv": [chess.Move.from_uci("e2e4")], "score": score, "wdl": wdl_white}
    arrows, scores, sans, wdl_triples = _extract_arrows_and_pvs(
        [info], board, chess.WHITE,
    )
    assert arrows[0] == "e2e4"
    assert wdl_triples[0] == (120, 850, 30)


from local_worker.analysis.stockfish import build_stockfish_payload


def test_build_stockfish_payload_emits_wdl_and_npv():
    """build_stockfish_payload includes WDL triples and normalize_to_pawn_value."""
    move = StockfishMoveResult(
        ply=1, san="e4", fen="...", cp_eval=30,
        wdl_win=120, wdl_draw=850, wdl_loss=30,
        wdl_win_1=120, wdl_draw_1=850, wdl_loss_1=30,
    )
    result = StockfishGameResult(
        engine_depth=20, engine_name="Stockfish 16", moves=[move],
        normalize_to_pawn_value=328,
    )
    payload = build_stockfish_payload(result, worker_id="w-1")
    assert payload["normalize_to_pawn_value"] == 328
    m = payload["moves"][0]
    assert (m["wdl_win"], m["wdl_draw"], m["wdl_loss"]) == (120, 850, 30)
    assert (m["wdl_win_1"], m["wdl_draw_1"], m["wdl_loss_1"]) == (120, 850, 30)
    assert m["wdl_loss_3"] is None


def test_build_stockfish_payload_npv_nullable():
    """build_stockfish_payload handles None normalize_to_pawn_value gracefully."""
    result = StockfishGameResult(engine_depth=20, moves=[])
    payload = build_stockfish_payload(result, worker_id="w-1")
    assert payload["normalize_to_pawn_value"] is None
