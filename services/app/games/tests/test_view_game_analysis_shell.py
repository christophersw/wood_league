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


def test_position_plate_present(client, new_schema_game_factory):
    """The board lives inside a wc-card POSITION plate.

    Parameters:
        client: Django test client.
        new_schema_game_factory: Fixture producing a fully-derived game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "position-plate" in body
    assert ">Position<" in body


def test_engine_line_scaffold_present(client, new_schema_game_factory):
    """The engine-lines scaffold IDs engineLines.js needs are present again.

    Parameters:
        client: Django test client.
        new_schema_game_factory: Fixture producing a fully-derived game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    body = resp.content.decode()
    assert resp.status_code == 200
    for needle in ['id="engine-lines-container"', 'id="engine-lines-controls"',
                   'id="engine-line-san-panel"', 'id="engine-line-moves"', ">Engine Line<"]:
        assert needle in body


def test_arrow_toggle_controls_present(client, new_schema_game_factory):
    """The POSITION plate header renders the three engine-arrow toggles with defaults.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    body = resp.content.decode()
    assert resp.status_code == 200
    assert 'id="board-sf-toggle"' in body
    assert 'id="board-lc0-toggle"' in body
    assert 'id="board-best-line-toggle"' in body
    assert body.count("checked") >= 2
