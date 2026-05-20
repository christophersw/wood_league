"""
Title: views.py — Search interface views and HTMX handlers
Description:
    View functions for rendering the search interface and handling HTMX partial
    requests for AI search, keyword search, and animated board previews.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-20: Thread current_user_username into AI prompt; add game_modal_partial;
                enrich result rows with hydrated Game fields (#162).
"""

import io
import json

import chess.pgn
import chess.svg
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.services import resolve_current_player
from games.models import Game
from players.models import Player
from search.services import (
    SearchPlanError,
    execute_sql_search,
    generate_search_plan,
    is_ai_available,
    keyword_game_search,
)


def search_index(request):
    """Render search page with AI availability status."""
    return render(request, "search/index.html", {
        "ai_available": is_ai_available(),
    })


@require_POST
def ai_search_partial(request):
    """Execute AI-generated SQL search from natural language query (HTMX partial).

    Threads the current logged-in player's username into the AI prompt so the
    model can personalise queries like "my recent losses".

    Args:
        request: HttpRequest with POST field ``query``.

    Returns:
        Rendered ``search/partials/results.html`` with enriched rows or an
        error message.
    """
    query = request.POST.get("query", "").strip()
    if not query:
        return render(request, "search/partials/results.html", {
            "error": "Please enter a search query.",
            "results": [],
            "debug": settings.DEBUG,
        })
    player = resolve_current_player(request.user)
    current_user_username = player.username if player else None
    try:
        plan = generate_search_plan(
            query, current_user_username=current_user_username,
        )
        rows = execute_sql_search(plan.sql_query)
        return render(request, "search/partials/results.html", {
            "results": _enrich(_normalise(rows)),
            "sql": plan.sql_query,
            "reasoning": plan.reasoning,
            "debug": settings.DEBUG,
            "club_usernames": _club_usernames(),
        })
    except SearchPlanError as exc:
        return render(request, "search/partials/results.html", {
            "error": str(exc),
            "sql": exc.candidate_sql,
            "reasoning": exc.reasoning,
            "results": [],
            "debug": settings.DEBUG,
        })
    except Exception as exc:
        return render(request, "search/partials/results.html", {
            "error": str(exc),
            "results": [],
            "debug": settings.DEBUG,
        })


@require_POST
def keyword_search_partial(request):
    """Search games by keyword in player names and opening names (HTMX partial).

    Args:
        request: HttpRequest with POST field ``query``.

    Returns:
        Rendered ``search/partials/results.html`` with enriched rows or an
        error message.
    """
    query = request.POST.get("query", "").strip()
    if not query:
        return render(request, "search/partials/results.html", {
            "error": "Please enter a keyword.",
            "results": [],
            "debug": settings.DEBUG,
        })
    rows = keyword_game_search(query, limit=200)
    return render(request, "search/partials/results.html", {
        "results": _enrich(rows),
        "debug": settings.DEBUG,
        "club_usernames": _club_usernames(),
    })


def _normalise(rows: list[dict]) -> list[dict]:
    """Ensure each row has slug, game_id, and played_at string."""
    out = []
    for row in rows:
        r = dict(row)
        # Normalize id → game_id
        if "id" in r and "game_id" not in r:
            r["game_id"] = r.pop("id")
        # Coerce played_at to string
        pt = r.get("played_at")
        if pt and hasattr(pt, "strftime"):
            r["played_at"] = pt.strftime("%Y-%m-%d")
        elif pt:
            r["played_at"] = str(pt)[:10]
        # Merge opening columns
        r.setdefault("opening", r.get("lichess_opening") or r.get("opening_name") or "")
        out.append(r)
    return out


def game_modal_partial(request, game_id):
    """Render the game preview modal body (HTMX partial).

    Args:
        request: HttpRequest (GET).
        game_id: Primary key of the Game to display.

    Returns:
        Rendered ``search/partials/game_modal.html`` with game context, or a
        404 plain-text response if the game does not exist.
    """
    try:
        game = Game.objects.select_related(
            "opening", "analysis", "lc0_analysis",
        ).get(id=game_id)
    except Game.DoesNotExist:
        return HttpResponse(
            "<p class='font-mono text-xs text-slate'>Game not found.</p>",
            status=404,
        )
    pgn_text = (game.pgn or "").strip()
    board_html = _board_animation_html(pgn_text)
    return render(request, "search/partials/game_modal.html", {
        "game": game,
        "board_html": board_html,
        "club_usernames": _club_usernames(),
        "sf": getattr(game, "analysis", None),
        "lc": getattr(game, "lc0_analysis", None),
    })


def _club_usernames() -> dict[str, str]:
    """Return a map of {username: display_name} for all known club Players.

    Returns:
        dict mapping username strings to display name strings.
    """
    return dict(Player.objects.values_list("username", "display_name"))


def _enrich(rows):
    """Hydrate result rows with Game-derived fields the new table needs.

    Looks up Game objects for all row game_ids in a single query and merges
    fields including time control, opening, move count, ratings, and per-side
    engine accuracies.

    Args:
        rows: List of dict rows, each expected to have a ``game_id`` key.

    Returns:
        List of dicts with additional Game fields merged in where available.
    """
    if not rows:
        return rows
    ids = [r["game_id"] for r in rows if r.get("game_id")]
    if not ids:
        return rows
    games = {
        g.id: g
        for g in Game.objects.filter(id__in=ids).select_related(
            "opening", "analysis", "lc0_analysis",
        )
    }
    return [_merge_row(r, games.get(r.get("game_id"))) for r in rows]


def _merge_row(row, game):
    """Merge fields from a hydrated Game onto a result row dict.

    Args:
        row: Mutable dict from a search result row.
        game: Game instance to pull fields from, or None if not found.

    Returns:
        The row dict with additional Game fields set (mutated in-place and
        returned).
    """
    if game is None:
        return row
    sf = getattr(game, "analysis", None)
    lc = getattr(game, "lc0_analysis", None)
    row.update({
        "time_control_base_s": game.time_control_base_s,
        "time_control_increment_s": game.time_control_increment_s,
        "time_control": game.time_control or "",
        "opening_id": game.opening_id,
        "opening_name": game.lichess_opening or game.opening_name or "",
        "pgn": game.pgn or "",
        "winner_username": game.winner_username or "",
        "white_rating": game.white_rating,
        "black_rating": game.black_rating,
        "result_pgn": game.result_pgn or "",
        "move_count": _move_count(game.pgn or ""),
        "sf_white": getattr(sf, "white_accuracy", None),
        "sf_black": getattr(sf, "black_accuracy", None),
        "lc0_white": getattr(lc, "white_accuracy", None),
        "lc0_black": getattr(lc, "black_accuracy", None),
    })
    return row


def _move_count(pgn_text):
    """Return number of full moves (pairs) parsed from ``pgn_text`` or None.

    Args:
        pgn_text: Raw PGN string for a game.

    Returns:
        Integer count of full moves, or None if the PGN is empty or unparseable.
    """
    if not pgn_text:
        return None
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:  # noqa: BLE001 — defensive
        return None
    if game is None:
        return None
    plies = sum(1 for _ in game.mainline_moves())
    return (plies + 1) // 2


def _board_animation_html(pgn_text: str, interval_ms: int = 700) -> str:
    """Generate interactive animated board HTML with SVG frames from PGN."""
    if not pgn_text:
        return ""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return ""
    board = game.board()
    frames = [chess.svg.board(board, size=340)]
    for move in game.mainline_moves():
        board.push(move)
        frames.append(chess.svg.board(board, lastmove=move, size=340))
    if len(frames) <= 1:
        return frames[0] if frames else ""

    frames_json = json.dumps(frames)
    total = len(frames)
    return f"""
<style>
#chess-anim-preview{{width:340px;font-family:monospace;}}
#cap-board-frame svg{{display:block;}}
#cap-controls{{margin-top:6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;}}
#cap-btn-pp{{padding:2px 10px;cursor:pointer;font-size:13px;border:1px solid #1A1A1A;background:transparent;}}
#cap-btn-pp:hover{{background:#1A1A1A;color:#F2E6D0;}}
#cap-scrubber{{flex:1;cursor:pointer;accent-color:#D4A843;}}
#cap-frame-lbl{{font-size:11px;color:#8B3A2A;min-width:60px;text-align:right;}}
</style>
<div id="chess-anim-preview">
  <div id="cap-board-frame"></div>
  <div id="cap-controls">
    <button id="cap-btn-pp" onclick="capToggle()">&#9646;&#9646;</button>
    <input id="cap-scrubber" type="range" min="0" max="{total - 1}" value="0" oninput="capScrub(this.value)"/>
    <span id="cap-frame-lbl">Start</span>
  </div>
</div>
<script>
(function(){{
  const frames={frames_json};
  let idx=0,playing=true;
  let timer=setInterval(advance,{interval_ms});
  function render(){{
    document.getElementById('cap-board-frame').innerHTML=frames[idx];
    document.getElementById('cap-scrubber').value=idx;
    document.getElementById('cap-frame-lbl').textContent=idx===0?'Start':'Ply '+idx;
  }}
  function advance(){{idx=(idx+1)%frames.length;render();}}
  window.capScrub=function(v){{idx=parseInt(v);render();}};
  window.capToggle=function(){{
    playing=!playing;
    const btn=document.getElementById('cap-btn-pp');
    if(playing){{timer=setInterval(advance,{interval_ms});btn.innerHTML='&#9646;&#9646;';}}
    else{{clearInterval(timer);btn.innerHTML='&#9654;';}}
  }};
  render();
}})();
</script>
"""
