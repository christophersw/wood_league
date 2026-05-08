# Wood League Monorepo Design

**Date:** 2026-05-07  
**Status:** Approved  
**Author:** Chris Webster

## Problem

The wood_league project is currently split across 4 separate git repos:

- `wood_league_app` — Django web app (Railway)
- `wood_league_dispatchers` — RunPod job dispatcher (Railway)
- `wood_league_stockfish_runpod` — Stockfish analysis worker (RunPod)
- `wood_league_lc0_runpod` — Lc0 neural net analysis worker (RunPod)

This causes three concrete problems:
1. **Code duplication** — `storage/models.py`, `chesscom_client.py`, `sync_service.py`, and `opening_book.py` are duplicated across services and drift out of sync
2. **Developer experience** — context-switching between 4 repos, 4 environments, 4 issue trackers
3. **Tooling** — vexp can't build a full semantic index across all services; one git-issue instance per repo

## Solution

Merge into a single monorepo using **uv workspaces**, extract shared code into a `wood_league_shared` internal package, and configure Railway/RunPod to deploy each service independently from the single repo.

---

## Repository Structure

```
wood_league/                            ← single git repo, single origin
├── pyproject.toml                      ← uv workspace root (not a package itself)
├── uv.lock                             ← single lockfile for all services
├── README.md                           ← project overview and quickstart
├── .issues/                            ← single git-issue tracker for all services
├── docs/
│   ├── architecture.md                 ← how services fit together
│   ├── deployment.md                   ← Railway + RunPod deployment guide
│   ├── shared-package.md               ← wood_league_shared API reference
│   └── adr/
│       └── 001-monorepo.md             ← decision record for this migration
├── packages/
│   └── shared/                         ← wood_league_shared internal package
│       ├── pyproject.toml
│       └── wood_league_shared/
│           ├── __init__.py
│           ├── storage/
│           │   ├── models.py           ← SQLAlchemy models (was duplicated)
│           │   └── database.py         ← DB session/connection logic
│           ├── ingest/
│           │   ├── chesscom_client.py  ← chess.com API client (was duplicated)
│           │   └── sync_service.py     ← sync orchestration (was duplicated)
│           └── services/
│               └── opening_book.py     ← opening book logic (was duplicated)
├── services/
│   ├── app/                            ← Django web app → Railway
│   │   ├── pyproject.toml
│   │   ├── railway.toml
│   │   └── README.md
│   ├── dispatchers/                    ← dispatcher service → Railway
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   ├── railway.toml
│   │   └── README.md
│   ├── stockfish_worker/               ← Stockfish analysis → RunPod
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── README.md
│   └── lc0_worker/                     ← Lc0 neural net analysis → RunPod
│       ├── pyproject.toml
│       ├── Dockerfile
│       └── README.md
└── scripts/
    └── build-runpod.sh                 ← builds + pushes RunPod Docker images
```

---

## uv Workspace Configuration

### Root `pyproject.toml`

```toml
[tool.uv.workspace]
members = [
    "packages/shared",
    "services/app",
    "services/dispatchers",
    "services/stockfish_worker",
    "services/lc0_worker",
]
```

### Service `pyproject.toml` (example: stockfish_worker)

```toml
[project]
name = "wood-league-stockfish-worker"
requires-python = ">=3.11"
dependencies = [
    "wood-league-shared",
    "runpod>=1.7.0",
    "python-chess>=1.999",
]

[tool.uv.sources]
wood-league-shared = { workspace = true }
```

Local development: `uv sync` at repo root installs all services into a single venv.

---

## Shared Package

### Rule for inclusion

A module belongs in `wood_league_shared` if:
- Two or more services import it, **and**
- It contains no service-specific logic (no RunPod handler code, no Django views, no Railway start commands)

### Initial contents

| Module | Currently duplicated in |
|--------|------------------------|
| `storage/models.py` | dispatchers, stockfish_worker, lc0_worker |
| `storage/database.py` | stockfish_worker, lc0_worker |
| `ingest/chesscom_client.py` | dispatchers, stockfish_worker |
| `ingest/sync_service.py` | dispatchers, stockfish_worker |
| `services/opening_book.py` | stockfish_worker, app |

---

## Railway Deployment

Railway supports monorepos via a **Root Directory** setting per service. Each Railway service is configured to point at its subdirectory (`services/app`, `services/dispatchers`). Railway only redeploys a service when files within its root directory change.

### Shared package dependency

Since Railpack/Nixpacks build from the service root directory (not the repo root), they cannot directly see `packages/shared/`. The shared package is declared as a **git dependency** in each Railway service's `pyproject.toml`:

```toml
[tool.uv.sources]
wood-league-shared = { git = "https://github.com/christophersw/wood_league", subdirectory = "packages/shared" }
```

This lets Railway resolve the shared package at build time with no extra infrastructure.

### Railway service configuration summary

| Service | Root Directory | Builder |
|---------|---------------|---------|
| app | `services/app` | Railpack |
| dispatchers | `services/dispatchers` | Nixpacks / Dockerfile |

---

## RunPod Docker Build Strategy

RunPod workers are Docker images pushed to a registry. Dockerfiles are written to accept the **repo root as the build context**, which lets them copy from `packages/shared/` directly.

### Dockerfile pattern

```dockerfile
# services/stockfish_worker/Dockerfile
# Build with: docker build -f services/stockfish_worker/Dockerfile .

FROM python:3.11-slim
# ... system deps ...

WORKDIR /app

# Shared package first for better layer caching
COPY packages/shared ./packages/shared

# Service code
COPY services/stockfish_worker/pyproject.toml .
COPY services/stockfish_worker/handler.py .
COPY services/stockfish_worker/stockfish_pipeline ./stockfish_pipeline

RUN pip install uv && uv sync --no-dev

CMD ["python", "handler.py"]
```

### Build script (`scripts/build-runpod.sh`)

```bash
#!/usr/bin/env bash
# Usage: ./scripts/build-runpod.sh stockfish_worker v1.2.3
SERVICE=$1
TAG=$2
docker build \
  -f services/${SERVICE}/Dockerfile \
  -t your-registry/${SERVICE}:${TAG} \
  .
docker push your-registry/${SERVICE}:${TAG}
```

---

## Documentation Structure

| Location | Contents |
|----------|----------|
| `/README.md` | Project overview, architecture diagram, quickstart for all services |
| `/docs/architecture.md` | How the 4 services interact, data flow, RunPod/Railway topology |
| `/docs/deployment.md` | Railway dashboard setup, RunPod image build + deploy steps |
| `/docs/shared-package.md` | `wood_league_shared` module reference |
| `/docs/adr/001-monorepo.md` | Why we moved to a monorepo |
| `services/*/README.md` | Per-service: local setup, env vars, service-specific deployment notes |
| `packages/shared/README.md` | Shared package API and contribution guide |

---

## Issue Tracking

A single `git issue` tracker lives at the monorepo root. All four existing issue trackers are abandoned; open issues are noted in the ADR before the old repos are archived. Initialize with:

```bash
git issue init
cp services/app/.issues/.config.yml .issues/.config.yml  # use existing config as template
```

---

## Migration Plan

### Phase 0 — Prepare (no code changes)
- Consolidate and rewrite documentation into the target structure
- Note any open issues in existing `.issues/` trackers (for reference during archive)
- Establish the ADR for this migration

### Phase 1 — Merge git histories
- Use `git subtree add` to pull each of the 4 repos into the monorepo with full commit history preserved
- Target directories: `services/app`, `services/dispatchers`, `services/stockfish_worker`, `services/lc0_worker`
- Push as the new single origin

### Phase 2 — Add uv workspace root
- Add root `pyproject.toml` declaring workspace members
- Run `uv sync` and verify all services install cleanly
- No code changes yet — verify existing tests pass

### Phase 3 — Extract shared package
- Create `packages/shared/wood_league_shared/`
- Move duplicated modules in (storage, ingest, opening_book)
- Update imports across all services
- Run all tests to verify nothing broken

### Phase 4 — Update RunPod Dockerfiles
- Rewrite `services/stockfish_worker/Dockerfile` and `services/lc0_worker/Dockerfile` to build from repo root
- Test locally: `docker build -f services/stockfish_worker/Dockerfile .`
- Update any CI steps that invoke `docker build`

### Phase 5 — Update Railway services
- Set Root Directory per service in Railway dashboard
- Add git dependency for `wood-league-shared` to Railway service `pyproject.toml` files
- Redeploy each service and verify health checks pass

### Phase 6 — Initialize git-issue
- `git issue init` at monorepo root
- Copy `.issues/.config.yml` from `services/app` as template

### Phase 7 — Archive old repos
- Once monorepo is live and stable for one deployment cycle
- Update each old repo README to point to the new monorepo
- Archive all 4 repos on GitHub
