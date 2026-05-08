---
id: 1
title: Persist Continuations
status: closed
priority: high
labels: [enhancement]
created: "2026-05-05"
updated: "2026-05-05"
---

## Same pattern — same fix needed

The Lc0 repo has **exactly the same issue** as the Stockfish one. It calls `engine.analyse()` with `multipv=3`, gets the full `pv` list back, but only extracts `pv[0]` (the first move) for each of the 3 lines.

## What the Code Currently Does

`lc0_service.py` grabs only `pv[0]` — the single best first move for each line:

```python
best_move_obj   = pre_top.get("pv", [None])[0]       # ← only move 1
second_move_obj = pre_alt.get("pv", [None])[0]        # ← only move 1
third_move_obj  = pre_third.get("pv", [None])[0]      # ← only move 1
```

So the full continuation is being discarded.

## One Important Lc0 Difference

Lc0's `pv` lines are typically **shorter** than Stockfish's (~3–6 moves vs ~10–16), because Lc0 uses node-count budgets rather than depth.

## The Fix

Add a `_pv_to_san()` helper that walks the full pv list on a temp board copy, converting each move to SAN. Add `pv_san_1/2/3: list[str]` to `Lc0MoveResult`, `pv_san_1/2/3` nullable Text columns to `Lc0MoveAnalysis`, and pass them through in `handler.py`'s `_save_analysis()`. Create a migration script for existing databases.

No extra engine calls needed — the full continuation was always in the pv list.
