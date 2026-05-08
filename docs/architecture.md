# Wood League — Architecture

## System Overview

Wood League is a chess club analytics platform with four services:

```
Browser → Railway (app) → PostgreSQL
              ↓
        Railway (dispatchers) → RunPod (stockfish_worker)
                             → RunPod (lc0_worker)
```

## Services

| Service | Purpose | Deployment | Language |
|---------|---------|------------|---------|
| `services/app` | Django web app — serves the UI and REST API | Railway | Python 3.13 |
| `services/dispatchers` | Polls DB for jobs, dispatches to RunPod | Railway | Python 3.11 |
| `services/stockfish_worker` | Stockfish engine analysis | RunPod Serverless | Python 3.11 |
| `services/lc0_worker` | Lc0 neural net analysis (GPU) | RunPod Serverless | Python 3.11 |

## Shared Library

`packages/shared` (`wood_league_shared`) contains code used by two or more services:
- `storage/models.py` — SQLAlchemy ORM models
- `storage/database.py` — engine, session factory, `init_db()`
- `ingest/chesscom_client.py` — Chess.com public API client
- `ingest/sync_service.py` — game sync orchestration
- `services/opening_book.py` — Lichess opening name lookup

## Data Flow

1. `dispatchers` polls the DB for unanalyzed games
2. `dispatchers` submits jobs to RunPod Serverless (stockfish or lc0)
3. RunPod worker analyzes the game and POSTs results back to the `app` API
4. `app` persists results and serves them in the UI
