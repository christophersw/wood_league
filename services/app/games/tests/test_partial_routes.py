"""
Title: test_partial_routes.py — Route resolution for HTMX partials
Description:
    Parametrized tests verify that all seven new analysis partial routes
    resolve and return 200 for new-schema games. Legacy games return 404.
    Also contains content-level assertions for the Win% chart partial.

Changelog:
    2026-05-21 (#186): Initial — stub routes scaffolding.
    2026-05-21 (#186): Task 9 — add Win% partial content assertions.
"""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PARTIALS = [
    "games_card_sf_partial",
    "games_card_lc0_partial",
    "games_chips_partial",
    "games_chart_winpct_partial",
    "games_chart_sf_cp_partial",
    "games_chart_lc0_wdl_partial",
    "games_pgn_partial",
]


@pytest.mark.parametrize("name", PARTIALS)
def test_partial_route_resolves(client, new_schema_game_factory, name):
    """Each partial route resolves to a 200 response for a new-schema game."""
    game = new_schema_game_factory()
    resp = client.get(reverse(name, args=[game.slug]))
    assert resp.status_code == 200


def test_winpct_partial_contains_payload_and_tooltip(client, new_schema_game_factory):
    """Win% partial must embed JSON payload, axis title, tooltip text, and JS reference.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/charts/winpct/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "winpct-data" in body          # json_script tag id
    assert "Win-for-White" in body        # axis / section title visible
    assert "How this is computed" in body  # tooltip body heading
    assert "winpct.js" in body             # static JS reference
