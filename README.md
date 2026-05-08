# wood_league_lc0_runpod

RunPod Serverless worker for Lc0 game analysis.

This is now the canonical Lc0 RunPod worker repo for Wood League Chess.

## What it does

- Receives jobs with `game_id` and `pgn`
- Runs Lc0 analysis
- Writes `lc0_game_analysis` and `lc0_move_analysis` directly to PostgreSQL
- Marks matching `analysis_jobs` row as `completed`

## Environment variables

Required:
- `DATABASE_URL` (`postgres://...` or `postgresql://...`; worker forces psycopg v3)

Optional:
- `LC0_PATH` (default: `/usr/local/bin/lc0`)
- `LC0_NODES` (default: `25000`)
- `LC0_NETWORK` (default: `/usr/local/share/lc0-network.pb.gz`)
- `LC0_BACKEND` (default: `cudnn-fp16`; built binary supports `cuda` and `cudnn-fp16` backends)
- `LC0_SYZYGY_PATH` (default: `/runpod-volume/syzygy`, directory containing `.rtbw` and `.rtbz`)

## Build and run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

export DATABASE_URL="postgresql://user:pass@host/db"
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
