"""
Title: test_cards_sf.py — Tests for the SF stat-card context builder
Description:
    Verifies that build_sf_card_context produces the correct keys and
    values from a new-schema GameAnalysisDataV2, including per-side
    accuracy, ACPL, avg Win%-drop, classification counts, and tooltip
    metadata. Also includes a rendered-HTML test for the SF cp chart slot.

Changelog:
    2026-05-21 (#186): Initial.
    2026-05-27 (#216): Task 3 — assert SF cp chart slot is present in rendered card.
"""
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

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


def test_sf_card_renders_chart_slot(client, new_schema_game_factory):
    """The SF card embeds an HTMX slot that loads the SF cp chart (#216).

    GETs the rendered SF card partial and asserts the chart-slot div is
    present with the correct hx-get URL and hx-trigger attribute. The view
    is gated by LoginRequiredMiddleware; the test logs in via force_login.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    User = get_user_model()
    user = User.objects.create_user(email="testuser_sf_chart@example.com", password="x")
    client.force_login(user)
    game = new_schema_game_factory()
    resp = client.get(reverse("games_card_sf_partial", args=[game.slug]))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert f"/_partials/games/{game.slug}/charts/sf-cp/" in body
    assert 'hx-trigger="load"' in body
