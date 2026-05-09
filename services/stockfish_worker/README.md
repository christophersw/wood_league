# wood_league_chess_runpod

RunPod Serverless CPU worker for Stockfish game analysis.

## What it does

Receives a job payload with a `job_id` and PGN string, runs Stockfish analysis,
and reports results to the Django API via `POST /api/v1/jobs/{id}/complete/`.
No direct database access — all persistence goes through the HTTP API.
Scales to zero when idle ($0 cost).

**RunPod job input payload** (set by the dispatcher):

```json
{
  "job_id": 123,
  "pgn": "1. e4 e5 ...",
  "depth": 20,
  "threads": 8,
  "hash_mb": 2048
}
```

## Local testing

```bash
pip install -r requirements.txt

export WORKER_API_URL="https://app.example.com"
export WORKER_API_KEY="your-worker-api-key"
export STOCKFISH_PATH="/usr/local/bin/stockfish"
export SYZYGY_PATH="/runpod-volume/syzygy"

# RunPod SDK reads test_input.json and calls handler() without a RunPod account
python handler.py
```

## Docker build

```bash
# Copy pipeline package first
cp -r ../wood_league_stockfish/stockfish_pipeline .

docker build -t yourdockerhub/wood-league-chess-worker .
docker push yourdockerhub/wood-league-chess-worker
```

## Automated Docker Hub publish (GitHub Actions)

This repository uses a 2-step GitHub Actions flow:

1. PR validation workflow (`.github/workflows/docker-pr-build.yml`)
	- Trigger: pull requests to `main`/`master` when Docker-related files change
	- Action: builds the image only (no Docker Hub push)
	- Purpose: catch Docker/build issues before merge

2. Publish workflow (`.github/workflows/docker-publish.yml`)
	- Trigger: pushes to `main`/`master` when Docker-related files change
	- Action: builds and pushes the image to Docker Hub

Watched paths:
- `Dockerfile`
- `requirements.txt`
- `handler.py`
- `stockfish_pipeline/**`
- `.github/workflows/docker-pr-build.yml`
- `.github/workflows/docker-publish.yml`

It publishes two tags:
- `latest`
- short commit SHA (for example: `sha-abc1234`)

Set these GitHub repository secrets before using it:
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN` (Docker Hub access token, not your password)

Both workflows can also be run manually from the Actions tab via `workflow_dispatch`.

## RunPod endpoint settings

| Setting | Value |
|---|---|
| Container image | your Docker Hub image |
| CPU type | Compute Optimized |
| Min workers (Active) | `0` |
| Max workers (Flex) | `10` |
| Idle timeout | `5` seconds |
| Execution timeout | `300` seconds |
| Container disk | `5 GB` |

## Environment variables (set in RunPod dashboard)

| Variable | Required | Default | Description |
|---|---|---|---|
| `WORKER_API_URL` | Yes | — | Base URL of the Django app, e.g. `https://app.example.com` |
| `WORKER_API_KEY` | Yes | — | Raw worker API key (`X-Api-Key`) |
| `STOCKFISH_PATH` | No | `/usr/games/stockfish` | Path to Stockfish binary |
| `ANALYSIS_DEPTH` | No | `20` | Default analysis depth (overridden per-job by payload) |
| `ANALYSIS_THREADS` | No | `8` | Default thread count |
| `ANALYSIS_HASH_MB` | No | `2048` | Default hash table size in MB |
| `SYZYGY_PATH` | No | `/runpod-volume/syzygy` | Folder containing `.rtbw` and `.rtbz` files |
