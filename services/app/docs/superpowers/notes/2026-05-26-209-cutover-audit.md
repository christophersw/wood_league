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

**V1 code that reads from data object (games/views.py & games/board_builder.py):**
- `data.pgn` (views.py:219, 306; board_builder.py:662)
- `data.moves` (views.py:97, 212, 218; board_builder.py:565)
- `data.lc0_moves` (views.py:97; board_builder.py:567)
- `data.has_sf` (board_builder.py:671)
- `data.has_lc0` (board_builder.py:671)
- `data.white` (views.py:467; board_builder.py:545)
- `data.black` (views.py:467; board_builder.py:545)

**V2 GameAnalysisDataV2 attributes & properties:**
- `pgn` ✅ (line 89)
- `sf_moves` ✅ (line 98)
- `lc0_moves` ✅ (line 112)
- `has_sf` ✅ property (line 126)
- `has_lc0` ✅ property (line 131)
- `white` ✅ (line 84)
- `black` ✅ (line 85)

**Cross-reference with appliers (_apply_sf_summary, _apply_lc0_summary):**
- v1 `engine_depth` (services.py:74) → v2 `sf_engine_depth` (services_v2.py:109, applied line 240)

**Verdict:** ✅ All v1-read attributes are present in v2. No v1-only attributes detected. The v2 dataclass is structurally complete for cutover.

---

## Summary

- **Risk 4 (services.py deletion):** ✅ Safe. Only three documented consumers.
- **Risk 3 (arrow dict keys):** ⚠️ Keep `stroke_width` in arrow dict.
- **Risk 1 (v2 readiness):** ✅ All v1-read attributes available in v2.
