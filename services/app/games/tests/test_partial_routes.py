"""
Title: test_partial_routes.py — Route resolution for HTMX partials
Description:
    Parametrized tests verify that all seven new analysis partial routes
    resolve and return 200 for new-schema games. Legacy games return 404.
    Also contains content-level assertions for the SF cp, and LC0 WDL
    chart partials, and the PGN moves-strip chip shape (#212).

Changelog:
    2026-05-21 (#186): Initial — stub routes scaffolding.
    2026-05-21 (#186): Task 9 — add Win% partial content assertions.
    2026-05-21 (#186): Task 10 — add SF cp partial content assertions.
    2026-05-21 (#186): Task 11 — add LC0 WDL partial content assertions.
    2026-05-25 (#208): Task 2 — add THIS MOVE identity + score-delta test.
    2026-05-26 (#212): Task 4 — add five moves-strip characterization tests.
    2026-05-27 (#216): Task 8 — retire Win% chart; replace content test with 404 regression.
"""
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PARTIALS = [
    "games_card_sf_partial",
    "games_card_lc0_partial",
    "games_chips_partial",
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


def test_winpct_route_is_gone(client, new_schema_game_factory):
    """The winpct chart route is retired (#216)."""
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/charts/winpct/")
    assert resp.status_code == 404


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
    assert "How to read this chart" in body              # tooltip header (#216)
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
    assert "How to read this chart" in body               # tooltip header (#216)
    assert "lc0Wdl.js" in body                            # static JS reference


def test_chips_partial_has_move_label(client, new_schema_game_factory):
    """Chips partial header shows a 'Move N · Side' subject label derived from ply.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/chips/?ply=3")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Move 2 · White" in body      # ply 3 -> move (3+1)//2 = 2, odd -> White


def test_chips_partial_is_du_bois_plate(client, new_schema_game_factory):
    """Chips partial renders inside a wc-card plate titled 'This Move' with source prefixes.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/chips/?ply=3")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert 'class="wc-card move-chips-card"' in body
    assert "This Move" in body
    assert "move-chip__source" in body
    assert "border-radius: 999px" not in body


def test_chips_partial_no_longer_links_movechips_css(client, new_schema_game_factory):
    """Chip styling now ships in the global tailwind.css; the partial must not
    inject its own moveChips.css <link> (which never applied through the HTMX swap).

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/chips/?ply=3")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "moveChips.css" not in body
    assert "move-chip" in body  # chips still rendered


def test_this_move_partial_has_identity_and_score_deltas(client, new_schema_game_factory):
    """The THIS MOVE partial renders move identity and SF/LC0 score-delta chips.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/chips/?ply=2")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Move 1" in body          # ply 2 -> move (2+1)//2 = 1
    assert "Black" in body           # ply 2 is even -> Black moved
    # SF delta ply2 = cp_eval[2]-cp_eval[1] = -25-30 = -55 (White frame);
    # Black moved -> mover-relative +55cp -> +0.55 pawns
    assert "+0.55" in body
    # LC0 delta ply2 = delta_mu 0.044 * 100 = +4%
    assert "+4%" in body


def test_pgn_partial_renders_strip_and_js(client, new_schema_game_factory):
    """PGN partial must embed id="pgn-moves" (the chip strip) and reference pgnTable.js.

    Converted from test_pgn_partial_renders_table_and_js for #212 — the old
    <details>+<table> shape is replaced by the inline chip strip.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game with
            a 4-ply PGN (e4 e5 Nf3 Nc6).
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/pgn/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert 'id="pgn-moves"' in body      # strip nav element present
    assert 'id="pgn-panel"' in body      # collapsible <details> wrapper (#212 v2)
    # pgnTable.js is now loaded once from analysis.html's extra_js block, not
    # from inside this partial — so the partial body should NOT contain a
    # second <script src=…/pgnTable.js> tag. This guards against regressing
    # back to the in-partial loading that raced with HTMX swap timing.
    assert "pgnTable.js" not in body
    assert 'id="pgn-table"' not in body  # old table shape gone
    assert "pgn-tbody" not in body        # old tbody gone


# --- Moves-strip partial tests (#212) ---


def test_pgn_strip_renders_one_chip_per_move(client, new_schema_game_factory):
    """The new-schema 4-ply fixture produces 4 .moves-mv chips with data-ply 1..4.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games_pgn_partial", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    for ply in (1, 2, 3, 4):
        assert f'data-ply="{ply}"' in body, f"chip data-ply={ply} missing"
    # Strip-shape sanity checks. The strip class attribute now carries both
    # "moves-strip" and a default source token (moves-source--sf), so we
    # substring-match the base class rather than the literal attribute.
    assert 'id="pgn-moves"' in body
    assert "moves-strip" in body
    assert 'id="pgn-panel"' in body  # collapsible <details> wrapper (#212 v2)
    assert "moves-source--sf" in body  # default engine source (#212 v3)
    # Old table shape must be gone — be specific about which structure rather
    # than "no <details>" (the strip is itself wrapped in a <details> now).
    assert 'id="pgn-table"' not in body
    assert "pgn-tbody" not in body


def test_pgn_strip_emits_annotation_for_classified_moves(client, new_schema_game_factory):
    """A row classified 'inaccuracy' produces a move-annotation-inaccuracy span.

    The new-schema fixture classifies ply 4 as 'inaccuracy' (SF moves_data in conftest.py).

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games_pgn_partial", args=[game.slug]))
    body = resp.content.decode()
    assert "move-annotation-inaccuracy" in body
    assert ">?!<" in body  # canonical symbol from move_annotations.ANNOTATIONS


def test_pgn_strip_omits_annotation_for_unclassified_moves(client, new_schema_game_factory):
    """A row classified 'best' (no badge) produces no move-annotation span for that ply.

    The fixture has classifications best/best/great/inaccuracy at plies 1/2/3/4
    for BOTH SF and LC0 (LC0 base_severity mirrors SF in the fixture). Since the
    moves strip now server-renders BOTH engine badges per chip (#212 v3 — JS
    flips visibility via the .moves-source--{sf,lc0} class), plies 3 and 4
    each emit two badge spans (one SF + one LC0) — total = 4. The semantic
    invariant being tested is unchanged: "best" plies (1 + 2) still produce
    zero annotation spans, only badged plies do.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(reverse("games_pgn_partial", args=[game.slug]))
    body = resp.content.decode()
    # Plies 1 + 2 = "best" → 0 spans. Plies 3 + 4 each emit one SF + one LC0
    # badge span (the LC0 one is hidden by default CSS until JS toggles source).
    # Total = 4 badge spans on body.
    assert body.count('class="move-annotation') == 4


def test_pgn_strip_renders_empty_placeholder_when_no_moves(client, simple_pgn_game):
    """A game with no new-schema analysis returns 404 from the pgn_partial view.

    The view calls _load_or_404 which raises Http404 when get_game_analysis_v2
    returns None (no new-schema analysis exists for this game).

    Params:
        client: Django test client fixture.
        simple_pgn_game: Fixture producing a game with no analysis rows.
    """
    # simple_pgn_game has no SF/LC0 analysis rows, so _load_or_404 raises Http404.
    resp = client.get(reverse("games_pgn_partial", args=[simple_pgn_game.slug]))
    assert resp.status_code == 404


def test_pgn_strip_uses_ellipsis_prefix_for_leading_black_move(client, new_schema_game_factory):
    """A PGN whose first move is Black's renders the move-number prefix with an ellipsis.

    When game.pgn is replaced with a mid-position PGN that starts on Black's turn,
    the view still has analysis (new-schema) but walks the modified game.pgn field.
    The first move chip should use the '1...' or '1…' form rather than '1.'.

    Note: the view reads data.pgn from get_game_analysis_v2, which returns the
    game model's pgn field — so saving a new pgn to the game instance is enough.

    Params:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    game.pgn = (
        '[Event "Mid-position"]\n'
        '[Site "?"]\n'
        '[Date "2026.01.01"]\n'
        '[Round "1"]\n'
        '[White "Alice"]\n'
        '[Black "Bob"]\n'
        '[Result "*"]\n'
        '[SetUp "1"]\n'
        '[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]\n'
        '\n1... e5 *'
    )
    game.save()
    resp = client.get(reverse("games_pgn_partial", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The chip's class attribute is now a multi-class string (move-chip moves-mv
    # move-annotation-{cls}), so substring-match on " moves-mv " catches it
    # without depending on class ordering.
    assert " moves-mv " in body
    # The first (and only) move-number span must use the ellipsis form.
    assert "1…" in body or "1..." in body
