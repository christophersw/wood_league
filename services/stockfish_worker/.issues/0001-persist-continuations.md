---
id: 1
title: Persist Continuations
status: closed
priority: high
labels: [enhancement]
created: "2026-05-05"
updated: "2026-05-05"
---

## Confirmed — but there's a gap to fix

Your pipeline **is** using `engine.analyse()` with `multipv=3` and **does** access the `pv` field — but it only extracts the **first move** of each line and discards the rest of the continuation. [^1]

Here's the relevant code in `stockfish_pipeline/services/stockfish_service.py`:

```python
result = engine.analyse(board, limit, multipv=3)
entries = result if isinstance(result, list) else [result]

def _entry(idx: int) -> tuple[float, str]:
    if idx < len(entries):
        e = entries[idx]
        cp = _cp(e["score"].white())
        pv = e.get("pv", [])
        uci = pv[0].uci() if pv else ""   # ← only move 1 of the pv is kept!
        return cp, uci
    return 0.0, ""
```

So currently: [^1]
- ✅ `multipv=3` — all 3 lines are analysed
- ✅ Score (`cp`) is captured for all 3 lines
- ✅ `pv` list is accessed
- ❌ Only `pv[0]` (the best *first* move) is stored — moves 2–16 are thrown away
- ❌ The full continuation is never written to the database

---

## The Fix — It's a Small Change

Instead of extracting just `pv[0].uci()`, iterate over the whole `pv` list and convert each move to SAN (or UCI). Change `_entry` to return the full line:

```python
def _entry(idx: int) -> tuple[float, str, list[str]]:
    if idx < len(entries):
        e = entries[idx]
        cp = _cp(e["score"].white())
        pv = e.get("pv", [])
        
        # Convert full pv to SAN move list
        temp_board = board.copy()
        san_moves = []
        for move in pv:
            san_moves.append(temp_board.san(move))
            temp_board.push(move)
        
        uci = pv[0].uci() if pv else ""   # keep for backward compat if needed
        return cp, uci, san_moves
    return 0.0, "", []
```

This gives you something like:
```
Line 1: +0.42 → Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 O-O d3 d6
Line 2: +0.18 → d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O
Line 3: -0.05 → c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5
```

You'd then store `san_moves` (as a JSON array or space-separated string) in your database alongside the existing `cp` and `uci` columns — **no extra Stockfish calls needed, zero additional compute cost**. The full continuation was always there; it just wasn't being saved.


[^1]: stockfish_pipeline/services/stockfish_service.py
