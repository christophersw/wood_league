"""
Title: test_cards_lc0.py — Tests for the LC0 stat card context builder
Description:
    Verifies that build_lc0_card_context correctly surfaces both classification
    levels (base_severity primary bar and draw_character subordinate bar),
    accuracy, WDL, avg Δμ, and tooltip metadata for the LC0 stat card partial.

Changelog:
    2026-05-21 (#186): Initial — Task 7 LC0 stat card tests.
"""
import pytest

from games.cards import build_lc0_card_context
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_lc0_card_surfaces_both_classification_levels(new_schema_game_factory):
    """build_lc0_card_context returns accuracy, WDL, both classification counts,
    and tooltip meta with the required keys.

    Asserts:
        - lc0_white_accuracy matches the dataclass value.
        - wdl.white.win matches the game-end win probability.
        - base_severity_counts.white contains a 'blunder' key.
        - draw_character_counts.white is a dict (even if all zeros for the test data).
        - tooltip_meta contains 'network_name' and 'draw_rate_reference'.
    """
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    ctx = build_lc0_card_context(data)

    assert ctx["lc0_white_accuracy"] == data.lc0_white_accuracy
    assert ctx["wdl"]["white"]["win"] == data.lc0_white_win_prob

    # Base severity counts (level 1) — must have 'blunder' key regardless of value
    assert "blunder" in ctx["base_severity_counts"]["white"]

    # Draw-character counts (level 2) — must be a dict with underscore-normalised keys
    assert isinstance(ctx["draw_character_counts"]["white"], dict)
    assert "missed_win" in ctx["draw_character_counts"]["white"]
    assert "losing_blunder" in ctx["draw_character_counts"]["white"]
    assert "risky" in ctx["draw_character_counts"]["white"]
    assert "simplification" in ctx["draw_character_counts"]["white"]

    # Tooltip metadata keys
    assert "network_name" in ctx["tooltip_meta"]
    assert "draw_rate_reference" in ctx["tooltip_meta"]
    assert "engine_nodes" in ctx["tooltip_meta"]
    assert "contempt" in ctx["tooltip_meta"]
    assert "calibration_elo" in ctx["tooltip_meta"]
    assert "analyzed_at" in ctx["tooltip_meta"]


def test_lc0_card_black_side_present(new_schema_game_factory):
    """Black-side keys are present in base_severity_counts and draw_character_counts.

    Asserts:
        - base_severity_counts.black is a dict with 'blunder' key.
        - draw_character_counts.black is a dict.
        - avg_delta_mu_black is non-None when black moves have delta_mu populated.
    """
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    ctx = build_lc0_card_context(data)

    assert "blunder" in ctx["base_severity_counts"]["black"]
    assert isinstance(ctx["draw_character_counts"]["black"], dict)
    # The test fixture populates 2 black moves (ply 2, 4) with delta_mu values
    assert ctx["avg_delta_mu_black"] is not None


def test_lc0_card_tooltip_values_match_dataclass(new_schema_game_factory):
    """Tooltip metadata values come from the lc0_* fields on the dataclass.

    Asserts:
        - tooltip_meta.network_name == data.lc0_network_name
        - tooltip_meta.engine_nodes == data.lc0_engine_nodes
        - tooltip_meta.draw_rate_reference == data.lc0_draw_rate_reference
    """
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    ctx = build_lc0_card_context(data)

    assert ctx["tooltip_meta"]["network_name"] == data.lc0_network_name
    assert ctx["tooltip_meta"]["engine_nodes"] == data.lc0_engine_nodes
    assert ctx["tooltip_meta"]["draw_rate_reference"] == data.lc0_draw_rate_reference
