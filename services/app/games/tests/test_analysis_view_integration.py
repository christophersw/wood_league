"""
Title: test_analysis_view_integration.py — End-to-end analysis-view contract
Description:
    Drives the board-partial HTMX endpoint against a fixture game that has full
    SF + LC0 analysis data, parses the rendered frames JSON, and asserts that
    each engine's arrows carry a non-empty label. This is the integration test
    whose absence let the LC0-labels regression ship during the #208 live review.

    Intentionally RED on commit (Task 6 of #209): it asserts the post-cutover
    shape where board-frames-json frames are dicts with embedded `arrows` lists.
    On the current legacy code, board-frames-json frames are SVG strings — the
    `isinstance(frame, dict)` check fails with the human-readable message
    "legacy SVG string path still active". Task 7's view + template + JS cutover
    is what turns these tests green.

    Board partial URL: /_partials/games/<slug>/board/ (name="games_board_partial")
    Auth: view is gated by LoginRequiredMiddleware; tests use client.force_login().

Changelog:
    2026-05-26 (#209 Task 6): Initial — proves the v2 cutover delivers arrow
        labels end-to-end on the rendered HTTP response. Prevents a repeat of
        the #208 LC0-labels regression.
"""
import json
import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_fully_analysed_game():
    """Create a Game with SF + LC0 analysis including per-candidate WDL fields.

    Builds the game using the conftest helper functions (_make_game, _make_sf_analysis)
    and adds a Lc0GameAnalysis with one Lc0MoveAnalysis row that has both the played-move
    WDL triple (wdl_win/draw/loss) AND the per-candidate tier-1 WDL triple
    (wdl_win_1/draw_1/loss_1). Without the per-candidate fields, _lc0_candidate_delta_mu
    returns None and _arrow_label returns "" — reproducing the original label bug.

    Returns:
        Game: The saved game with SF analysis and LC0 analysis attached.
    """
    from datetime import datetime, timezone
    from uuid import uuid4
    from games.models import Game
    from analysis.models import GameAnalysis, MoveAnalysis, Lc0GameAnalysis, Lc0MoveAnalysis

    slug = uuid4().hex[:12]
    pgn = (
        '[Event "Test"]\n'
        '[Site "?"]\n'
        '[Date "2026.01.01"]\n'
        '[Round "1"]\n'
        '[White "Alice"]\n'
        '[Black "Bob"]\n'
        '[Result "*"]\n'
        '[TimeControl "300+0"]\n'
        "\n"
        "1. e4 e5 2. Nf3 Nc6 *"
    )
    game = Game.objects.create(
        id=slug,
        slug=slug,
        played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_control="300+0",
        white_username="Alice",
        black_username="Bob",
        white_rating=1500,
        black_rating=1500,
        result_pgn="1-0",
        pgn=pgn,
    )

    # SF analysis — ply 1 with cp_eval, arrow_cp_1, and derived fields.
    ga = GameAnalysis.objects.create(
        game=game,
        analyzed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        engine_depth=20,
        white_accuracy=85.0,
        black_accuracy=82.0,
        white_acpl=18.5,
        black_acpl=22.3,
        white_blunders=0,
        white_mistakes=0,
        white_inaccuracies=1,
        black_blunders=0,
        black_mistakes=0,
        black_inaccuracies=1,
    )
    fens = [
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
        "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
    ]
    # arrow_cp_1 = 65.0 > cp_eval = 20.0 → delta = +0.45 → label "+0.45"
    MoveAnalysis.objects.create(
        analysis=ga,
        ply=1,
        san="e4",
        fen=fens[1],
        cp_eval=20.0,
        mate_in=None,
        cpl=5.0,
        move_win_delta=-5.0,
        classification="best",
        arrow_uci_1="e2e4",
        best_move="e2e4",
        pv_san_1="e4",
        arrow_cp_1=65.0,
        wdl_win_adj=520,
        wdl_draw_adj=450,
        wdl_loss_adj=30,
    )

    # LC0 analysis — ply 1 with BOTH played-move WDL AND per-candidate WDL tier 1.
    # played mu  = (500 + 200/2) / 1000 = 0.60
    # candidate1 mu = (620 + 180/2) / 1000 = 0.71
    # delta = +0.11 → label "+11%"
    lga = Lc0GameAnalysis.objects.create(
        game=game,
        analyzed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        engine_nodes=800,
        network_name="BT4-1024x15x32h-swa-6147500",
        white_win_prob=0.58,
        white_draw_prob=0.30,
        white_loss_prob=0.12,
        black_win_prob=0.42,
        black_draw_prob=0.30,
        black_loss_prob=0.28,
        draw_rate_reference=0.30,
        wdl_calibration_elo=1500,
        contempt=0,
        white_accuracy=87.5,
        black_accuracy=84.2,
    )
    Lc0MoveAnalysis.objects.create(
        analysis=lga,
        ply=1,
        san="e4",
        fen=fens[1],
        # played-move WDL (raw, mover-frame)
        wdl_win=500,
        wdl_draw=200,
        wdl_loss=300,
        # per-candidate tier-1 WDL — required for _lc0_candidate_delta_mu to return non-None
        wdl_win_1=620,
        wdl_draw_1=180,
        wdl_loss_1=200,
        # derived fields (new-schema)
        wdl_win_adj=500,
        wdl_draw_adj=200,
        wdl_loss_adj=300,
        wdl_mu=0.60,
        delta_mu=0.0,
        delta_d=0.005,
        base_severity="best",
        draw_character="balanced",
        arrow_uci_1="e2e4",
        best_move="e2e4",
        pv_san_1="e4",
    )

    return game


@pytest.fixture
def fully_analysed_game(db):
    """Fixture: game with both SF and LC0 analysis, including per-candidate WDL.

    Parameters:
        db: Django pytest database fixture.

    Returns:
        Game: Saved game instance with SF + LC0 analysis attached.
    """
    return _make_fully_analysed_game()


@pytest.fixture
def auth_client(client, db):
    """Django test client pre-authenticated as a minimal test user.

    The board-partial view is gated by LoginRequiredMiddleware (AUTH_ENABLED
    defaults to True in the test environment). This fixture creates a throwaway
    user and logs in via force_login so the integration tests receive 200 rather
    than a 302 redirect to /auth/login/.

    Parameters:
        client: Django test client fixture.
        db: Django pytest database fixture.

    Returns:
        django.test.Client: Authenticated test client.
    """
    User = get_user_model()
    user = User.objects.create_user(
        email="testuser_integration@example.com",
        password="testpassword123",
    )
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_frames_json(html: str) -> list:
    """Extract and parse the board-frames-json script block from rendered HTML.

    Looks for the post-cutover script block that embeds frames as self-contained
    dicts with an ``arrows`` key. On the legacy path this block contains SVG
    strings; on the v2 path it contains dicts.

    Parameters:
        html (str): The full rendered HTML response body.

    Returns:
        list: Parsed JSON array from the board-frames-json script block.

    Raises:
        AssertionError: If the board-frames-json script block is not found.
    """
    match = re.search(
        r'<script[^>]+id="board-frames-json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "board-frames-json script block not found in board-partial response"
    return json.loads(match.group(1))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_board_partial_renders_frames_as_dicts(auth_client, fully_analysed_game):
    """Board partial renders frames as dicts (not raw SVG strings) after v2 cutover.

    On the legacy path, board-frames-json contains a JSON array of SVG strings.
    On the v2 path each entry is a dict with at least {svg, arrows}. This test
    asserts the post-cutover shape; it is intentionally RED on Task 6 commit.

    Parameters:
        auth_client: Authenticated Django test client (LoginRequiredMiddleware active).
        fully_analysed_game: Fixture game with SF + LC0 analysis.
    """
    url = reverse("games_board_partial", kwargs={"slug": fully_analysed_game.slug})
    response = auth_client.get(url)
    assert response.status_code == 200, (
        f"expected 200 from board_partial, got {response.status_code}"
    )
    frames = _extract_frames_json(response.content.decode())
    assert frames, "board-frames-json was empty"
    first_frame = frames[0]
    assert isinstance(first_frame, dict), (
        "frames must be dicts after v2 cutover — got "
        f"{type(first_frame).__name__} (legacy SVG string path still active)"
    )
    assert "arrows" in first_frame, (
        "each frame dict must carry an 'arrows' key after v2 cutover"
    )


def test_board_partial_renders_lc0_arrow_labels(auth_client, fully_analysed_game):
    """LC0 arrows in the rendered frames JSON carry non-empty labels end-to-end.

    This is the regression test for the #208 live-review bug where LC0 arrows
    had empty labels because _lc0_candidate_delta_mu returned None (missing
    wdl_win_1/draw_1/loss_1 per-candidate fields). After the v2 cutover (Task 7)
    this test must be green; it is intentionally RED on the Task 6 commit.

    Parameters:
        auth_client: Authenticated Django test client.
        fully_analysed_game: Fixture game with both SF and full LC0 WDL data,
            including wdl_win_1/draw_1/loss_1 per-candidate tier-1 WDL fields.
    """
    url = reverse("games_board_partial", kwargs={"slug": fully_analysed_game.slug})
    response = auth_client.get(url)
    assert response.status_code == 200
    frames = _extract_frames_json(response.content.decode())

    lc0_arrows = [
        arrow
        for frame in frames
        if isinstance(frame, dict)
        for arrow in frame.get("arrows", [])
        if arrow.get("engine") == "lc0"
    ]
    assert lc0_arrows, (
        "no LC0 arrows found in any frame — either the fixture has no LC0 data "
        "or the frames are still legacy SVG strings (v2 cutover not done)"
    )
    labelled = [a for a in lc0_arrows if a.get("label")]
    assert labelled, (
        "all LC0 arrows have empty labels — this is the #208 regression; "
        "check that wdl_win_1/draw_1/loss_1 per-candidate fields are set "
        "and that _lc0_candidate_delta_mu is wired into the view/template"
    )


def test_board_partial_renders_sf_arrow_labels(auth_client, fully_analysed_game):
    """SF arrows in the rendered frames JSON carry non-empty labels end-to-end.

    Companion to test_board_partial_renders_lc0_arrow_labels: ensures the SF
    label path (mover-relative cp delta) also survives the full view → template
    round-trip. Intentionally RED on the Task 6 commit.

    Parameters:
        auth_client: Authenticated Django test client.
        fully_analysed_game: Fixture game with SF analysis including arrow_cp_1
            different from cp_eval so the delta is non-zero.
    """
    url = reverse("games_board_partial", kwargs={"slug": fully_analysed_game.slug})
    response = auth_client.get(url)
    assert response.status_code == 200
    frames = _extract_frames_json(response.content.decode())

    sf_arrows = [
        arrow
        for frame in frames
        if isinstance(frame, dict)
        for arrow in frame.get("arrows", [])
        if arrow.get("engine") == "sf"
    ]
    assert sf_arrows, (
        "no SF arrows found in any frame — either the fixture has no SF data "
        "or the frames are still legacy SVG strings (v2 cutover not done)"
    )
    assert all(a.get("label") for a in sf_arrows), (
        "some SF arrows have empty labels — check that arrow_cp_1 != cp_eval "
        "in the fixture and that _arrow_label is wired into the view/template"
    )
