<!--
Title: complexity-review.md — Flagged complexity findings for human review
Description:
    Documents functions where AI could not safely simplify (domain expert required),
    notes refactors already completed, and lists grade-C+ issues discovered during
    the quality gate run on 2026-05-08 that are queued for future work.

Changelog:
    2026-05-08: Initial creation from quality gate audit (Task 8)
    2026-05-08: Task 9 — refactored 4 grade-D/E functions; updated decisions table
-->

# Complexity Review — Flagged for Human Review

Functions where AI could not safely simplify — require domain expert judgement.

| Function | File | Grade | CC | Decision | Notes |
|----------|------|-------|----|----------|-------|
| `continuation_flow` | `openings/services.py` | ~~E~~ → C | ~~37~~ → 14 | **Refactored** | Extracted 4 helpers; see Details §1 |
| `continuation_flow` | `app/services/opening_position_service.py` | ~~E~~ → C | ~~37~~ → 14 | **Refactored + Flag dedup** | Same 4 helpers extracted; near-identical to `openings/services.py` — see Details §2 |
| `opening_tree_context` | `openings/services.py` | ~~E~~ → C | ~~25~~ → ~10 | **Refactored** | Extracted `_scan_game_for_tree`, `_annotate_tree_results`; see Details §3 |
| `get_games` | `openings/services.py` | ~~E~~ → C | ~~21~~ → ~8 | **Refactored** | Extracted `_pgn_reaches_epd`, `_build_games_queryset`, `_participant_to_record`; see Details §4 |
| `opening_tree_context` | `app/services/opening_position_service.py` | ~~E~~ → C | ~~25~~ → ~10 | **Refactored + Flag dedup** | Same 2 helpers extracted as module-level; near-identical to `openings/services.py` — see Details §5 |
| `get_opening_flow` | `dashboard/services.py` | ~~E~~ → C | ~~23~~ → ~8 | **Refactored** | Extracted `_query_deduped_participants`, `_accumulate_flow_stats`, `_build_flow_dataframes`; see Details §6 |

---

## Details

### §1 — `openings/services.py::continuation_flow` (E→C, CC 37→14)

**Decision: Refactored.** The complexity was real but decomposable. Four private helpers
were extracted, each with independently clear responsibility:

- `_advance_board_to_opening(game, ply_depth, target_epd)` — EPD replay and verification
- `_collect_continuation_names(node, board, opening_name)` — variation name sampling at +2/+4/+6 plies
- `_accumulate_node_stats(node_data, path, result_val, w_acc, b_acc, player)` — per-node stat accumulation
- `_build_node_stats_df(node_data, visible_nodes)` — DataFrame assembly

The remaining C(14) on `continuation_flow` itself reflects inherent iteration over games
with deduplication, edge counting, and edge filtering — not further reducible without
obscuring the algorithm.

### §2 — `app/services/opening_position_service.py::OpeningPositionService.continuation_flow` (E→C, CC 37→14)

**Decision: Refactored.** Same four helpers extracted as module-level functions.

**Deduplication flag:** Both `openings/services.py::continuation_flow` and
`opening_position_service.py::continuation_flow` implement the same chess opening
continuation Sankey algorithm — one via Django ORM, one via SQLAlchemy. The helpers
are already identical. A future refactor should move the four helpers (and possibly the
outer loop) into `wood_league_shared` so both callers share one implementation.

### §3 — `openings/services.py::opening_tree_context` (E→C, CC 25→~10)

**Decision: Refactored.** The main loop had two separable concerns: scanning each game
for lineage/child data, and annotating results with percentages. Two helpers extracted:

- `_scan_game_for_tree(game, lineage_epd_set, selected_epd, selected_ply)` — walks moves,
  returns `(seen_lineage_epds, reached_selected, selected_child)`. Pure function over a
  parsed game; can be tested independently.
- `_annotate_tree_results(lineage, lineage_game_counts, child_counts, ...)` — attaches
  games counts, pct_scoped, pct_selected and sorts children. Pure transformation.

The outer function is now a coordinator: scope query → lineage setup → per-game loop →
annotate → return.

### §4 — `openings/services.py::get_games` (E→C, CC 21→~8)

**Decision: Refactored.** Three separable concerns extracted as named helpers:

- `_pgn_reaches_epd(pgn_text, target_epd, ply_depth)` — pure PGN scan; the nested
  `_matches` closure was eliminated, with the cache moved to the outer loop.
- `_build_games_queryset(lookback_days, players)` — builds the filtered Django queryset.
  Isolates the ORM query construction from the iteration logic.
- `_participant_to_record(gp)` — converts a GameParticipant ORM object to a flat record
  dict. The 14-key dict literal is now in its own function with a clear return type.

### §5 — `app/services/opening_position_service.py::OpeningPositionService.opening_tree_context` (E→C, CC 25→~10)

**Decision: Refactored.** Same two helpers as §3 (`_scan_game_for_tree`,
`_annotate_tree_results`) added as module-level functions before the class definition.
The method body now delegates to them identically to §3.

**Deduplication flag:** `opening_tree_context` in both files is near-identical (same
pattern as `continuation_flow` in §2). Both files now have the same two helpers. A
future refactor should consolidate into `wood_league_shared`.

### §6 — `dashboard/services.py::get_opening_flow` (E→C, CC 23→~8)

**Decision: Refactored.** Three distinct phases were extracted:

- `_query_deduped_participants(lookback_days, players)` — ORM query with deduplication
  by (game_id, player.username). Isolates DB access from the stats accumulation.
- `_accumulate_flow_stats(records)` — scans PGNs and builds edge_counts + node_data
  accumulators. Contains all the per-result/accuracy branching (inherent domain logic).
- `_build_flow_dataframes(edge_counts, node_data, min_games)` — converts accumulators
  to DataFrames and filters by min_games threshold. Pure transformation.

The outer `get_opening_flow` is now a 4-line coordinator.

---

## Grade-C+ Issues Queued for Future Work

Discovered during the 2026-05-08 quality gate run. Lower-priority items not yet addressed.

| Function | File | Grade | CC | Notes |
|----------|------|-------|----|-------|
| *(file-level)* | `openings/services.py` | — | MI=5.75 | **CRITICAL** — maintainability index below threshold of 20; entire file needs architectural attention |
| `opening_tree_svg` | `openings/services.py` | C | 13 | SVG generation branching |
| `player_stats` | `app/services/opening_position_service.py` | C | 18 | Per-player aggregation loop |
| `get_games` | `app/services/opening_position_service.py` | C | 16 | SQLAlchemy filter chain |
| `_uncatalogued_label` | `app/services/opening_labels.py` | C | 19 | Classification logic — may be inherent |
| `_opening_family` | `app/services/opening_analysis_service.py` | C | 14 | Family classification |
| `_recent_games` | `app/services/opening_analysis_service.py` | C | 13 | Game filtering |
| `_opening_name_path` | `dashboard/services.py` | C | 14 | Name parsing |
| `get_most_recent_games` | `dashboard/services.py` | C | 11 | Game query with branching |
| `welcome_opening_sankey` | `dashboard/charts.py` | C | 14 | Chart rendering branches |

### Priority recommendations

1. **`openings/services.py` MI=5.75** — highest urgency; the entire file's maintainability
   score is critically low. Task 9 improvements should raise MI, but a dedicated refactor
   sprint is still warranted for the remaining C-grade functions.
2. **Deduplication of `opening_tree_context` and `continuation_flow` helpers** — both sets
   of helpers now exist in both `openings/services.py` and `opening_position_service.py`
   as near-identical copies. Consolidation into `wood_league_shared` would eliminate drift.
3. **`_accumulate_flow_stats` in `dashboard/services.py`** — the win/draw/loss/accuracy
   accumulation loop may still score C; if so, consider a dataclass accumulator pattern.

---

## Security Findings — Accepted Risks

### Snyk Code: python/Sqli (Medium) — `search/services.py::execute_sql_search`

**Finding:** Snyk's taint analysis traces `response.json()` (Anthropic API response) →
`cursor.execute()` and flags it as SQL injection.

**Assessment: Accepted risk / architectural false positive.**

The AI-to-SQL search feature works as follows:
1. User's natural language query → Anthropic Claude API (user text is NOT interpolated into SQL)
2. Claude generates SQL → `_sanitize_sql()` validates it before execution
3. `_sanitize_sql()` enforces: SELECT-only, allowlisted tables only (`games`, `game_analysis`,
   `move_analysis`, `game_participants`), no UNION/system catalog/DML keywords, LIMIT enforced

Snyk's taint analysis cannot reason about custom sanitizers, so it reports this as unfixed
even though the sanitization is comprehensive. Parameterized queries cannot be used because
the SQL structure itself is dynamic (AI-generated column selection, WHERE conditions, JOINs).

**Mitigations in place:**
- User input never reaches SQL as a string value — only natural language to Claude
- SELECT-only enforced; all DML/DDL keywords blocked
- Only 4 non-sensitive chess-game tables accessible
- `cursor.execute()` annotated with `# nosec B608` for bandit tracking
- No PII or credentials in the 4 allowlisted tables

**Action needed:** Suppress via Snyk dashboard (project-level ignore) or accept as known risk.
If the search feature is ever extended to inject user-provided values as SQL parameters,
use `cursor.execute(sql, params)` with proper Django parameterization for those values.
