# Postman API Test Collection — Design Spec

**Date:** 2026-05-08  
**Status:** Approved

## Overview

A Postman Collection (v2.1 JSON) for the Wood League Worker API (`/api/v1/`), importable directly into Postman. Paired with two Postman Environment files (Local Dev and Staging) that are switchable via the Postman environment dropdown.

## Collection Structure

```
Wood League Worker API
├── Health & Status
│   ├── Health Check          GET  /api/v1/health/
│   └── Queue Status          GET  /api/v1/jobs/status/
├── Jobs
│   ├── Checkout Jobs         POST /api/v1/jobs/checkout/
│   ├── Complete — Stockfish  POST /api/v1/jobs/:job_id/complete/
│   ├── Complete — Lc0        POST /api/v1/jobs/:job_id/complete/
│   ├── Fail Job              POST /api/v1/jobs/:job_id/fail/
│   └── Submit Job (RunPod)   POST /api/v1/jobs/:job_id/submit/
└── Worker
    └── Heartbeat             POST /api/v1/heartbeat/
```

## Variables

### Collection-level
- `job_id` — integer job ID, set manually before running job-specific requests.

### Environment-level (set per environment)
| Variable   | Local Dev                          | Staging                                   |
|------------|------------------------------------|-------------------------------------------|
| `base_url` | `http://localhost:8000/api/v1`     | `https://YOUR_STAGING_URL.railway.app/api/v1` |
| `api_key`  | `YOUR_LOCAL_API_KEY`               | `YOUR_STAGING_API_KEY`                    |

## Authentication

All authenticated endpoints send `X-Api-Key: {{api_key}}` as a header. The `GET /api/v1/health/` endpoint has no auth header.

## Request Bodies

### Checkout Jobs
```json
{
  "engine": "stockfish",
  "batch_size": 1,
  "worker_id": "test-worker-01",
  "dispatch_mode": "pull"
}
```

### Complete — Stockfish
```json
{
  "engine": "stockfish",
  "worker_id": "test-worker-01",
  "engine_depth": 20,
  "white_accuracy": 85.5,
  "black_accuracy": 72.3,
  "white_acpl": 18.2,
  "black_acpl": 34.7,
  "white_blunders": 0,
  "white_mistakes": 1,
  "white_inaccuracies": 2,
  "black_blunders": 1,
  "black_mistakes": 2,
  "black_inaccuracies": 3,
  "moves": [
    {
      "ply": 1,
      "san": "e4",
      "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
      "cp_eval": 29,
      "cpl": 0,
      "best_move": "e4",
      "classification": "Best"
    }
  ]
}
```

### Complete — Lc0
```json
{
  "engine": "lc0",
  "worker_id": "test-worker-01",
  "engine_nodes": 800,
  "network_name": "maia-1100",
  "white_win_prob": 0.55,
  "white_draw_prob": 0.30,
  "white_loss_prob": 0.15,
  "black_win_prob": 0.15,
  "black_draw_prob": 0.30,
  "black_loss_prob": 0.55,
  "white_blunders": 0,
  "white_mistakes": 1,
  "white_inaccuracies": 2,
  "black_blunders": 1,
  "black_mistakes": 2,
  "black_inaccuracies": 3,
  "moves": [
    {
      "ply": 1,
      "san": "e4",
      "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
      "wdl_win": 550,
      "wdl_draw": 300,
      "wdl_loss": 150,
      "cp_equiv": 29,
      "best_move": "e4",
      "move_win_delta": 0.0,
      "classification": "Best"
    }
  ]
}
```

### Fail Job
```json
{
  "worker_id": "test-worker-01",
  "error": "Engine crashed: segfault at ply 14"
}
```

### Submit Job (RunPod)
```json
{
  "runpod_job_id": "runpod-abc123xyz"
}
```

### Heartbeat
```json
{
  "worker_id": "test-worker-01",
  "engine": "stockfish",
  "status_message": "idle"
}
```

## Assertions (Tests tab)

| Request              | Assertions                                                      |
|----------------------|-----------------------------------------------------------------|
| Health Check         | Status 200; body has `status: "ok"`                            |
| Queue Status         | Status 200; body has `queue` array                             |
| Checkout Jobs        | Status 200; body has `jobs` array                              |
| Complete — Stockfish | Status 200; body has `status: "completed"`                     |
| Complete — Lc0       | Status 200; body has `status: "completed"`                     |
| Fail Job             | Status 200; body has `status` field                            |
| Submit Job           | Status 200; body has `status: "submitted"`                     |
| Heartbeat            | Status 200; body has `status: "ok"`                            |

## Output Files

| File | Purpose |
|------|---------|
| `docs/postman/WoodLeagueWorkerAPI.postman_collection.json` | Import into Postman |
| `docs/postman/WoodLeague-LocalDev.postman_environment.json` | Local environment |
| `docs/postman/WoodLeague-Staging.postman_environment.json` | Staging environment |
