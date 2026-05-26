"""
Title: test_engine_line_partial.py — Characterization tests for the engine_line_partial view
Description:
    Lock the observable behavior of the engine_line_partial HTMX view before and
    after refactoring. Tests cover happy-path rendering, query-parameter validation
    (missing, too-short, and illegal move_uci), and the orientation=black branch.

    These are characterization tests: they document current behavior. If the view
    changes behavior they should fail, not be updated to match the new behavior
    (unless the behavior change is intentional).

Changelog:
    2026-05-23 (#208): Initial — characterization tests for engine_line_partial.
"""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

URL_NAME = "games_engine_line_partial"


def _url(game, **params):
    """Build the engine_line_partial URL for the given game slug and query params.

    Parameters:
        game: Game instance with a .slug attribute.
        **params: Query-string key/value pairs to append.

    Returns:
        str: Full path with query string.
    """
    base = reverse(URL_NAME, args=[game.slug])
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}?{qs}"
    return base


def test_happy_path_white_orientation_returns_200(client, new_schema_game_factory):
    """GET with a valid ply=0, move_uci=e2e4, engine=sf, tier=1, orientation=white returns 200.

    Verifies the basic success path and that the engine-line JSON data marker is present.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="e2e4", engine="sf", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "engine-line-frames-json" in body


def test_happy_path_black_orientation_returns_200(client, new_schema_game_factory):
    """GET with orientation=black returns 200 (exercises the flipped=True branch).

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="e2e4", engine="sf", tier=1, orientation="black")
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "engine-line-frames-json" in body


def test_missing_move_uci_returns_400(client, new_schema_game_factory):
    """GET without move_uci param returns 400 with an error message.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    url = _url(game, ply=0, engine="sf", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 400


def test_too_short_move_uci_returns_400(client, new_schema_game_factory):
    """GET with move_uci shorter than 4 characters returns 400.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="zz", engine="sf", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 400


def test_illegal_move_uci_for_start_position_returns_400(client, new_schema_game_factory):
    """GET with a well-formed but illegal UCI move (a1a8) at ply=0 returns 400.

    a1a8 is 4 characters and passes the length check, but is illegal from the
    starting position and should trigger the parse_uci ValueError branch → 400.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="a1a8", engine="sf", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 400


def test_happy_path_lc0_engine_returns_200(client, new_schema_game_factory):
    """GET with engine=lc0 returns 200 (exercises the lc0_moves branch in _engine_row_for_request).

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="e2e4", engine="lc0", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 200


def test_sf_engine_line_shows_bot_player_label(client, new_schema_game_factory):
    """The engine-line board labels both player slots with the SF bot + depth.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="e2e4", engine="sf", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.count("SF bot · depth 20") == 2   # top + bottom slots
    assert "engine-lines-header" not in body       # old strip removed
    assert "Best" not in body                       # old context_label gone


def test_lc0_engine_line_shows_bot_player_label(client, new_schema_game_factory):
    """The engine-line board labels both player slots with the LC0 bot + nodes.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="e2e4", engine="lc0", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.count("LC0 bot · nodes 800") == 2


def test_bot_label_omits_setting_when_unknown():
    """_engine_line_bot_label drops the depth/nodes suffix when the value is None.

    Parameters:
        (none)
    """
    from types import SimpleNamespace

    from games.views import _engine_line_bot_label

    no_settings = SimpleNamespace(engine_depth=None, lc0_engine_nodes=None)
    assert _engine_line_bot_label("sf", no_settings) == "SF bot"
    assert _engine_line_bot_label("lc0", no_settings) == "LC0 bot"
