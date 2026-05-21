"""
Title: test_cards_sf.py — Tests for the SF stat-card context builder
Description:
    Verifies that build_sf_card_context produces the correct keys and
    values from a new-schema GameAnalysisDataV2, including per-side
    accuracy, ACPL, avg Win%-drop, classification counts, and tooltip
    metadata.

Changelog:
    2026-05-21 (#186): Initial.
"""
import pytest
from games.cards import build_sf_card_context
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_sf_card_context_uses_new_fields(new_schema_game_factory):
    """build_sf_card_context should surface new-schema derived fields.

    Params:
        new_schema_game_factory: Fixture producing a fully-derived game.
    """
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    ctx = build_sf_card_context(data)
    assert ctx["white_accuracy"] == data.sf_white_accuracy
    assert ctx["white_acpl"] == data.sf_white_acpl
    assert ctx["avg_win_drop_white"] is not None  # mean(move_win_delta) over White plies
    assert "engine_depth" in ctx["tooltip_meta"]
    assert ctx["classification_counts"]["white"]["blunder"] >= 0
