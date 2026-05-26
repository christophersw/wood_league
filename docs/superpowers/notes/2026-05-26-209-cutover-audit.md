# Issue #209 Cutover Audit — 2026-05-26

## services.py consumers

**Grep results (services.py imports):**
```
games/board_builder.py:45:from games.services import GameAnalysisData, MoveRow
games/tests.py:23:from games.services import GameAnalysisData, MoveRow
games/views.py:41:from games.services import MoveRow, get_game_analysis
```

**Verdict:** ✅ Matches spec exactly. Three consumers: board_builder.py:45, tests.py:23, views.py:41. No surprises.

---

## stroke_width usage

**Grep results (stroke_width in templates/games/*.js and templates/games/*.html):**
```
templates/games/_board_partial.html:65:.board-arrow-label{...stroke-width:3px...}
templates/games/_board_partial.html:237:   * @param {number} strokeWidth - Visible shaft width.
templates/games/_board_partial.html:240:  function buildArrowGeometry(fromPoint, toPoint, strokeWidth) {
templates/games/_board_partial.html:250:    var headLength = Math.max(13, strokeWidth * 2.0);
templates/games/_board_partial.html:251:    var headWidth = Math.max(12, strokeWidth * 1.7);
templates/games/_board_partial.html:292:    var strokeWidth = Number(arrowData.stroke_width || 7);
templates/games/_board_partial.html:293:    var geometry = buildArrowGeometry(fromPoint, toPoint, strokeWidth);
templates/games/_board_partial.html:324:    hitbox.setAttribute('stroke-width', Math.max(strokeWidth + 16, 22));
templates/games/_board_partial.html:336:    shaft.setAttribute('stroke-width', strokeWidth);
```

**Key finding:** Line 292 reads `arrowData.stroke_width` directly from the arrow dict passed to the JavaScript function.

**Verdict:** ⚠️ Task 4 must keep `stroke_width` in arrow dict. The JS will break if that key is removed.

---

## Engine-line attributes

**Functions present on `main` (this branch's base):** `engine_line_partial` (views.py:~277) and `_engine_row_for_request` (views.py:97). The plan also references `_engine_line_bot_label` and `_engine_line_player_meta` — those were added on `issue/208-restyle-game-analysis-page` and **do not exist on main**. Task 8's helper-re-type instructions are therefore moot on this branch; only the loader-call swap inside `engine_line_partial` applies. When #208 later rebases on top of #209, the rebase will replay those helpers and they'll need v2 types then — that's #208's problem to handle.

**V1 attributes read by engine_line_partial & _engine_row_for_request (views.py:277, 97):**
- `data.moves` (Stockfish move rows; read at views.py:277, 97)
- `data.lc0_moves` (LC0 move rows; read at views.py:97)
- `data.pgn` (game PGN string; read at views.py:277)

**V2 GameAnalysisDataV2 equivalents:**
| v1 attribute | v2 attribute | Notes |
|---|---|---|
| `data.moves` | `data.sf_moves` | Rename from generic `moves` to explicit `sf_moves` |
| `data.lc0_moves` | `data.lc0_moves` | No rename |
| `data.pgn` | `data.pgn` | No rename |

**Verdict:** ⚠️ Attribute rename required in Task 8: `data.moves` → `data.sf_moves`. The engine-line handler's `_engine_row_for_request` function (line 97) directly reads `data.moves` for Stockfish rows and `data.lc0_moves` for LC0 rows. Re-typing alone is insufficient; line 97 must rewrite the move-row accessor to use `sf_moves` when engine=="sf".

---

## Summary

- **Risk 4 (services.py deletion):** ✅ Safe. Only three documented consumers.
- **Risk 3 (arrow dict keys):** ⚠️ Keep `stroke_width` in arrow dict.
- **Risk 1 (v2 readiness):** ⚠️ Attribute rename required in Task 8: `data.moves` → `data.sf_moves` inside `_engine_row_for_request` (views.py:97). `data.lc0_moves` and `data.pgn` carry over unchanged. The plan's `_engine_line_bot_label` / `_engine_line_player_meta` re-type steps do not apply on this branch (those helpers live on `issue/208-…`, not on `main`).
