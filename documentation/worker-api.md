# Analysis Worker API

This API is used by remote workers (Stockfish/Lc0) to claim jobs and report results.

Base path:

- `/api/v1/`

## Authentication

All endpoints except `GET /health/` require an API key header:

```http
X-Api-Key: <raw-worker-api-key>
```

Worker keys are issued in the admin UI:

- `/admin/api-keys/`

Notes:

- Missing, invalid, or revoked key returns `403`.
- Authenticated calls update the key's `last_used_at`.

## Rate limits

Scoped throttles:

- Checkout: `60/min`
- Complete: `120/min`
- Heartbeat: `600/min`

Other endpoints are not scoped.

## Data model notes

- Jobs are in `analysis_jobs` (`AnalysisJob` model).
- `engine` is `stockfish` or `lc0`.
- Job lifecycle: `pending -> running -> completed` or `failed`.
- Jobs are owned by both `worker_id` and API key prefix while running.

## Endpoint summary

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/health/` | No | Liveness check |
| `POST` | `/api/v1/jobs/checkout/` | Yes | Claim up to N pending jobs |
| `POST` | `/api/v1/jobs/{job_id}/complete/` | Yes | Submit Stockfish or Lc0 job result |
| `POST` | `/api/v1/jobs/{job_id}/fail/` | Yes | Report failure and requeue/fail job |
| `GET` | `/api/v1/jobs/status/` | Yes | Queue counts by engine and status |
| `POST` | `/api/v1/heartbeat/` | Yes | Worker heartbeat upsert |

---

## `GET /api/v1/health/`

Public liveness check.

### Example

```bash
curl -s https://example.com/api/v1/health/
```

### Success response (`200`)

```json
{"status": "ok"}
```

---

## `POST /api/v1/jobs/checkout/`

Claims pending jobs for an engine.

- Uses row locking (`SELECT ... FOR UPDATE SKIP LOCKED`) for safe concurrent workers.
- Runs stale-job recovery before checkout.

### Request body

| Field | Type | Required | Notes |
|---|---|---|---|
| `engine` | string | Yes | `stockfish` or `lc0` |
| `batch_size` | integer | No | `1..10`, default `1` |
| `worker_id` | string | Yes | max length `64` |
| `game_id` | string | No | Optional targeted checkout for a specific game |

### Example request

```bash
curl -s -X POST https://example.com/api/v1/jobs/checkout/ \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: <key>' \
  -d '{
    "engine": "stockfish",
    "batch_size": 2,
    "worker_id": "stockfish-runpod-1"
  }'
```

### Success response (`200`)

Returns an array (possibly empty):

```json
{
  "jobs": [
    {
      "id": 123,
      "game_id": "game-abc",
      "pgn": "1. e4 e5 2. Nf3 Nc6",
      "engine": "stockfish",
      "depth": 20,
      "nodes": null,
      "worker_id": "stockfish-runpod-1",
      "claimed_by_key_prefix": "a1b2c3d4"
    }
  ]
}
```

No jobs available:

```json
{"jobs": []}
```

### Conflict responses (`409`)

Targeted `game_id` checkout can return:

```json
{"error": "Analysis already completed for requested game"}
```

```json
{"error": "Requested game is already claimed"}
```

```json
{"error": "No pending job exists for requested game"}
```

### Validation/auth errors

- `400`: invalid payload
- `403`: missing/invalid/revoked API key

---

## `POST /api/v1/jobs/{job_id}/complete/`

Submits completion payload and marks the running job as `completed`.

Engine is selected by `engine` in the JSON body.

- `engine: "stockfish"` -> Stockfish schema
- `engine: "lc0"` -> Lc0 schema

If the job is not running, does not exist, or is owned by another worker/key, returns `404`.

### Stockfish payload

Required fields:

- `engine`: `"stockfish"`
- `worker_id`
- `engine_depth` (`1..40`)
- `white_accuracy`, `black_accuracy` (`0..100`)
- `white_acpl`, `black_acpl` (`>=0`)
- `white_blunders`, `white_mistakes`, `white_inaccuracies` (`>=0`)
- `black_blunders`, `black_mistakes`, `black_inaccuracies` (`>=0`)
- `moves` (max 500)

Each Stockfish move item:

- `ply` (`>=1`)
- `san`
- `fen`
- `cp_eval` (integer)
- `cpl` (`>=0`)
- `best_move`
- `classification` in: `Brilliant`, `Great`, `Best`, `Excellent`, `Inaccuracy`, `Mistake`, `Blunder`

### Stockfish example

```bash
curl -s -X POST https://example.com/api/v1/jobs/123/complete/ \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: <key>' \
  -d '{
    "engine": "stockfish",
    "worker_id": "stockfish-runpod-1",
    "engine_depth": 20,
    "white_accuracy": 95.5,
    "black_accuracy": 88.2,
    "white_acpl": 21.3,
    "black_acpl": 34.8,
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
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "cp_eval": 35,
        "cpl": 0,
        "best_move": "e4",
        "classification": "Best"
      }
    ]
  }'
```

### Lc0 payload

Required fields:

- `engine`: `"lc0"`
- `worker_id`
- `engine_nodes` (`>=1`)
- `white_win_prob`, `white_draw_prob`, `white_loss_prob` (`0..1`)
- `black_win_prob`, `black_draw_prob`, `black_loss_prob` (`0..1`)
- `white_blunders`, `white_mistakes`, `white_inaccuracies` (`>=0`)
- `black_blunders`, `black_mistakes`, `black_inaccuracies` (`>=0`)
- `moves` (max 500)

Optional:

- `network_name`

Each Lc0 move item:

- `ply` (`>=1`)
- `san`
- `fen`
- `wdl_win`, `wdl_draw`, `wdl_loss` (`0..1000`)
- `cp_equiv` (nullable)
- `best_move`
- `arrow_uci` (optional)
- `move_win_delta` (float)
- `classification` in: `Brilliant`, `Great`, `Best`, `Excellent`, `Inaccuracy`, `Mistake`, `Blunder`

### Lc0 example

```bash
curl -s -X POST https://example.com/api/v1/jobs/456/complete/ \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: <key>' \
  -d '{
    "engine": "lc0",
    "worker_id": "lc0-runpod-2",
    "engine_nodes": 25000,
    "network_name": "BT4",
    "white_win_prob": 0.42,
    "white_draw_prob": 0.35,
    "white_loss_prob": 0.23,
    "black_win_prob": 0.23,
    "black_draw_prob": 0.35,
    "black_loss_prob": 0.42,
    "white_blunders": 1,
    "white_mistakes": 2,
    "white_inaccuracies": 1,
    "black_blunders": 0,
    "black_mistakes": 1,
    "black_inaccuracies": 2,
    "moves": [
      {
        "ply": 1,
        "san": "d4",
        "fen": "rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
        "wdl_win": 420,
        "wdl_draw": 350,
        "wdl_loss": 230,
        "cp_equiv": 28,
        "best_move": "d4",
        "arrow_uci": "d2d4",
        "move_win_delta": 0.7,
        "classification": "Best"
      }
    ]
  }'
```

### Success response (`200`)

```json
{"status": "completed"}
```

### Error responses

- `400`: missing/invalid `engine` or payload validation errors
- `403`: auth error
- `404`: job not found, not running, or not owned by this worker/key

---

## `POST /api/v1/jobs/{job_id}/fail/`

Reports a worker failure for a running job.

### Request body

| Field | Type | Required | Notes |
|---|---|---|---|
| `worker_id` | string | Yes | Must match the claimant |
| `error` | string | Yes | Max `2000` chars (stored truncated) |

### Example

```bash
curl -s -X POST https://example.com/api/v1/jobs/123/fail/ \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: <key>' \
  -d '{
    "worker_id": "stockfish-runpod-1",
    "error": "Engine crashed: out of memory"
  }'
```

### Success response (`200`)

When under retry limit (`MAX_JOB_RETRIES`):

```json
{"status": "requeued"}
```

When retry limit reached:

```json
{"status": "failed"}
```

### Error responses

- `400`: invalid payload
- `403`: auth error
- `404`: job not found, not running, or not owned by this worker/key

---

## `GET /api/v1/jobs/status/`

Returns grouped queue counts by engine and status.

### Example

```bash
curl -s https://example.com/api/v1/jobs/status/ \
  -H 'X-Api-Key: <key>'
```

### Success response (`200`)

```json
{
  "queue": [
    {"engine": "lc0", "status": "pending", "count": 120},
    {"engine": "lc0", "status": "running", "count": 5},
    {"engine": "stockfish", "status": "completed", "count": 2400}
  ]
}
```

### Error responses

- `403`: auth error

---

## `POST /api/v1/heartbeat/`

Upserts worker heartbeat record by `worker_id`.

### Request body

| Field | Type | Required | Notes |
|---|---|---|---|
| `worker_id` | string | Yes | max length `64` |
| `engine` | string | Yes | `stockfish` or `lc0` |
| `status_message` | string | No | max length `256`, default empty |

### Example

```bash
curl -s -X POST https://example.com/api/v1/heartbeat/ \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: <key>' \
  -d '{
    "worker_id": "lc0-runpod-2",
    "engine": "lc0",
    "status_message": "analyzing game game-abc"
  }'
```

### Success response (`200`)

```json
{"status": "ok"}
```

### Error responses

- `400`: invalid payload
- `403`: auth error

---

## Fault tolerance behavior

### Stale running job recovery

Before each checkout, jobs stuck in `running` longer than `STALE_JOB_TIMEOUT_MINUTES` are reset to `pending` and claim ownership is cleared.

Default:

- `STALE_JOB_TIMEOUT_MINUTES=15`

### Retry policy

On `/fail/`:

- increment `retry_count`
- if `retry_count < MAX_JOB_RETRIES`: set `status=pending` (`requeued`)
- else: set `status=failed`

Default:

- `MAX_JOB_RETRIES=3`

## Environment variables relevant to API workers

| Variable | Default | Description |
|---|---|---|
| `STALE_JOB_TIMEOUT_MINUTES` | `15` | Minutes before running job is considered stale and requeued on checkout |
| `MAX_JOB_RETRIES` | `3` | Retry attempts before permanent failed state |
| `API_KEY_CUSTOM_HEADER` | `HTTP_X_API_KEY` | Django request header key used for API key lookup |
