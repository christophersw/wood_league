# ADR 001 — Consolidate to Monorepo

**Date:** 2026-05-07
**Status:** Accepted

## Context

Four separate git repos caused code duplication (`storage/models.py`,
`chesscom_client.py`, `sync_service.py`, `opening_book.py`), context-switching
overhead, and tooling fragmentation (4 issue trackers, vexp couldn't build a
full cross-service index).

## Decision

Merge into a single uv-workspace monorepo at `github.com/christophersw/wood_league`.
Extract shared code into `packages/shared` (`wood_league_shared`). Deploy Railway
services via per-service Root Directory config. Build RunPod Docker images from
the repo root.

## Consequences

- Single git history and issue tracker
- One `uv sync` installs all services locally
- Shared code changes are immediately visible to all consumers
- Railway git dependency (`wood-league-shared @ git+...`) resolves shared code at build time
- RunPod Dockerfiles must be built with repo root as context (breaking change from old per-repo build)
