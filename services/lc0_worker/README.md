# wood_league_lc0_runpod

RunPod Serverless worker for Lc0 game analysis.

This is now the canonical Lc0 RunPod worker repo for Wood League Chess.

## What it does

- Receives jobs with `job_id` and `pgn` (sent by the RunPod dispatcher)
- Runs Lc0 analysis
- Reports results to the Django API via `POST /api/v1/jobs/{id}/complete/`
- No direct database access — all persistence goes through the HTTP API

**RunPod job input payload** (set by the dispatcher):

```json
{
  "job_id": 456,
  "pgn": "1. d4 d5 ...",
  "nodes": 25000,
  "weights_path": "/path/to/network.pb.gz"
}
```

## Environment variables

Required:
- `WORKER_API_URL` — base URL of the Django app, e.g. `https://app.example.com`
- `WORKER_API_KEY` — raw worker API key (`X-Api-Key`)

Optional:
- `LC0_PATH` (default: `/usr/local/bin/lc0`)
- `LC0_NODES` (default: `25000` — overridden per-job by payload)
- `LC0_NETWORK` (default: empty — overridden per-job by payload)
- `LC0_BACKEND` (default: `cudnn-fp16`; built binary supports `cuda` and `cudnn-fp16`)
- `LC0_SYZYGY_PATH` (default: `/runpod-volume/syzygy`, directory containing `.rtbw` and `.rtbz`)

## Build and run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

export WORKER_API_URL="https://app.example.com"
export WORKER_API_KEY="your-worker-api-key"
export LC0_PATH="/usr/local/bin/lc0"
python handler.py
```

## Docker image

```bash
docker build -t <docker-username>/wood-league-lc0-runpod:latest .
docker push <docker-username>/wood-league-lc0-runpod:latest
```

## Automated Docker Hub publish

This repository now includes GitHub Actions workflows that:
- build the Docker image on pull requests without pushing
- build and push the image to Docker Hub on pushes to `main` or `master`

Published tags:
- `latest`
- short commit SHA (for example: `sha-abc1234`)

Required GitHub repository secrets:
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

Workflow files:
- `.github/workflows/docker-pr-build.yml`
- `.github/workflows/docker-publish.yml`

## Direct migration

Use this repo as the only Lc0 RunPod image source.

With the new layout:
- `wood_league_dispatchers` submits Lc0 jobs to RunPod
- `wood_league_lc0_runpod` executes Lc0 analysis on RunPod
- `wood_league_lc0` no longer needs to be the deployed submitter/image repo
