Here is the complete design document. I've written it to be directly usable by a Claude agent that has access to the existing codebase.

---

# RunPod Serverless Migration — Design Document
**Project:** wood_league_stockfish_runpod → RunPod Serverless Worker  
**Date:** 2026-04-19  
**Status:** Ready for implementation

---

## 1. Goal

Migrate the Stockfish analysis worker from a Railway always-on PostgreSQL-queue-polling architecture to a **RunPod Serverless CPU** architecture. The result should:

- Cost **$0 when idle** (no games in queue)
- Auto-scale to process many games in parallel
- Eliminate the Railway worker service entirely for analysis
- Preserve all existing analysis logic, move classifications, and DB schema unchanged
- Write results directly back to the existing PostgreSQL database

---

## 2. Current Architecture (Railway)

```
Chess.com API
     │
     ▼
run_sync.py ──────────────────────────────────────────────────────────────────┐
     │                                                                         │
     ▼                                                                         ▼
PostgreSQL                                                              AnalysisJob table
  (Game table)                                                          (queue rows)
                                                                               │
                                                              ┌────────────────┘
                                                              │  SELECT FOR UPDATE SKIP LOCKED
                                                              ▼
                                                    run_analysis_worker.py
                                                    (Railway always-on service)
                                                              │
                                                              ▼
                                                    stockfish_service.py
                                                    (Stockfish subprocess)
                                                              │
                                                              ▼
                                                    MoveAnalysis table
                                                    (results written to DB)
```

**Problems:**
- Railway worker runs 24/7, paying for idle time
- Shared burstable vCPUs — Stockfish gets throttled
- Single worker processes one game at a time by default
- Scaling requires manual replica configuration

---

## 3. Target Architecture (RunPod Serverless)

```
Chess.com API
     │
     ▼
run_sync.py (Railway — unchanged)
     │
     ▼
PostgreSQL (Game table — unchanged)
     │
     ▼
job_submitter.py (Railway — lightweight, replaces run_analysis_worker.py)
     │  POST /run for each unanalyzed game
     ▼
RunPod Managed Queue (internal — no code needed)
     │  RunPod pushes job to available worker
     ▼
RunPod Serverless Worker (new repo: wood_league_stockfish_runpod)
     │  handler.py + Stockfish SF18 AVX2
     │  Dedicated CPU, 8 threads, 2GB hash
     ▼
PostgreSQL (MoveAnalysis table — written directly by worker)
```

**Benefits:**
- $0 idle cost (Flex workers scale to zero) [^4]
- Dedicated CPU — no throttling
- Auto-scales to N parallel games simultaneously
- Worker is stateless and simple

---

## 4. What Changes vs. What Stays the Same

### ✅ Unchanged
- `stockfish_pipeline/models.py` — all DB models, schema, relationships
- `stockfish_pipeline/analysis/stockfish_service.py` — all analysis logic, move classification, accuracy calculations, CPL formulas
- `stockfish_pipeline/ingest/run_sync.py` — Chess.com ingest
- PostgreSQL database and all existing data
- Railway deployment for ingest + job submission

### 🔄 Modified
- `stockfish_pipeline/ingest/run_analysis_worker.py` — repurposed as **job submitter** (submits to RunPod API instead of processing locally)
- `start_workers.py` — updated to call job submitter instead of local worker loop
- `Dockerfile` (Railway) — can remove Stockfish binary since Railway no longer runs analysis
- `requirements.txt` — add `runpod` SDK to worker repo

### 🆕 New (separate repo: `wood_league_stockfish_runpod`)
- `handler.py` — RunPod worker entry point
- `Dockerfile` — RunPod-specific container with SF18 AVX2
- `requirements.txt` — minimal dependencies
- `test_input.json` — local testing payload

---

## 5. New Repo: `wood_league_stockfish_runpod`

### 5.1 Directory Structure

```
wood_league_stockfish_runpod/
├── handler.py              # RunPod worker entry point
├── Dockerfile              # Container definition
├── requirements.txt        # Python dependencies
├── test_input.json         # Local test payload
└── README.md
```

### 5.2 `handler.py`

This is the core of the RunPod worker. It receives a job, runs Stockfish analysis using the **existing `stockfish_service.py` logic** (copied or installed as a package), and writes results directly to PostgreSQL. [^2]

```python
"""
RunPod Serverless Worker — Stockfish Analysis Handler
Receives a job with a PGN string and game_id, runs Stockfish analysis,
writes MoveAnalysis rows to PostgreSQL, marks the game as analysed.
"""

import os
import runpod
import chess.pgn
import chess.engine
import io
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import analysis logic from the existing pipeline package
# (installed via pip install -e . or copied directly)
from stockfish_pipeline.analysis.stockfish_service import analyse_game
from stockfish_pipeline.models import Game, MoveAnalysis, Base

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# --- Configuration (from RunPod environment variables) ---
STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/usr/games/stockfish")
ANALYSIS_DEPTH = int(os.environ.get("ANALYSIS_DEPTH", "20"))
ANALYSIS_THREADS = int(os.environ.get("ANALYSIS_THREADS", "8"))
ANALYSIS_HASH_MB = int(os.environ.get("ANALYSIS_HASH_MB", "2048"))
DATABASE_URL = os.environ.get("DATABASE_URL")  # Required

# --- DB setup (module-level, reused across warm invocations) ---
engine_db = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine_db)


def handler(job):
    """
    RunPod job handler. Called once per job by the RunPod SDK.

    Expected job["input"]:
    {
        "game_id": int,          # Primary key of Game row in PostgreSQL
        "pgn": str,              # Full PGN string of the game
        "depth": int,            # Optional — overrides ANALYSIS_DEPTH env var
        "threads": int,          # Optional — overrides ANALYSIS_THREADS env var
        "hash_mb": int           # Optional — overrides ANALYSIS_HASH_MB env var
    }

    Returns:
    {
        "game_id": int,
        "moves_analysed": int,
        "accuracy_white": float,
        "accuracy_black": float,
        "status": "ok" | "error",
        "error": str             # Only present if status == "error"
    }
    """
    job_input = job["input"]
    game_id = job_input["game_id"]
    pgn_string = job_input["pgn"]
    depth = job_input.get("depth", ANALYSIS_DEPTH)
    threads = job_input.get("threads", ANALYSIS_THREADS)
    hash_mb = job_input.get("hash_mb", ANALYSIS_HASH_MB)

    log.info(f"Starting analysis: game_id={game_id}, depth={depth}, threads={threads}")

    try:
        # Parse PGN
        pgn_io = io.StringIO(pgn_string)
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            raise ValueError(f"Failed to parse PGN for game_id={game_id}")

        # Run Stockfish analysis
        # analyse_game() is the existing function from stockfish_service.py
        move_results, accuracy_white, accuracy_black = analyse_game(
            game=game,
            stockfish_path=STOCKFISH_PATH,
            depth=depth,
            threads=threads,
            hash_mb=hash_mb,
        )

        # Write results to PostgreSQL
        with SessionLocal() as session:
            # Delete any existing MoveAnalysis rows for this game (idempotent)
            session.query(MoveAnalysis).filter(MoveAnalysis.game_id == game_id).delete()

            # Insert new MoveAnalysis rows
            for move_data in move_results:
                row = MoveAnalysis(game_id=game_id, **move_data)
                session.add(row)

            # Update Game row with accuracy scores and mark as analysed
            db_game = session.get(Game, game_id)
            if db_game:
                db_game.accuracy_white = accuracy_white
                db_game.accuracy_black = accuracy_black
                db_game.analysed = True

            session.commit()

        log.info(f"Completed: game_id={game_id}, moves={len(move_results)}")

        return {
            "game_id": game_id,
            "moves_analysed": len(move_results),
            "accuracy_white": accuracy_white,
            "accuracy_black": accuracy_black,
            "status": "ok",
        }

    except Exception as e:
        log.error(f"Analysis failed for game_id={game_id}: {e}", exc_info=True)
        return {
            "game_id": game_id,
            "status": "error",
            "error": str(e),
        }


# Entry point — RunPod SDK handles all queue communication
runpod.serverless.start({"handler": handler})
```

**Key design decisions:**
- The DB engine is created at **module level** so it is reused across warm invocations (connection pooling)
- The handler is **idempotent** — it deletes existing `MoveAnalysis` rows before inserting, so re-running a job is safe
- Errors are caught and returned as `{"status": "error"}` rather than raising — this prevents RunPod from retrying indefinitely on bad PGN data
- `analyse_game()` is the existing function from `stockfish_service.py` — **do not rewrite it**

### 5.3 `stockfish_service.py` — Required Refactor

The existing `stockfish_service.py` needs one change: the core analysis logic must be extractable as a standalone function `analyse_game()` that the handler can call. The function signature should be:

```python
def analyse_game(
    game: chess.pgn.Game,
    stockfish_path: str,
    depth: int = 20,
    threads: int = 1,
    hash_mb: int = 256,
) -> tuple[list[dict], float, float]:
    """
    Analyse all moves in a game using Stockfish.

    Returns:
        move_results: list of dicts, one per half-move, with keys:
            - ply: int
            - move_uci: str
            - move_san: str
            - classification: str  (Brilliant/Great/Best/Excellent/Inaccuracy/Mistake/Blunder)
            - cpl: int             (centipawn loss, always >= 0)
            - eval_before: int     (centipawns, White perspective, before move)
            - eval_after: int      (centipawns, White perspective, after move)
            - best_move_uci: str
            - accuracy: float      (0.0–100.0, Lichess formula)
        accuracy_white: float      (game-level accuracy, White)
        accuracy_black: float      (game-level accuracy, Black)
    """
```

**Existing optimizations to preserve (already implemented):** [^5]
- N+1 engine calls per game (not 2N) — second call only when played move ≠ best move
- `multipv=1` for forced moves (single legal move)
- `multipv=2` for all other positions (needed for Brilliant/Great detection)
- `Limit(depth=depth, time=5.0)` — time cap to prevent outlier positions
- Hash table not cleared between positions (carries over within a game)

### 5.4 `Dockerfile` (RunPod)

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y wget tar && rm -rf /var/lib/apt/lists/*

# Install Stockfish 18 AVX2 (same as current Railway Dockerfile)
RUN wget -q https://github.com/official-stockfish/Stockfish/releases/latest/download/stockfish-ubuntu-x86-64-avx2.tar \
    && tar xf stockfish-ubuntu-x86-64-avx2.tar \
    && mv stockfish/stockfish-ubuntu-x86-64-avx2 /usr/games/stockfish \
    && chmod +x /usr/games/stockfish \
    && rm -rf stockfish stockfish-ubuntu-x86-64-avx2.tar

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy handler and pipeline package
COPY handler.py .
COPY stockfish_pipeline/ ./stockfish_pipeline/

# RunPod entry point
CMD ["python", "handler.py"]
```

### 5.5 `requirements.txt` (RunPod worker)

```
runpod>=1.6.0
chess>=1.10.0
sqlalchemy>=2.0.0
psycopg2-binary>=2.9.0
```

### 5.6 `test_input.json`

Used for local testing with `python handler.py` before deploying to RunPod. [^3]

```json
{
  "input": {
    "game_id": 1,
    "pgn": "[Event \"Live Chess\"]\n[Site \"Chess.com\"]\n[White \"player1\"]\n[Black \"player2\"]\n[Result \"1-0\"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 1-0",
    "depth": 18,
    "threads": 4,
    "hash_mb": 512
  }
}
```

---

## 6. Modified Files in `wood_league_stockfish_runpod`

### 6.1 `run_analysis_worker.py` — Repurposed as Job Submitter

The existing worker loop (poll DB → claim job → run Stockfish) is replaced with a **RunPod job submitter**. The submitter is fire-and-forget — it does not wait for results, because the RunPod worker writes results directly to PostgreSQL. [^1]

```python
"""
job_submitter.py — Submits unanalysed games to RunPod Serverless endpoint.
Replaces the local Stockfish worker loop.
"""

import os
import time
import logging
import runpod
from stockfish_pipeline.models import Game
from stockfish_pipeline.db import get_session

log = logging.getLogger(__name__)

RUNPOD_ENDPOINT_ID = os.environ["RUNPOD_ENDPOINT_ID"]
RUNPOD_API_KEY = os.environ["RUNPOD_API_KEY"]
ANALYSIS_DEPTH = int(os.environ.get("ANALYSIS_DEPTH", "20"))
ANALYSIS_THREADS = int(os.environ.get("ANALYSIS_THREADS", "8"))
ANALYSIS_HASH_MB = int(os.environ.get("ANALYSIS_HASH_MB", "2048"))
POLL_INTERVAL = int(os.environ.get("SF_POLL_INTERVAL", "60"))

runpod.api_key = RUNPOD_API_KEY
endpoint = runpod.Endpoint(RUNPOD_ENDPOINT_ID)


def submit_unanalysed_games(session, limit=None):
    """Find games not yet analysed and submit them to RunPod."""
    query = session.query(Game).filter(Game.analysed == False)
    if limit:
        query = query.limit(limit)
    games = query.all()

    submitted = 0
    for game in games:
        try:
            run_request = endpoint.run({
                "game_id": game.id,
                "pgn": game.pgn,
                "depth": ANALYSIS_DEPTH,
                "threads": ANALYSIS_THREADS,
                "hash_mb": ANALYSIS_HASH_MB,
            })
            log.info(f"Submitted game_id={game.id}, runpod_job_id={run_request.job_id}")
            submitted += 1
        except Exception as e:
            log.error(f"Failed to submit game_id={game.id}: {e}")

    return submitted


def run_submitter_loop():
    """Continuously submit new unanalysed games to RunPod."""
    with get_session() as session:
        while True:
            n = submit_unanalysed_games(session)
            log.info(f"Submitted {n} games. Sleeping {POLL_INTERVAL}s.")
            time.sleep(POLL_INTERVAL)
```

### 6.2 `start_workers.py`

```python
from stockfish_pipeline.ingest.job_submitter import run_submitter_loop

if __name__ == "__main__":
    run_submitter_loop()
```

### 6.3 `Dockerfile` (Railway — simplified)

Since Railway no longer runs Stockfish, remove the Stockfish binary installation:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "start_workers.py"]
```

---

## 7. Environment Variables

### RunPod Worker (set in RunPod endpoint configuration)

| Variable | Description | Recommended Value |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (same as Railway) | `postgresql://user:pass@host/db` |
| `STOCKFISH_PATH` | Path to Stockfish binary in container | `/usr/games/stockfish` |
| `ANALYSIS_DEPTH` | Search depth | `20` |
| `ANALYSIS_THREADS` | Threads per Stockfish instance | `8` |
| `ANALYSIS_HASH_MB` | Hash table size in MB | `2048` |

### Railway Job Submitter (updated)

| Variable | Description | Value |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `${{Postgres.DATABASE_URL}}` |
| `RUNPOD_ENDPOINT_ID` | RunPod endpoint ID | From RunPod dashboard |
| `RUNPOD_API_KEY` | RunPod API key | From RunPod dashboard |
| `ANALYSIS_DEPTH` | Forwarded to RunPod job input | `20` |
| `ANALYSIS_THREADS` | Forwarded to RunPod job input | `8` |
| `ANALYSIS_HASH_MB` | Forwarded to RunPod job input | `2048` |
| `SF_POLL_INTERVAL` | Seconds between submission sweeps | `60` |

**Remove from Railway** (no longer needed): `STOCKFISH_PATH`, `SF_ENQUEUE`, `SF_ENQUEUE_ONLY`, `SF_NO_POLL`

---

## 8. Database Considerations

### Option A: Keep `AnalysisJob` Table (Recommended)
Add a `runpod_job_id` column for tracking:

```python
# Add to AnalysisJob model in models.py
runpod_job_id = Column(String, nullable=True)   # RunPod job ID for tracking
submitted_at = Column(DateTime, nullable=True)   # When submitted to RunPod
```

### Option B: Remove `AnalysisJob` Table
The submitter queries `Game.analysed == False` directly — the `AnalysisJob` table is no longer needed as a queue. Simpler, but loses job tracking.

**Recommendation:** Keep the table, add `runpod_job_id`. This enables a status dashboard later.

### Idempotency
The `handler.py` deletes existing `MoveAnalysis` rows before inserting new ones:
- Re-submitting an already-analysed game is safe
- If a RunPod job fails halfway, re-submitting produces a clean result
- The submitter must check `Game.analysed == True` to avoid re-submitting completed games

---

## 9. RunPod Endpoint Configuration

In the RunPod dashboard, create a new **Serverless CPU Endpoint** with these settings: [^4]

| Setting | Value | Reason |
|---|---|---|
| Container image | Your Docker Hub image | Built from `wood_league_stockfish_runpod` |
| CPU type | Compute Optimized | Dedicated CPU for Stockfish |
| Min workers (Active) | `0` | Scale to zero — $0 idle cost |
| Max workers (Flex) | `10` | Process up to 10 games in parallel |
| Idle timeout | `5` seconds | Shut down quickly after finishing |
| Execution timeout | `300` seconds | 5 min max per game — safety net |
| Container disk | `5 GB` | Enough for Stockfish binary + Python |

---

## 10. Error Handling & Retries

### In `handler.py`
- All exceptions are caught and returned as `{"status": "error", "error": "..."}`
- This prevents RunPod from auto-retrying on bad data (e.g. malformed PGN)
- Transient errors (DB connection lost) should be allowed to raise — RunPod will retry these

```python
# Distinguish transient vs. permanent errors
try:
    session.commit()
except sqlalchemy.exc.OperationalError:
    raise  # Transient — let RunPod retry
except Exception as e:
    return {"status": "error", "error": str(e)}  # Permanent — don't retry
```

### In `job_submitter.py`
- Failed submissions (RunPod API down) are logged and skipped
- The next poll cycle will re-attempt (game still has `analysed == False`)
- No manual retry logic needed

---

## 11. Testing Locally Before Deploying

```bash
cd wood_league_stockfish_runpod
pip install -r requirements.txt
export DATABASE_URL="postgresql://..."
export STOCKFISH_PATH="/usr/local/bin/stockfish"

# RunPod SDK reads test_input.json and calls handler() directly
python handler.py
```

The RunPod SDK supports local testing via `test_input.json` with no RunPod account needed. [^3]

---

## 12. Deployment Steps (In Order)

1. **Create `wood_league_stockfish_runpod` repo** with the files in Section 5
2. **Refactor `stockfish_service.py`** to expose `analyse_game()` function (Section 5.3)
3. **Build and push Docker image** to Docker Hub: `docker build -t yourdockerhub/wood-league-chess-worker . && docker push`
4. **Create RunPod Serverless CPU endpoint** using the image (Section 9 settings)
5. **Test via RunPod dashboard** "Test" tab with a sample game payload
6. **Verify** `MoveAnalysis` rows appear in PostgreSQL
7. **Add `RUNPOD_ENDPOINT_ID` and `RUNPOD_API_KEY`** to Railway env vars
8. **Update `run_analysis_worker.py` → `job_submitter.py`** (Section 6.1)
9. **Update `start_workers.py`** (Section 6.2)
10. **Simplify Railway `Dockerfile`** (Section 6.3)
11. **Deploy to Railway** — submitter will start sending jobs to RunPod automatically

---

## 13. What NOT to Change

- `stockfish_pipeline/models.py` — DB schema is correct as-is
- `stockfish_pipeline/ingest/run_sync.py` — Chess.com ingest is unrelated
- All move classification logic and CPL/accuracy formulas in `stockfish_service.py`
- The PostgreSQL database itself
- Railway deployment for the ingest service

---

## 14. Expected Performance After Migration

| Metric | Before (Railway) | After (RunPod) |
|---|---|---|
| Time per 14-move game | 90–150s | 10–20s |
| CPU type | Shared burstable | Dedicated compute |
| Idle cost | ~$20–40/month | **$0** |
| Max parallel games | 1 (per replica) | 10 (auto-scaled) |
| Threads per game | 1 (if env var not set) | 8 (dedicated) |
| Hash per game | 256 MB default | 2048 MB |

---

*The markdown file has also been saved to `/tmp/runpod_migration_design.md` in the sandbox if you need to copy it out directly.*