# Deployment Guide

## Railway Services

Both `app` and `dispatchers` deploy automatically on push to `main` when files
in their root directory or `packages/shared` change.

### Railway Dashboard Setup (one-time)

| Service | Root Directory | Watch Paths |
|---------|---------------|-------------|
| app | `services/app` | `services/app/**`, `packages/shared/**` |
| dispatchers | `services/dispatchers` | `services/dispatchers/**`, `packages/shared/**` |

### Environment Variables

**app service:** `DATABASE_URL`, `SECRET_KEY`, `ALLOWED_HOSTS`, `RUNPOD_API_KEY`

**dispatchers service:** `DATABASE_URL`, `RUNPOD_API_KEY`, `CHESS_COM_USER_AGENT`,
`CHESS_COM_USERNAMES`, `STOCKFISH_ENDPOINT_ID`, `LC0_ENDPOINT_ID`

## RunPod Workers

RunPod workers are deployed as Docker images. Build and push with:

```bash
./scripts/build-runpod.sh stockfish_worker v1.0.0 docker.io/christophersw
./scripts/build-runpod.sh lc0_worker v1.0.0 docker.io/christophersw
```

Then update the RunPod endpoint's Docker image in the RunPod dashboard.

### RunPod Environment Variables

**stockfish_worker:** `DATABASE_URL`, `STOCKFISH_PATH=/usr/games/stockfish`,
`CHESS_COM_USER_AGENT`, `ANALYSIS_DEPTH`, `ANALYSIS_THREADS`, `ANALYSIS_HASH_MB`

**lc0_worker:** `DATABASE_URL`, `LC0_PATH=/usr/local/bin/lc0`,
`LC0_NETWORK=/usr/local/share/lc0-network.pb.gz`
