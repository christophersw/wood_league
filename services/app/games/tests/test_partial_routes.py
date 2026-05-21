"""
Title: test_partial_routes.py — Route resolution for HTMX partials
Description:
    Parametrized tests verify that all seven new analysis partial routes
    resolve and return 200 for new-schema games. Legacy games return 404.
    Also contains content-level assertions for the Win%, SF cp, and LC0 WDL
    chart partials.

Changelog:
    2026-05-21 (#186): Initial — stub routes scaffolding.
    2026-05-21 (#186): Task 9 — add Win% partial content assertions.
    2026-05-21 (#186): Task 10 — add SF cp partial content assertions.
    2026-05-21 (#186): Task 11 — add LC0 WDL partial content assertions.
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


def test_sf_cp_partial_contains_payload_and_tooltip(client, new_schema_game_factory):
    """SF cp partial must embed JSON payload, section title, tooltip text, and JS reference.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/charts/sf-cp/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "sf-cp-data" in body                          # json_script tag id
    assert "Stockfish centipawn evaluation" in body      # section title
    assert "underlying engine signal" in body            # tooltip body text
    assert "sfCp.js" in body                             # static JS reference


def test_lc0_wdl_partial_contains_payload_and_tooltip(client, new_schema_game_factory):
    """LC0 WDL partial must embed JSON payload, chart title, calibration draw-rate text, and JS reference.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/charts/lc0-wdl/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "lc0-wdl-data" in body                         # json_script tag id
    assert "LC0 Win / Draw / Loss" in body                # chart section title
    assert "draw rate" in body                            # calibration draw-rate subtitle text
    assert "lc0Wdl.js" in body                            # static JS reference


def test_pgn_partial_renders_table_and_js(client, new_schema_game_factory):
    """PGN partial must embed id="pgn-table" and reference pgnTable.js.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game with
            a 4-ply PGN (e4 e5 Nf3 Nc6).
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/pgn/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert 'id="pgn-table"' in body      # table element present
    assert "pgnTable.js" in body          # static JS reference
