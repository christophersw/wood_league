"""
Title: test_view_game_analysis_shell.py — Shell view tests for game analysis rewrite
Description:
    Tests that the game_analysis view renders the thin-shell template with
    HTMX partial slots for each visual unit, and shows the re-analyze banner
    when no new-schema data is available.

Changelog:
    2026-05-21 (#186): Initial — Task 4 shell view + template tests.
"""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_shell_returns_200_and_loads_partials(client, new_schema_game_factory):
    """Shell renders 200 and each visual unit slot has the correct hx-get URL.

    Parameters:
        client: Django test client.
        new_schema_game_factory: Fixture producing a fully-derived game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Each visual unit is wired with hx-get pointing at its partial URL.
    for partial in ["cards/sf", "cards/lc0", "chips", "charts/winpct",
                    "charts/sf-cp", "charts/lc0-wdl", "pgn"]:
        assert f"/_partials/games/{game.slug}/{partial}/" in body
    # Shell stays thin — no inline Plotly traces.
    assert body.count("Plotly.newPlot") == 0


def test_shell_shows_reanalyze_banner_when_legacy(client, legacy_sf_game_factory):
    """Shell returns 200 with re-analysis banner for legacy (pre-new-schema) games.

    Parameters:
        client: Django test client.
        legacy_sf_game_factory: Fixture producing a legacy SF-only game.
    """
    game = legacy_sf_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    assert "Re-analysis required" in resp.content.decode()
