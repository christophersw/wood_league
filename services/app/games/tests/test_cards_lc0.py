"""
Title: test_cards_lc0.py — Tests for the LC0 stat card context builder
Description:
    Verifies that build_lc0_card_context correctly surfaces both classification
    levels (base_severity primary bar and draw_character subordinate bar),
    accuracy, WDL, avg Δμ, and tooltip metadata for the LC0 stat card partial.
    Also includes a rendered-HTML absence test for the removed GWC whole-game strip.

Changelog:
    2026-05-21 (#186): Initial — Task 7 LC0 stat card tests.
    2026-05-27 (#216): Task 2 — assert GWC whole-game strip is absent from rendered card.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from games.cards import build_lc0_card_context
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


@pytest.fixture
def lc0_ctx(new_schema_game_factory):
    """Build the LC0 card context for a new-schema game."""
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    return build_lc0_card_context(data), data


def test_lc0_card_surfaces_accuracy_and_wdl(lc0_ctx):
    """Accuracy and game-end WDL come straight from the dataclass."""
    ctx, data = lc0_ctx
    assert ctx["lc0_white_accuracy"] == data.lc0_white_accuracy
    assert ctx["wdl"]["white"]["win"] == data.lc0_white_win_prob


def test_lc0_card_has_base_severity_counts(lc0_ctx):
    """Base-severity counts (level 1) include a 'blunder' bucket."""
    ctx, _ = lc0_ctx
    assert "blunder" in ctx["base_severity_counts"]["white"]


def test_lc0_card_has_draw_character_counts(lc0_ctx):
    """Draw-character counts (level 2) expose all four underscore-normalised keys."""
    ctx, _ = lc0_ctx
    white = ctx["draw_character_counts"]["white"]
    assert isinstance(white, dict)
    for key in ("missed_win", "losing_blunder", "risky", "simplification"):
        assert key in white


def test_lc0_card_tooltip_has_required_keys(lc0_ctx):
    """Tooltip metadata exposes the LC0 run parameters."""
    ctx, _ = lc0_ctx
    for key in (
        "network_name", "draw_rate_reference", "engine_nodes",
        "contempt", "calibration_elo", "analyzed_at",
    ):
        assert key in ctx["tooltip_meta"]


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


def test_lc0_card_no_whole_game_gwc_strip(client, new_schema_game_factory):
    """The LC0 card partial must not render the whole-game GWC strip.

    The 'Avg. Winning Chances for Whole Game' block and its .card-gwc container
    were removed in #216 Task 2. This test GETs the rendered partial and asserts
    neither the heading text nor the CSS class is present.

    The view is gated by LoginRequiredMiddleware; the test logs in via
    force_login so it receives a 200 rather than a 302 redirect.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    User = get_user_model()
    user = User.objects.create_user(email="testuser_gwc@example.com", password="x")
    client.force_login(user)

    game = new_schema_game_factory()
    resp = client.get(reverse("games_card_lc0_partial", args=[game.slug]))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Avg. Winning Chances for Whole Game" not in body
    assert "card-gwc" not in body
