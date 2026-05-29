"""
Title: test_view_game_analysis_shell.py — Shell view tests for game analysis rewrite
Description:
    Tests that the game_analysis view renders the thin-shell template with
    HTMX partial slots for each visual unit, and shows the re-analyze banner
    when no new-schema data is available.

Changelog:
    2026-05-21 (#186): Initial — Task 4 shell view + template tests.
    2026-05-27 (#216): Task 8 — remove charts/winpct from partial fragment list.
    2026-05-29 (#226): Task C1 — header: TC label, opening link guard, chess.com
                       button, copy-PGN button, pgn json_script, trophy.
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
    for partial in ["cards/sf", "cards/lc0", "chips", "pgn"]:
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


def test_analysis_page_has_flip_button(client, new_schema_game_factory):
    """The Position card header renders a perspective-flip button (#216).

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="board-flip-btn"' in body
    assert "Flip" in body


# --- C1 header tests (#226) ---

_PGN_WITH_LINK = (
    '[Event "Live Chess"]\n'
    '[Site "Chess.com"]\n'
    '[Date "2026.01.01"]\n'
    '[Round "-"]\n'
    '[White "Alice"]\n'
    '[Black "Bob"]\n'
    '[Result "1-0"]\n'
    '[TimeControl "600+0"]\n'
    '[Link "https://www.chess.com/game/live/123456"]\n'
    "\n"
    "1. e4 e5 2. Nf3 Nc6 *"
)


def test_header_copy_pgn_and_pgn_json_script_present(client, new_schema_game_factory):
    """Copy PGN button and json_script tag appear when the game has a PGN (#226 C1).

    Parameters:
        client: Django test client.
        new_schema_game_factory: Factory producing a fully-derived game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="copy-pgn-btn"' in body
    assert 'Copy PGN' in body
    assert 'id="game-pgn-data"' in body


def test_header_chess_com_link_when_url_present(client, new_schema_game_factory):
    """'Open on Chess.com' button renders when the PGN contains a Link header (#226 C1).

    Parameters:
        client: Django test client.
        new_schema_game_factory: Factory producing a fully-derived game.
    """
    game = new_schema_game_factory()
    game.pgn = _PGN_WITH_LINK
    game.save()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Open on Chess.com" in body
    assert "chess.com/game/live/123456" in body


def test_header_chess_com_link_absent_when_no_url(client, new_schema_game_factory):
    """'Open on Chess.com' button is absent when PGN has no Link header (#226 C1).

    Parameters:
        client: Django test client.
        new_schema_game_factory: Factory producing a fully-derived game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Open on Chess.com" not in body


def test_header_trophy_renders_for_winner(client, new_schema_game_factory):
    """Trophy emoji appears in header when winner_username matches white player (#226 C1).

    Parameters:
        client: Django test client.
        new_schema_game_factory: Factory producing a fully-derived game.
    """
    game = new_schema_game_factory()
    game.winner_username = game.white_username  # Alice wins
    game.save()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "🏆" in body
    assert "winner-trophy" in body


def test_header_no_trophy_when_no_winner(client, new_schema_game_factory):
    """No trophy emoji when game has no winner_username set (#226 C1).

    Parameters:
        client: Django test client.
        new_schema_game_factory: Factory producing a fully-derived game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The trophy span only appears when a winner is set; the CSS class name is
    # in the <style> block regardless, so we check for the span element.
    assert '<span class="winner-trophy"' not in body


def test_header_opening_link_absent_when_no_opening(client, new_schema_game_factory):
    """Opening link is absent when game has no opening data (#226 C1 guard).

    Parameters:
        client: Django test client.
        new_schema_game_factory: Factory producing a fully-derived game.
    """
    game = new_schema_game_factory()
    # Fixture has no eco_code or opening FK, so opening_book_id will be None.
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The opening <a> element must be absent; the CSS class appears in <style> only.
    assert 'class="page-hero-opening"' not in body
    assert 'href="/openings/' not in body


def test_header_time_control_label_present(client, new_schema_game_factory):
    """Time-control label renders in the hero sub-line (#226 C1).

    The fixture has time_control="300+0" and no time_class (None), so
    format_time_control_label returns "5 min". The sub-line must contain
    the result · date · label structure.

    Parameters:
        client: Django test client.
        new_schema_game_factory: Factory producing a fully-derived game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games:analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The fixture time_control="300+0" → "5 min" (no time_class prefix).
    assert "5 min" in body
