"""
Title: test_stockfish_payload.py — Tests for Stockfish payload building
Description:
    Tests that the build_stockfish_payload helper produces valid API payloads
    from pre-canned move results.

Changelog:
    2026-05-09: Initial creation
"""
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


def _move_with_defaults():
    """Build a minimal StockfishGameResult with one move using dataclass defaults."""
    return StockfishGameResult(
        engine_depth=20, white_accuracy=92.1, black_accuracy=87.3,
        white_acpl=15.2, black_acpl=23.8,
        white_blunders=0, white_mistakes=1, white_inaccuracies=2,
        black_blunders=1, black_mistakes=2, black_inaccuracies=3,
        moves=[
            StockfishMoveResult(
                ply=1, san="e4",
                fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
                cp_eval=35, cpl=0, best_move="e4", classification="Best",
            )
        ],
    )


def test_payload_multipv_defaults_present():
    """Unset MultiPV slots are serialised as ""/None so the API row is well-formed."""
    move = build_stockfish_payload(_move_with_defaults(), worker_id="w")["moves"][0]
    assert move["arrow_uci"] == "" and move["arrow_uci_2"] == "" and move["arrow_uci_3"] == ""
    assert move["arrow_score_1"] is None and move["pv_san_1"] is None


def test_payload_round_trips_multipv_fields():
    """When the worker fills in arrow_* and pv_san_*, the payload carries them."""
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
                arrow_uci="e2e4", arrow_uci_2="d2d4", arrow_uci_3="g1f3",
                arrow_score_1=55.1, arrow_score_2=54.8, arrow_score_3=53.0,
                pv_san_1='["e4", "e5", "Nf3"]', pv_san_2='["d4", "d5"]', pv_san_3=None,
            )
        ],
    )
    move = build_stockfish_payload(game, worker_id="test-worker")["moves"][0]
    assert move["arrow_uci"] == "e2e4"
    assert move["arrow_uci_2"] == "d2d4"
    assert move["arrow_uci_3"] == "g1f3"
    assert move["arrow_score_1"] == 55.1
    assert move["arrow_score_2"] == 54.8
    assert move["arrow_score_3"] == 53.0
    assert move["pv_san_1"] == '["e4", "e5", "Nf3"]'
    assert move["pv_san_2"] == '["d4", "d5"]'
    assert move["pv_san_3"] is None
