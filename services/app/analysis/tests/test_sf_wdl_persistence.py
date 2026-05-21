"""
Title: test_sf_wdl_persistence.py — #188 Phase B WDL persistence tests
Description:
    Round-trip tests verifying that SF WDL triples + NormalizeToPawnValue
    flow through derive_sf_game and complete_stockfish_job into the DB
    verbatim. Phase B is purely passthrough — _adj columns stay null until
    Phase C.

Changelog:
    2026-05-21 (#188/B): Initial — TDD suite for Task B2 (passthrough) and
        Task B3 (persistence round-trip).
"""
from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from analysis.derivation.stockfish import derive_sf_game
from analysis.models import AnalysisJob, GameAnalysis, MoveAnalysis
from analysis.services.jobs import complete_stockfish_job
from games.models import Game


# ── Fixtures ─────────────────────────────────────────────────────────────


def _make_game() -> Game:
    """Create a minimal Game row with a unique ID.

    Returns:
        Game: A saved Game instance suitable for analysis job tests.
    """
    return Game.objects.create(
        id=f"test-188b-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="1. e4 e5 *",
    )


def _payload(**overrides) -> dict:
    """Build a minimal raw SF payload with all WDL fields populated.

    Args:
        **overrides: Any key overrides applied to the top-level payload dict.

    Returns:
        dict: A complete raw SF payload matching the #161/#188 contract.
    """
    move = {
        "ply": 1,
        "san": "e4",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "cp_eval": 30,
        "mate_in": None,
        "arrow_uci_1": "e2e4",
        "arrow_uci_2": "d2d4",
        "arrow_uci_3": None,
        "arrow_score_1": 55.0,
        "arrow_score_2": 52.0,
        "arrow_score_3": None,
        "pv_san_1": '["e5"]',
        "pv_san_2": '["c5"]',
        "pv_san_3": None,
        "wdl_win": 120,
        "wdl_draw": 850,
        "wdl_loss": 30,
        "wdl_win_1": 120,
        "wdl_draw_1": 850,
        "wdl_loss_1": 30,
        "wdl_win_2": 110,
        "wdl_draw_2": 860,
        "wdl_loss_2": 30,
        "wdl_win_3": None,
        "wdl_draw_3": None,
        "wdl_loss_3": None,
    }
    payload = {
        "worker_id": "w-1",
        "engine_depth": 20,
        "engine_name": "Stockfish 16",
        "normalize_to_pawn_value": 328,
        "moves": [move],
    }
    payload.update(overrides)
    return payload


# ── Task B2: derive_sf_game passthrough ──────────────────────────────────


def test_derive_sf_game_passes_wdl_through_verbatim() -> None:
    """derive_sf_game passes raw WDL triples through unchanged.

    The played-move triple and all three candidate triples must survive
    the derivation pipeline byte-for-byte. Phase B does not transform them.
    """
    derived = derive_sf_game(_payload(), game=None)
    m = derived["moves"][0]
    assert (m["wdl_win"], m["wdl_draw"], m["wdl_loss"]) == (120, 850, 30)
    assert (m["wdl_win_1"], m["wdl_draw_1"], m["wdl_loss_1"]) == (120, 850, 30)
    assert (m["wdl_win_2"], m["wdl_draw_2"], m["wdl_loss_2"]) == (110, 860, 30)
    assert m["wdl_win_3"] is None
    assert m["wdl_draw_3"] is None
    assert m["wdl_loss_3"] is None


def test_derive_sf_game_wdl_adj_null_in_phase_b() -> None:
    """Phase B: _adj WDL columns are null placeholders — Phase C populates them."""
    derived = derive_sf_game(_payload(), game=None)
    m = derived["moves"][0]
    assert m["wdl_win_adj"] is None
    assert m["wdl_draw_adj"] is None
    assert m["wdl_loss_adj"] is None


def test_derive_sf_game_passes_npv_through() -> None:
    """derive_sf_game surfaces normalize_to_pawn_value at the top level."""
    derived = derive_sf_game(_payload(), game=None)
    assert derived["normalize_to_pawn_value"] == 328


def test_derive_sf_game_handles_missing_wdl_fields() -> None:
    """Backwards compat: a payload without WDL fields still derives cleanly.

    Older SF workers that did not emit WDL or NPV must not crash the
    derivation pipeline. All new columns must be null.
    """
    payload = _payload()
    move = payload["moves"][0]
    for key in list(move):
        if key.startswith("wdl_"):
            del move[key]
    del payload["normalize_to_pawn_value"]

    derived = derive_sf_game(payload, game=None)
    m = derived["moves"][0]
    assert m["wdl_win"] is None
    assert m["wdl_draw"] is None
    assert m["wdl_loss"] is None
    assert m["wdl_win_1"] is None
    assert m["wdl_win_adj"] is None
    assert derived["normalize_to_pawn_value"] is None


# ── Task B3: complete_stockfish_job persistence ───────────────────────────


@pytest.mark.django_db
def test_complete_stockfish_job_persists_wdl_and_npv() -> None:
    """complete_stockfish_job writes WDL columns + NPV to the DB.

    Creates an AnalysisJob, calls complete_stockfish_job with a payload
    carrying full WDL data, then reads back from the DB to verify every
    new column is stored verbatim.
    """
    game = _make_game()
    job = AnalysisJob.objects.create(
        game=game,
        status=AnalysisJob.STATUS_RUNNING,
        worker_id="w-1",
        engine="stockfish",
        depth=20,
    )
    payload = _payload()

    complete_stockfish_job(
        job_id=job.id,
        worker_id="w-1",
        key_prefix=None,
        payload=payload,
    )

    ga = GameAnalysis.objects.get(game=game)
    assert ga.normalize_to_pawn_value == 328

    move = MoveAnalysis.objects.get(analysis=ga, ply=1)
    assert (move.wdl_win, move.wdl_draw, move.wdl_loss) == (120, 850, 30)
    assert (move.wdl_win_1, move.wdl_draw_1, move.wdl_loss_1) == (120, 850, 30)
    assert (move.wdl_win_2, move.wdl_draw_2, move.wdl_loss_2) == (110, 860, 30)
    assert move.wdl_win_3 is None
    assert move.wdl_draw_3 is None
    assert move.wdl_loss_3 is None
    # Phase B: _adj columns stay null until Phase C.
    assert move.wdl_win_adj is None
    assert move.wdl_draw_adj is None
    assert move.wdl_loss_adj is None


@pytest.mark.django_db
def test_complete_stockfish_job_handles_missing_wdl_fields() -> None:
    """complete_stockfish_job still completes when payload has no WDL fields.

    Backwards compat: older SF workers that did not emit WDL or NPV must
    still produce a valid GameAnalysis row with all new columns null.
    """
    game = _make_game()
    job = AnalysisJob.objects.create(
        game=game,
        status=AnalysisJob.STATUS_RUNNING,
        worker_id="w-1",
        engine="stockfish",
        depth=20,
    )
    payload = _payload()
    move = payload["moves"][0]
    for key in list(move):
        if key.startswith("wdl_"):
            del move[key]
    del payload["normalize_to_pawn_value"]

    complete_stockfish_job(
        job_id=job.id,
        worker_id="w-1",
        key_prefix=None,
        payload=payload,
    )

    ga = GameAnalysis.objects.get(game=game)
    assert ga.normalize_to_pawn_value is None

    move_row = MoveAnalysis.objects.get(analysis=ga, ply=1)
    assert move_row.wdl_win is None
    assert move_row.wdl_draw is None
    assert move_row.wdl_loss is None
    assert move_row.wdl_win_adj is None
