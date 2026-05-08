"""Views for game search interface (AI-powered and keyword search)."""

import io
import json

import chess.pgn
import chess.svg
from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from games.models import Game
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
    """Execute AI-generated SQL search from natural language query (HTMX partial)."""
    query = request.POST.get("query", "").strip()
    if not query:
        return render(request, "search/partials/results.html", {
            "error": "Please enter a search query.",
            "results": [],
        })
    try:
        plan = generate_search_plan(query)
        results = execute_sql_search(plan.sql_query)
        return render(request, "search/partials/results.html", {
            "results": _normalise(results),
            "sql": plan.sql_query,
            "reasoning": plan.reasoning,
        })
    except SearchPlanError as exc:
        return render(request, "search/partials/results.html", {
            "error": str(exc),
            "sql": exc.candidate_sql,
            "reasoning": exc.reasoning,
            "results": [],
        })
    except Exception as exc:
        return render(request, "search/partials/results.html", {
            "error": str(exc),
            "results": [],
        })


@require_POST
def keyword_search_partial(request):
    """Search games by keyword in player names and opening names (HTMX partial)."""
    query = request.POST.get("query", "").strip()
    if not query:
        return render(request, "search/partials/results.html", {
            "error": "Please enter a keyword.",
            "results": [],
        })
    results = keyword_game_search(query, limit=200)
    return render(request, "search/partials/results.html", {"results": results})


def board_preview_partial(request, game_id):
    """Render animated board preview for a single game (HTMX partial)."""
    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return HttpResponse("<p class='font-mono text-xs text-slate'>Game not found.</p>")

    pgn_text = (game.pgn or "").strip()
    board_html = _board_animation_html(pgn_text)
    return render(request, "search/partials/board_preview.html", {
        "game": game,
        "board_html": board_html,
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
