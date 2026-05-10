"""
Title: test_stockfish_payload.py — Tests for Stockfish payload building
Description:
    Tests that the build_stockfish_payload helper produces valid API payloads
    from pre-canned move results.

Changelog:
    2026-05-09: Initial creation
"""
import pytest
from local_worker.analysis.models import StockfishMoveResult, StockfishGameResult
from local_worker.analysis.stockfish import build_stockfish_payload


def test_payload_structure():
    game = StockfishGameResult(
        engine_depth=20,
        white_accuracy=92.1,
        black_accuracy=87.3,
        white_acpl=15.2,
        black_acpl=23.8,
        white_blunders=0,
        white_mistakes=1,
        white_inaccuracies=2,
        black_blunders=1,
        black_mistakes=2,
        black_inaccuracies=3,
        moves=[
            StockfishMoveResult(
                ply=1, san="e4",
                fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
                cp_eval=35, cpl=0, best_move="e4", classification="Best",
            )
        ],
    )
    payload = build_stockfish_payload(game, worker_id="test-worker")
    assert payload["engine"] == "stockfish"
    assert payload["worker_id"] == "test-worker"
    assert payload["engine_depth"] == 20
    assert 0 <= payload["white_accuracy"] <= 100
    assert len(payload["moves"]) == 1
    move = payload["moves"][0]
    assert move["ply"] == 1
    assert move["classification"] == "Best"
