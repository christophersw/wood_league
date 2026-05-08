<!--
Title: complexity-review.md — Flagged complexity findings for human review
Description:
    Documents functions where AI could not safely simplify (domain expert required),
    notes refactors already completed, and lists grade-C+ issues discovered during
    the quality gate run on 2026-05-08 that are queued for future work.

Changelog:
    2026-05-08: Initial creation from quality gate audit (Task 8)
-->

# Complexity Review — Flagged for Human Review

Functions where AI could not safely simplify — require domain expert judgement.

| Function | File | Grade | CC | Decision | Notes |
|----------|------|-------|----|----------|-------|
| `continuation_flow` | `openings/services.py` | ~~E~~ → C | ~~37~~ → 14 | **Refactored** | Extracted 4 helpers; see Details §1 |
| `continuation_flow` | `app/services/opening_position_service.py` | ~~E~~ → C | ~~37~~ → 14 | **Refactored + Flag dedup** | Same 4 helpers extracted; near-identical to `openings/services.py` — see Details §2 |

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

---

## Grade-C+ Issues Queued for Future Work

Discovered during the 2026-05-08 quality gate run. **Do not fix in this task** — listed
for prioritisation in a future audit pass.

| Function | File | Grade | CC | Notes |
|----------|------|-------|----|-------|
| *(file-level)* | `openings/services.py` | — | MI=5.75 | **CRITICAL** — maintainability index below threshold of 20; entire file needs architectural attention |
| `opening_tree_context` | `openings/services.py` | D | 25 | Likely candidate for helper extraction |
| `get_games` | `openings/services.py` | D | 21 | Inner `_matches` closure + filter chain |
| `opening_tree_svg` | `openings/services.py` | C | 13 | SVG generation branching |
| `opening_tree_context` | `app/services/opening_position_service.py` | D | 25 | Near-duplicate of `openings/services.py::opening_tree_context` |
| `player_stats` | `app/services/opening_position_service.py` | C | 18 | Per-player aggregation loop |
| `get_games` | `app/services/opening_position_service.py` | C | 16 | SQLAlchemy filter chain |
| `_uncatalogued_label` | `app/services/opening_labels.py` | C | 19 | Classification logic — may be inherent |
| `_opening_family` | `app/services/opening_analysis_service.py` | C | 14 | Family classification |
| `_recent_games` | `app/services/opening_analysis_service.py` | C | 13 | Game filtering |
| `get_opening_flow` | `dashboard/services.py` | D | 23 | Sankey edge builder — similar pattern to continuation_flow |
| `_opening_name_path` | `dashboard/services.py` | C | 14 | Name parsing |
| `get_most_recent_games` | `dashboard/services.py` | C | 11 | Game query with branching |
| `welcome_opening_sankey` | `dashboard/charts.py` | C | 14 | Chart rendering branches |

### Priority recommendations

1. **`openings/services.py` MI=5.75** — highest urgency; the entire file's maintainability
   score is critically low. The D/C functions above concentrated in this file are
   contributors. A dedicated refactor sprint is warranted.
2. **Deduplication of `opening_tree_context`** — appears in both `openings/services.py`
   and `opening_position_service.py` with identical signatures; same pattern as
   `continuation_flow`.
3. **`dashboard/services.py::get_opening_flow` (D, CC=23)** — another Sankey builder;
   likely shares logic with the now-refactored `continuation_flow` helpers and could
   be unified.
