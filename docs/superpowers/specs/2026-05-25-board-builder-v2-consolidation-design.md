# Board Builder v2 Consolidation — Design Spec

**Issue:** [#209](https://github.com/christophersw/wood_league/issues/209) (label `upgrade`, milestone v1)
**Branch:** `issue/209-consolidate-build-board-frames-v2-signature` (off `main`)
**Date:** 2026-05-25
**Supersedes:** the "LC0 arrow labels still missing" live-review item on [#208](https://github.com/christophersw/wood_league/issues/208).

## Goal

Replace the dual-signature `games.board_builder.build_board_frames` and the parallel v1/v2 service layers with a single end-to-end v2 path. The live LC0-label rendering bug surfaced during #208 live review is a *side effect* of this refactor: once the analysis view consumes the v2 board path, LC0 labels render correctly because the WDL-derived label code shipped on #208 (`_lc0_candidate_delta_mu`, `_arrow_label`) is finally reachable.

## Why

`build_board_frames` accepts two completely different call shapes (legacy positional `data` argument vs. v2 keyword-args `pgn`/`sf_moves`/`lc0_moves`), routed internally on which args were passed. The analysis view at `games/views.py:209` still uses the legacy signature; the rest of the view (SF/LC0 cards, charts at `views.py:175` and `views.py:570`) has already migrated to `get_game_analysis_v2`.

This bit us during #208: arrow-label work landed in the v2 branch (which our unit tests exercise) but the live view never enters that branch, so the LC0 arrow labels look correct in tests and missing in the browser. The same trap will catch the next contributor unless we cut over.

## End-state contract

### Service layer

New thin loader in `services_v2.py`:

```python
def load_board_inputs(game: Game) -> tuple[str, list[SfMoveRow], list[Lc0MoveRow]]:
    """Return (pgn, sf_moves, lc0_moves) for the analysis-page board builder.

    Wraps the existing v2 loaders so the view doesn't have to know about
    _sf_rows / _lc0_rows / _load_analyses internals.
    """
```

`get_game_analysis_v2(slug)` continues to be the entry point for everything else.

### Builder signature

Single signature — the legacy positional `data` overload is deleted:

```python
def build_board_frames(
    pgn: str,
    sf_moves: list[SfMoveRow],
    lc0_moves: list[Lc0MoveRow],
    *,
    orientation: Literal["white", "black"] = "white",
    size: int = 480,
) -> BoardFramesResult: ...
```

### Output shape

```python
{
    "frames": [
        {
            "svg": "<svg>…</svg>",          # rendered per ply (server keeps tinting last-move squares)
            "arrows": [<arrow_dict>, …],    # arrows live IN their frame; no sidecar arrows_by_ply
            "ply": int,                     # 0 = start position
            "san": str | None,              # SAN of the move that produced this frame; None for ply 0
            "last_move_uci": str | None,    # 4-char UCI; None for ply 0
            "classification": str | None,   # SF classification of the played move ("best"|…|"blunder"); None when SF absent
        },
        …
    ],
    "overlay_geometry": {…},                # constant per game (depends on size)
    # Player-layout keys are flat at top level (not nested), matching the legacy
    # template contract so the cutover needs no template variable-name churn.
    "top_player":    str | None,
    "top_sym":       str,                   # "♔" / "♚"
    "top_side":      "White" | "Black",
    "bottom_player": str | None,
    "bottom_sym":    str,
    "bottom_side":   "White" | "Black",
    "has_sf":        bool,
    "has_lc0":       bool,
    "san_list":      list[str],             # convenience: SAN per ply (excluding start frame)
    "total_frames":  int,                   # convenience: len(frames)
}
```

Top-level key dropped vs. legacy: sidecar `arrows_by_ply` (arrows now live in `frames[i]["arrows"]`). `san_list` and `total_frames` are kept as convenience aggregations the template still reads (slider max, PGN-sync). `arrow_data_json` context key, the `board-arrows-json` script block, and the `is_best_json` / `board-isbest-json` and `board-san-json` dead blocks were also removed (the latter two in PR #210 review cleanup — they were unread by any JS).

### Per-arrow dict (tightened)

```python
{
    "engine": "sf" | "lc0",
    "uci":    str,        # 4-char UCI
    "tier":   1 | 2 | 3,
    "label":  str,        # "+0.45" (SF, pawns) | "+11%" (LC0, win-% delta) | "" when unavailable
    "color":  str,        # hex; engine base colour
    "opacity": float,     # 0.42..0.98; encodes tier + delta magnitude
}
```

Fields dropped vs. legacy: `from_sq`, `to_sq` (JS slices UCI), `engine_label` ("Stockfish"/"Lc0" — JS maps from `engine`), `move_uci` (duplicate of `uci`), `title` (JS composes it), `stroke_width` (unused — verify and drop), `delta`/`delta_text` (replaced by `label`), `request_ply` (frame already knows its `ply`).

### Edge cases (match existing v2-handler pattern)

- `get_game_analysis_v2(slug)` returns `None` → 404 from the view, same as the cards/charts handlers do today.
- One engine missing (rows == []) → that engine's arrows simply don't appear; frames render from PGN; `has_sf` / `has_lc0` flag what's available.
- Empty PGN / no moves → single start-position frame with `arrows: []`.

## Migrations required

### `games/views.py`

- **`views.py:209`** (analysis page): replace `get_game_analysis` + legacy `build_board_frames(data, …)` with:
  ```python
  game = get_object_or_404(Game, slug=slug)  # or existing equivalent
  pgn, sf_moves, lc0_moves = load_board_inputs(game)
  board_data = build_board_frames(pgn, sf_moves, lc0_moves, orientation=orientation, size=480)
  ```
  Also fetch `get_game_analysis_v2(slug)` for the surrounding view context (cards/summaries) — match the existing handlers.
- **`views.py:463`** (engine-line partial): swap `get_game_analysis(slug)` → `get_game_analysis_v2(slug)`. Re-type `_engine_line_bot_label(engine, data)` and `_engine_line_player_meta` parameter from `GameAnalysisData` to `GameAnalysisDataV2`; verify attribute names (`data.engine_depth`, `data.sf_nodes`, `data.lc0_nodes`, etc.) exist on the v2 dataclass. If `_apply_sf_summary` / `_apply_lc0_summary` don't already populate them, extend the v2 appliers — do not invent v1-only attributes.
- **View helpers around lines 88, 108, 402** typed `data: GameAnalysisData` / `MoveRow`: re-type to `GameAnalysisDataV2` and the equivalent v2 row type; mypy will surface attribute mismatches.

### `templates/games/_board_partial.html`

- Replace the `arrow_data_json` script block (currently emits `arrows_by_ply` keyed by ply) with `frames_json` — the entire frames array. Provide the player-layout and overlay-geometry in their own small JSON blocks (or as data attributes) as today.
- JS changes:
  - `arrowsByPly = JSON.parse(...)` → `frames = JSON.parse(...)`; for the current `ply`, the arrows are `frames[ply].arrows`.
  - `arrowData.from_sq` / `arrowData.to_sq` → `arrowData.uci.slice(0,2)` / `arrowData.uci.slice(2,4)`.
  - Compose `title` in JS from `engine` + `tier` + `label`: `` `${displayName(engine)} #${tier}: ${uci}${label ? ` (${label})` : ""}` `` where `displayName({sf:"Stockfish", lc0:"Lc0"})`.
  - The frame's `svg` string still goes into the board container as today; no change to the SVG rendering path.

### Deletions in the same PR

- `games/board_builder.py`: the legacy positional branch of `build_board_frames`, plus every helper exclusive to it — `_build_tier_map`, `_build_arrow_entries_for_engine`, `_resolve_tier_entries`, `_legacy_tier_context`, `_legacy_frame_loop`, `_player_layout` (legacy), `_build_single_arrow_entry`, `_format_arrow_delta`, `_compute_arrow_delta`. `_build_arrow_opacity` and `_mover_relative_score` are retained — they're shared with the v2 path. `_arrow_entries_from_row` is extended in this PR to emit the tightened arrow dict (add `color` from `_ENGINE_BASE_COLORS`, `opacity` from `_build_arrow_opacity`).
- `games/services.py`: `get_game_analysis`, `GameAnalysisData`, `MoveRow`, `_load_sf`, `_load_lc0`, `_lc0_move_rows`, `_lc0_summary_kwargs`. Audit the file before deletion — if any function is reused by `services_v2.py` (e.g. an opening-id helper), move it into v2 first. If nothing remains in `services.py` after the deletion, delete the file.
- `games/tests.py` — the dead-shadowed legacy test file ([[games_tests_shadowed]] memory). It tests only legacy-shape behavior and is not discovered by pytest under the current layout. Verify no other file imports from it, then delete.
- Sidecar `arrows_by_ply` plumbing everywhere it's referenced (template script block, JS, any test fixtures).

## Testing strategy

- **Extend v2 unit tests in `games/tests/`** to assert the new top-level shape (`frames[i]["arrows"]`) and the tightened arrow-dict fields (`color`, `opacity` present; `from_sq`/`to_sq`/`title` absent). Update existing arrow-label tests to read `frames[ply]["arrows"][0]` consistently.
- **New integration test** — the missing-test that let this bug ship. Drive the analysis-page view end-to-end against a fixture game that has full LC0 WDL data, render the response, parse the `frames_json` script block, and assert that at least one frame's `arrows` list contains an entry with `engine == "lc0"` and a non-empty `label`. Lives in `games/tests/test_analysis_view_integration.py`.
- **Engine-line partial characterization tests** (already exist after #208 Task 5) re-run against the v2-typed handler; they continue to pass without changes if `_apply_sf_summary` / `_apply_lc0_summary` already populate the attributes `_engine_line_bot_label` reads.
- **Quality gate** (per `feedback_quality_gate`): ruff → bandit + semgrep → radon / xenon → mypy → pytest + cov. mypy is the critical safety net for the type re-hint pass on the view helpers.

## Risks

1. **`views.py:463` attribute audit.** The engine-line handler reads attributes off `GameAnalysisData` that may or may not exist on `GameAnalysisDataV2` (e.g. `engine_depth`). Mitigation: re-type the helper parameter first and let mypy surface every missing attribute before we run the page. If a v1-only attribute turns out to be needed, extend the v2 applier — don't paper over with `getattr` defaults.
2. **Template/JS parse-time regression.** Reshaping the `<script type="application/json">` block is the kind of change that silently breaks the JS if a single key is mis-renamed. Mitigation: the new integration test parses the rendered HTML for the frames JSON and asserts shape, so a typo on either side fails the gate.
3. **`stroke_width` field on legacy arrow dict.** I called it likely-unused but didn't verify. Implementation Task 1 must grep the JS for `stroke_width` / `strokeWidth` before dropping it; if it's read, keep it on the arrow dict.
4. **Other `services.py` consumers.** I audited views.py, board_builder.py, and tests/ — only views.py and the legacy board path consume v1. Implementation Task 1 must repeat the audit with `grep -rn "from games.services\b\|games\.services\."` to catch anything I missed (e.g. management commands, API serializers).

## Out of scope

- Migrating any non-board view handler. The cards/charts handlers are already on v2 and stay there; no behavioral change.
- Client-side last-move tinting (the (q) option discussed during brainstorming). Frames stay server-rendered. If payload size becomes an issue, file a separate perf-focused upgrade.
- Reshaping `GameAnalysisDataV2` itself or its summary appliers, beyond adding any attribute the engine-line handler needs (risk #1).
- Anything cosmetic on the analysis page (chips, cards, hero, charts, PGN panel). Those are #208's scope and stay there.

## Acceptance criteria

1. `games/views.py` no longer imports from `games.services`. The only board entry point is `services_v2.load_board_inputs` + `board_builder.build_board_frames(...)` with the keyword-only signature.
2. `build_board_frames` has one signature; calling the old positional shape raises `TypeError` (not a quiet routing miss).
3. Live analysis page: LC0 (blue) arrows render with `+N%` labels; SF (tobacco) arrows render with `±X.XX` pawn labels; both reflect delta-vs-played.
4. Full gate green (ruff, bandit, radon/xenon, mypy, pytest with coverage no worse than baseline).
5. New integration test fails when reverted to the legacy path — i.e. it actually proves the bug it was added to catch.
6. `git grep "GameAnalysisData\b\|MoveRow\b\|arrows_by_ply"` returns no hits under `games/`, `analysis/`, `dashboard/`, `api/`, `templates/`.
