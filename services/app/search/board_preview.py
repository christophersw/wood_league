"""
Title: board_preview.py — Animated board snippet for the search modal
Description:
    Builds the interactive animated chess board HTML/CSS/JS injected into the
    search-results modal. Extracted from search.views so views.py stays under
    the project Halstead-effort gate.
Changelog:
    2026-05-20: Initial extraction from search/views.py (#162 follow-up).
"""

import io
import json

import chess.pgn
import chess.svg

_CSS = """
<style>
#chess-anim-preview{width:340px;font-family:monospace;}
#cap-board-frame svg{display:block;}
#cap-controls{margin-top:6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap;}
#cap-btn-pp{padding:2px 10px;cursor:pointer;font-size:13px;border:1px solid #1A1A1A;background:transparent;}
#cap-btn-pp:hover{background:#1A1A1A;color:#F2E6D0;}
#cap-scrubber{flex:1;cursor:pointer;accent-color:#D4A843;}
#cap-frame-lbl{font-size:11px;color:#8B3A2A;min-width:60px;text-align:right;}
</style>
"""

_MARKUP = """
<div id="chess-anim-preview">
  <div id="cap-board-frame"></div>
  <div id="cap-controls">
    <button id="cap-btn-pp" onclick="capToggle()">&#9646;&#9646;</button>
    <input id="cap-scrubber" type="range" min="0" max="__MAX__" value="0" oninput="capScrub(this.value)"/>
    <span id="cap-frame-lbl">Start</span>
  </div>
</div>
"""

# Uses __FRAMES__ / __INTERVAL__ placeholders so the JS string contains no
# format-brace tokens. window.__capTimer is shared across modal opens so a
# reopen tears down the previous interval (prevents racing animations).
_JS = """
<script>
(function(){
  if(window.__capTimer){clearInterval(window.__capTimer);window.__capTimer=null;}
  const frames=__FRAMES__;
  let idx=0,playing=true;
  function render(){
    const frame=document.getElementById('cap-board-frame');
    if(!frame){
      if(window.__capTimer){clearInterval(window.__capTimer);window.__capTimer=null;}
      return;
    }
    frame.innerHTML=frames[idx];
    document.getElementById('cap-scrubber').value=idx;
    document.getElementById('cap-frame-lbl').textContent=idx===0?'Start':'Ply '+idx;
  }
  function advance(){idx=(idx+1)%frames.length;render();}
  window.__capTimer=setInterval(advance,__INTERVAL__);
  window.capScrub=function(v){idx=parseInt(v);render();};
  window.capToggle=function(){
    playing=!playing;
    const btn=document.getElementById('cap-btn-pp');
    if(playing){window.__capTimer=setInterval(advance,__INTERVAL__);btn.innerHTML='&#9646;&#9646;';}
    else{clearInterval(window.__capTimer);window.__capTimer=null;btn.innerHTML='&#9654;';}
  };
  render();
})();
</script>
"""


def _render_frames(pgn_text):
    """Parse PGN and return one SVG string per ply (including start position).

    Args:
        pgn_text: Raw PGN string.

    Returns:
        List of SVG strings; empty list if PGN is empty or unparseable.
    """
    if not pgn_text:
        return []
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return []
    board = game.board()
    frames = [chess.svg.board(board, size=340)]
    for move in game.mainline_moves():
        board.push(move)
        frames.append(chess.svg.board(board, lastmove=move, size=340))
    return frames


def render_animation_html(pgn_text, interval_ms=700):
    """Build the animated-board HTML snippet for the search modal.

    Args:
        pgn_text: Raw PGN string.
        interval_ms: Auto-advance interval in milliseconds.

    Returns:
        HTML/CSS/JS string ready to inject. Empty string if PGN unparseable;
        a single static SVG if the game has no moves.
    """
    frames = _render_frames(pgn_text)
    if not frames:
        return ""
    if len(frames) == 1:
        return frames[0]
    markup = _MARKUP.replace("__MAX__", str(len(frames) - 1))
    script = (
        _JS.replace("__FRAMES__", json.dumps(frames))
           .replace("__INTERVAL__", str(interval_ms))
    )
    return _CSS + markup + script
