# wood_league_dispatchers

Unified Railway worker that submits queued `analysis_jobs` to two RunPod serverless endpoints:
- Stockfish endpoint
- Lc0 endpoint
- Periodic Chess.com ingest

This is now the canonical Railway dispatcher repo for Wood League Chess.

## What it does

- Polls `analysis_jobs` where `status='pending'`
- Submits `engine='stockfish'` jobs to the Stockfish RunPod endpoint
- Submits `engine='lc0'` jobs to the Lc0 RunPod endpoint
- Marks jobs as `submitted` and stores `runpod_job_id`
- Periodically syncs new games from Chess.com when usernames are configured
- Optionally enqueues newly ingested games immediately for Stockfish and/or Lc0

RunPod workers are responsible for analysis + writing final results + marking jobs completed.

## Environment variables

Required:
- `DATABASE_URL`
- `RUNPOD_API_KEY`
- `RUNPOD_STOCKFISH_ENDPOINT_ID`
- `RUNPOD_LC0_ENDPOINT_ID`

Optional:
- `SF_POLL_INTERVAL` (default: `60`)
- `LC0_POLL_INTERVAL` (default: `60`)
- `CHESS_COM_USERNAMES` (comma-separated Chess.com usernames; enables ingest loop)
- `INGEST_POLL_INTERVAL` (default: `900`)
- `INGEST_MONTH_LIMIT` (default: `24`)
- `CHESS_COM_USER_AGENT` (default: `wood-league-dispatchers/0.1 (+runpod dispatcher)`)
- `QUEUE_STOCKFISH_AFTER_INGEST` (default: `true`)
- `QUEUE_LC0_AFTER_INGEST` (default: `false`)
- `ANALYSIS_DEPTH` (default: `20`, used for newly queued Stockfish jobs)
- `ANALYSIS_THREADS` (default: `8`)
- `ANALYSIS_HASH_MB` (default: `2048`)
- `LC0_NODES` (default: `25000`)
- `LC0_NETWORK` (optional path forwarded in payload)

Backwards-compatible fallback:
- `RUNPOD_ENDPOINT_ID` is used for Stockfish if `RUNPOD_STOCKFISH_ENDPOINT_ID` is unset.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python start_workers.py
```

## Railway

- Start command: `python start_workers.py`
- Set env vars listed above.

## Direct migration

If you are not preserving an existing deployment, use this layout directly:
- Railway dispatcher service: `wood_league_dispatchers`
- RunPod Stockfish worker: `wood_league_chess_runpod`
- RunPod Lc0 worker: `wood_league_lc0_runpod`

The older mixed submitter/runtime paths in `wood_league_stockfish` and `wood_league_lc0` can be treated as source material rather than deployment targets.
