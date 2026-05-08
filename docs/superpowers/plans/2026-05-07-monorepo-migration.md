# Wood League Monorepo Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge four separate git repos into a single uv-workspace monorepo with a shared internal package, unified documentation, and per-service Railway/RunPod deployment configs.

**Architecture:** Root `pyproject.toml` declares a uv workspace with five members (`packages/shared` + four services). The `wood_league_shared` internal package contains all code duplicated across services. Railway services use a git dependency to resolve `wood_league_shared` at build time; RunPod Dockerfiles are built from the repo root to access `packages/shared` directly.

**Tech Stack:** Python 3.11/3.13, uv workspaces, git subtree, Django/Railpack (app service), Nixpacks/Dockerfile (dispatchers), Docker/RunPod Serverless (stockfish_worker + lc0_worker)

**Spec:** `docs/superpowers/specs/2026-05-07-monorepo-design.md`

---

> ⚠️ **Before starting:** Ensure all four sub-repos have clean working trees with all changes pushed to GitHub. Verify with `git status` in each of: `wood_league_app/`, `wood_league_dispatchers/`, `wood_league_stockfish_runpod/`, `wood_league_lc0_runpod/`.

---

## Phase A: Repository Structure (Phases 0–2 of spec)

### Task 1: Create the GitHub monorepo and initialize git at the workspace root

**Files:**
- Create: `.gitignore`
- Create: `README.md` (placeholder)

- [ ] **Step 1: Create the new GitHub repo**

  Go to https://github.com/new and create a public repo named `wood_league`. Do NOT initialize it with a README, .gitignore, or license.

- [ ] **Step 2: Initialize git at the workspace root**

  ```bash
  cd /Users/christopherwebster/Projects/wood_league
  git init
  ```

- [ ] **Step 3: Create .gitignore to exclude old sub-repo directories and venvs**

  Create `/Users/christopherwebster/Projects/wood_league/.gitignore`:

  ```gitignore
  # Old sub-repo directories (will be removed after git subtree adds)
  /wood_league_app/
  /wood_league_dispatchers/
  /wood_league_stockfish_runpod/
  /wood_league_lc0_runpod/

  # Python
  __pycache__/
  *.pyc
  *.pyo
  .venv/
  .snyk-venv/
  *.egg-info/

  # Database
  *.db
  *.db-shm
  *.db-wal

  # Environment
  .env

  # vexp runtime (index files tracked separately)
  .vexp/daemon.log
  .vexp/daemon.pid
  .vexp/daemon.sock
  .vexp/healthy
  .vexp/index.db-shm
  .vexp/index.db-wal

  # OS
  .DS_Store
  ```

- [ ] **Step 4: Create a placeholder README.md**

  Create `/Users/christopherwebster/Projects/wood_league/README.md`:

  ```markdown
  # Wood League

  Chess club analytics platform. See `docs/architecture.md` for system overview.

  ## Services

  | Service | Description | Deployment |
  |---------|-------------|------------|
  | `services/app` | Django web application | Railway |
  | `services/dispatchers` | RunPod job dispatcher | Railway |
  | `services/stockfish_worker` | Stockfish analysis worker | RunPod |
  | `services/lc0_worker` | Lc0 neural net analysis worker | RunPod |

  ## Local Development

  ```bash
  # Install uv if needed
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # Install all workspace members
  uv sync
  ```
  ```

- [ ] **Step 5: Stage and commit the root files**

  ```bash
  git add .gitignore README.md CLAUDE.md AGENTS.md IMPLEMENTATION_SUMMARY.md vexp.toml
  git commit -m "chore: initialize monorepo root with existing workspace files"
  ```

- [ ] **Step 6: Add the GitHub remote and push**

  ```bash
  git remote add origin https://github.com/christophersw/wood_league.git
  git branch -M main
  git push -u origin main
  ```

---

### Task 2: Merge wood_league_app history into services/app

**Files:**
- Create: `services/app/` (via git subtree)

- [ ] **Step 1: Add remote and fetch**

  ```bash
  git remote add wood_league_app https://github.com/christophersw/wood_league_app.git
  git fetch wood_league_app
  ```

- [ ] **Step 2: Merge the history into services/app**

  ```bash
  git subtree add --prefix=services/app wood_league_app main --squash
  ```

  Expected: A merge commit is created. `services/app/` now contains the full app codebase.

- [ ] **Step 3: Verify the directory exists**

  ```bash
  ls services/app/
  ```

  Expected: `manage.py`, `pyproject.toml`, `railway.toml`, `requirements.txt` and the Django app directories.

---

### Task 3: Merge wood_league_dispatchers history into services/dispatchers

**Files:**
- Create: `services/dispatchers/` (via git subtree)

- [ ] **Step 1: Add remote and fetch**

  ```bash
  git remote add wood_league_dispatchers https://github.com/christophersw/wood_league_dispatchers.git
  git fetch wood_league_dispatchers
  ```

- [ ] **Step 2: Merge the history into services/dispatchers**

  ```bash
  git subtree add --prefix=services/dispatchers wood_league_dispatchers main --squash
  ```

- [ ] **Step 3: Verify**

  ```bash
  ls services/dispatchers/
  ```

  Expected: `Dockerfile`, `pyproject.toml`, `railway.toml`, `start_workers.py`, `dispatchers/`.

---

### Task 4: Merge wood_league_stockfish_runpod history into services/stockfish_worker

**Files:**
- Create: `services/stockfish_worker/` (via git subtree)

- [ ] **Step 1: Add remote and fetch**

  ```bash
  git remote add wood_league_stockfish_runpod https://github.com/christophersw/wood_league_stockfish_runpod.git
  git fetch wood_league_stockfish_runpod
  ```

- [ ] **Step 2: Merge into services/stockfish_worker**

  ```bash
  git subtree add --prefix=services/stockfish_worker wood_league_stockfish_runpod main --squash
  ```

- [ ] **Step 3: Verify**

  ```bash
  ls services/stockfish_worker/
  ```

  Expected: `Dockerfile`, `handler.py`, `pyproject.toml`, `requirements.txt`, `stockfish_pipeline/`.

---

### Task 5: Merge wood_league_lc0_runpod history into services/lc0_worker

**Files:**
- Create: `services/lc0_worker/` (via git subtree)

- [ ] **Step 1: Add remote and fetch**

  ```bash
  git remote add wood_league_lc0_runpod https://github.com/christophersw/wood_league_lc0_runpod.git
  git fetch wood_league_lc0_runpod
  ```

- [ ] **Step 2: Merge into services/lc0_worker**

  ```bash
  git subtree add --prefix=services/lc0_worker wood_league_lc0_runpod main --squash
  ```

- [ ] **Step 3: Verify**

  ```bash
  ls services/lc0_worker/
  ```

  Expected: `Dockerfile`, `handler.py`, `pyproject.toml`, `lc0_worker/`.

- [ ] **Step 4: Remove the old remotes (cleanup)**

  ```bash
  git remote remove wood_league_app
  git remote remove wood_league_dispatchers
  git remote remove wood_league_stockfish_runpod
  git remote remove wood_league_lc0_runpod
  ```

- [ ] **Step 5: Push all merged history to origin**

  ```bash
  git push origin main
  ```

---

### Task 6: Add uv workspace root and verify install

**Files:**
- Create: `pyproject.toml` (workspace root)

- [ ] **Step 1: Install uv if not already installed**

  ```bash
  which uv || curl -LsSf https://astral.sh/uv/install.sh | sh
  uv --version
  ```

  Expected: version printed (e.g. `uv 0.4.x`).

- [ ] **Step 2: Create the workspace root pyproject.toml**

  Create `/Users/christopherwebster/Projects/wood_league/pyproject.toml`:

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

- [ ] **Step 3: Create the packages/shared scaffold (empty, real content in Phase B)**

  ```bash
  mkdir -p packages/shared/wood_league_shared
  ```

  Create `packages/shared/pyproject.toml`:

  ```toml
  [project]
  name = "wood-league-shared"
  version = "0.1.0"
  description = "Shared internal library for Wood League services"
  requires-python = ">=3.11"
  dependencies = [
      "sqlalchemy>=2.0.29",
      "psycopg[binary]>=3.2.0",
      "python-chess>=1.999",
  ]

  [build-system]
  requires = ["setuptools>=68", "wheel"]
  build-backend = "setuptools.build_meta"

  [tool.setuptools.packages.find]
  where = ["."]
  include = ["wood_league_shared*"]
  ```

  Create `packages/shared/wood_league_shared/__init__.py`:

  ```python
  # wood_league_shared — internal shared library for Wood League services
  ```

- [ ] **Step 4: Run uv sync to verify the workspace resolves**

  ```bash
  uv sync
  ```

  Expected: uv resolves all workspace members and creates `uv.lock`. No errors. (Some members may fail to install due to system deps like Stockfish/CUDA — that is expected at this stage.)

- [ ] **Step 5: Commit**

  ```bash
  git add pyproject.toml packages/
  git commit -m "chore: add uv workspace root and packages/shared scaffold"
  git push origin main
  ```

---

## Phase B: Shared Package Extraction (Phase 3 of spec)

> ⚠️ **Before starting Phase B:** All four services are still using their original import namespaces (`stockfish_pipeline.*`, `dispatchers.*`, `lc0_worker.*`). Phase B moves the duplicated modules to `wood_league_shared` and updates all import sites. Work through Tasks 7–14 in order without skipping — each task depends on the previous.

---

### Task 7: Move storage/models.py to the shared package

The `storage/models.py` is duplicated in all three worker services with identical SQLAlchemy models. The canonical version lives in `services/stockfish_worker/stockfish_pipeline/storage/models.py`.

**Files:**
- Create: `packages/shared/wood_league_shared/storage/__init__.py`
- Create: `packages/shared/wood_league_shared/storage/models.py`

- [ ] **Step 1: Compare the three models files to confirm they can be safely merged**

  ```bash
  diff services/stockfish_worker/stockfish_pipeline/storage/models.py \
       services/dispatchers/dispatchers/models.py
  diff services/stockfish_worker/stockfish_pipeline/storage/models.py \
       services/lc0_worker/lc0_worker/storage/models.py
  ```

  Expected: diffs show only import path differences, not structural model differences. If there are real schema differences, resolve them manually before continuing — the shared version must be the superset.

- [ ] **Step 2: Create the storage package in shared**

  ```bash
  touch packages/shared/wood_league_shared/storage/__init__.py
  ```

- [ ] **Step 3: Copy the canonical models.py to shared, updating the import**

  Copy `services/stockfish_worker/stockfish_pipeline/storage/models.py` to `packages/shared/wood_league_shared/storage/models.py`. The file has no internal imports from `stockfish_pipeline`, so no edits are needed. Verify:

  ```bash
  grep "from stockfish_pipeline\|from dispatchers\|from lc0_worker" \
    packages/shared/wood_league_shared/storage/models.py
  ```

  Expected: no output (no internal namespace imports).

- [ ] **Step 4: Commit the new shared models**

  ```bash
  git add packages/shared/wood_league_shared/storage/
  git commit -m "feat(shared): add canonical storage/models.py to wood_league_shared"
  ```

---

### Task 8: Move storage/database.py to the shared package

The stockfish version imports from `stockfish_pipeline.config`; the dispatchers version uses `os.environ` directly (better for a shared library). The shared version uses the dispatchers pattern with the stockfish SQLite fallback for local dev.

**Files:**
- Create: `packages/shared/wood_league_shared/storage/database.py`

- [ ] **Step 1: Create the canonical shared database.py**

  Create `packages/shared/wood_league_shared/storage/database.py`:

  ```python
  """
  Title: database.py — SQLAlchemy engine and session factory
  Description:
      Builds the SQLAlchemy engine from the DATABASE_URL environment variable.
      Falls back to a local SQLite file for development when DATABASE_URL is unset.
      Exports ENGINE, get_session(), and init_db() for use by all services.

  Changelog:
      2026-05-07: Extracted from stockfish_pipeline and dispatchers into shared library
  """
  from __future__ import annotations

  import os
  from contextlib import contextmanager

  from sqlalchemy import create_engine
  from sqlalchemy.orm import Session, sessionmaker

  from wood_league_shared.storage.models import Base


  def _normalize_database_url(database_url: str) -> str:
      """Normalize any postgres:// variant to the psycopg3 driver scheme."""
      if database_url.startswith("postgresql+psycopg://"):
          return database_url
      if database_url.startswith("postgresql://"):
          return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
      if database_url.startswith("postgres://"):
          return database_url.replace("postgres://", "postgresql+psycopg://", 1)
      return database_url


  def _build_engine():
      url = os.environ.get("DATABASE_URL", "")
      if url:
          return create_engine(_normalize_database_url(url), pool_pre_ping=True)
      return create_engine("sqlite+pysqlite:///wood_league_chess.db", pool_pre_ping=True)


  ENGINE = _build_engine()
  SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


  def init_db() -> None:
      """Create all tables defined in the shared models if they do not exist."""
      Base.metadata.create_all(ENGINE)


  @contextmanager
  def get_session() -> Session:
      """Yield a SQLAlchemy session and close it when done."""
      session = SessionLocal()
      try:
          yield session
      finally:
          session.close()
  ```

- [ ] **Step 2: Commit**

  ```bash
  git add packages/shared/wood_league_shared/storage/database.py
  git commit -m "feat(shared): add canonical storage/database.py to wood_league_shared"
  ```

---

### Task 9: Move ingest/chesscom_client.py to the shared package

The dispatchers version is the canonical shared version — it takes `user_agent` as a constructor param (no config dependency). The stockfish version currently reads from config; after this task, its callers will pass `user_agent` explicitly.

**Files:**
- Create: `packages/shared/wood_league_shared/ingest/__init__.py`
- Create: `packages/shared/wood_league_shared/ingest/chesscom_client.py`

- [ ] **Step 1: Create the ingest package in shared**

  ```bash
  touch packages/shared/wood_league_shared/ingest/__init__.py
  ```

- [ ] **Step 2: Create the canonical shared chesscom_client.py**

  Create `packages/shared/wood_league_shared/ingest/chesscom_client.py`:

  ```python
  """
  Title: chesscom_client.py — Chess.com public API client
  Description:
      Fetches game archives and game data from the Chess.com public API.
      Accepts user_agent as a constructor parameter; falls back to an env var
      or a default string. Has no dependency on service-specific config modules.

  Changelog:
      2026-05-07: Merged from dispatchers and stockfish_pipeline into shared library
  """
  from __future__ import annotations

  import json
  import os
  import urllib.request
  from typing import Any


  class ChessComClient:
      def __init__(self, user_agent: str | None = None) -> None:
          self._user_agent = user_agent or os.environ.get(
              "CHESS_COM_USER_AGENT", "wood-league/0.1"
          )

      def _get_json(self, url: str) -> dict[str, Any]:
          request = urllib.request.Request(
              url,
              headers={
                  "User-Agent": self._user_agent,
                  "Accept": "application/json",
              },
          )
          with urllib.request.urlopen(request, timeout=30) as response:
              return json.loads(response.read().decode("utf-8"))

      def get_archives(self, username: str) -> list[str]:
          """Return list of monthly archive URLs for a Chess.com player."""
          endpoint = f"https://api.chess.com/pub/player/{username}/games/archives"
          payload = self._get_json(endpoint)
          return payload.get("archives", [])

      def get_games_for_archive(self, archive_url: str) -> list[dict[str, Any]]:
          """Return list of game dicts for a given monthly archive URL."""
          payload = self._get_json(archive_url)
          return payload.get("games", [])
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add packages/shared/wood_league_shared/ingest/
  git commit -m "feat(shared): add canonical ingest/chesscom_client.py to wood_league_shared"
  ```

---

### Task 10: Move ingest/sync_service.py to the shared package

The dispatchers version is the canonical shared version — it takes `ingest_month_limit` and `user_agent` as constructor params. The stockfish version reads these from config; its callers will need to pass them explicitly after this task.

**Files:**
- Create: `packages/shared/wood_league_shared/ingest/sync_service.py`

- [ ] **Step 1: Compare the two sync_service.py files**

  ```bash
  diff services/stockfish_worker/stockfish_pipeline/ingest/sync_service.py \
       services/dispatchers/dispatchers/ingest/sync_service.py
  ```

  Note any functional differences in the sync logic (not just import paths). The dispatchers version has `inserted_game_ids` in `SyncStats` and a `sync_many` convenience method — both should be in the canonical shared version.

- [ ] **Step 2: Create the canonical shared sync_service.py**

  Copy `services/dispatchers/dispatchers/ingest/sync_service.py` to `packages/shared/wood_league_shared/ingest/sync_service.py`, then update the imports at the top:

  Replace:
  ```python
  from dispatchers.db import get_session, init_db
  from dispatchers.ingest.chesscom_client import ChessComClient
  from dispatchers.models import Game, GameParticipant, Player
  ```

  With:
  ```python
  from wood_league_shared.storage.database import get_session, init_db
  from wood_league_shared.ingest.chesscom_client import ChessComClient
  from wood_league_shared.storage.models import Game, GameParticipant, Player
  ```

  Also add a file header docstring at the top:
  ```python
  """
  Title: sync_service.py — Chess.com game sync service
  Description:
      Fetches and persists Chess.com game archives for a list of usernames.
      Parameterized via constructor — no direct config module dependency.

  Changelog:
      2026-05-07: Merged from dispatchers and stockfish_pipeline into shared library
  """
  ```

- [ ] **Step 3: Verify no internal namespace imports remain**

  ```bash
  grep "from dispatchers\|from stockfish_pipeline\|from lc0_worker" \
    packages/shared/wood_league_shared/ingest/sync_service.py
  ```

  Expected: no output.

- [ ] **Step 4: Commit**

  ```bash
  git add packages/shared/wood_league_shared/ingest/sync_service.py
  git commit -m "feat(shared): add canonical ingest/sync_service.py to wood_league_shared"
  ```

---

### Task 11: Move services/opening_book.py to the shared package

The opening_book.py is identical in `services/stockfish_worker/stockfish_pipeline/services/opening_book.py` and `services/app/app/services/opening_book.py`. Verify, then move.

**Files:**
- Create: `packages/shared/wood_league_shared/services/__init__.py`
- Create: `packages/shared/wood_league_shared/services/opening_book.py`

- [ ] **Step 1: Confirm they are identical**

  ```bash
  diff services/stockfish_worker/stockfish_pipeline/services/opening_book.py \
       services/app/app/services/opening_book.py
  ```

  Expected: no output (files are identical). If there are differences, merge them manually — keep all functionality, use the stockfish version as the base.

- [ ] **Step 2: Create the services package in shared**

  ```bash
  touch packages/shared/wood_league_shared/services/__init__.py
  ```

- [ ] **Step 3: Copy to shared, updating internal imports**

  ```bash
  cp services/stockfish_worker/stockfish_pipeline/services/opening_book.py \
     packages/shared/wood_league_shared/services/opening_book.py
  ```

  Check if it imports from `stockfish_pipeline`:
  ```bash
  grep "from stockfish_pipeline\|from dispatchers\|from lc0_worker\|from app" \
    packages/shared/wood_league_shared/services/opening_book.py
  ```

  Update any such imports to use `wood_league_shared.*`.

- [ ] **Step 4: Commit**

  ```bash
  git add packages/shared/wood_league_shared/services/
  git commit -m "feat(shared): add services/opening_book.py to wood_league_shared"
  ```

---

### Task 12: Update imports in services/stockfish_worker

Replace all imports of the now-shared modules. The stockfish service also needs to pass `user_agent` and `ingest_month_limit` explicitly to `ChessComClient` and `ChessComSyncService` since those are no longer read from config internally.

**Files:**
- Modify: `services/stockfish_worker/stockfish_pipeline/ingest/sync_service.py` (delete — now in shared)
- Modify: `services/stockfish_worker/stockfish_pipeline/ingest/chesscom_client.py` (delete — now in shared)
- Modify: `services/stockfish_worker/stockfish_pipeline/storage/models.py` (delete — now in shared)
- Modify: `services/stockfish_worker/stockfish_pipeline/storage/database.py` (delete — now in shared)
- Modify: `services/stockfish_worker/stockfish_pipeline/services/opening_book.py` (delete — now in shared)
- Modify: all files that import from the above

- [ ] **Step 1: Find all files that import from the modules being removed**

  ```bash
  grep -rl "from stockfish_pipeline\.storage\.models\|from stockfish_pipeline\.storage\.database\|from stockfish_pipeline\.ingest\.chesscom_client\|from stockfish_pipeline\.ingest\.sync_service\|from stockfish_pipeline\.services\.opening_book" \
    services/stockfish_worker/ --include="*.py"
  ```

- [ ] **Step 2: Update imports in each file found**

  For each file from Step 1, replace:

  | Old import | New import |
  |-----------|-----------|
  | `from stockfish_pipeline.storage.models import X` | `from wood_league_shared.storage.models import X` |
  | `from stockfish_pipeline.storage.database import X` | `from wood_league_shared.storage.database import X` |
  | `from stockfish_pipeline.ingest.chesscom_client import X` | `from wood_league_shared.ingest.chesscom_client import X` |
  | `from stockfish_pipeline.ingest.sync_service import X` | `from wood_league_shared.ingest.sync_service import X` |
  | `from stockfish_pipeline.services.opening_book import X` | `from wood_league_shared.services.opening_book import X` |

  Run these sed commands from the repo root:
  ```bash
  find services/stockfish_worker -name "*.py" -exec sed -i '' \
    -e 's/from stockfish_pipeline\.storage\.models import/from wood_league_shared.storage.models import/g' \
    -e 's/from stockfish_pipeline\.storage\.database import/from wood_league_shared.storage.database import/g' \
    -e 's/from stockfish_pipeline\.ingest\.chesscom_client import/from wood_league_shared.ingest.chesscom_client import/g' \
    -e 's/from stockfish_pipeline\.ingest\.sync_service import/from wood_league_shared.ingest.sync_service import/g' \
    -e 's/from stockfish_pipeline\.services\.opening_book import/from wood_league_shared.services.opening_book import/g' \
    {} \;
  ```

- [ ] **Step 3: Update sync_service caller in stockfish_worker**

  In `services/stockfish_worker/stockfish_pipeline/ingest/` find any file that instantiates `ChessComSyncService()` with no arguments and update it to pass settings explicitly. Open `services/stockfish_worker/stockfish_pipeline/ingest/run_sync.py` (or whichever file calls it) and change:

  ```python
  # Before
  service = ChessComSyncService()
  ```

  ```python
  # After
  from stockfish_pipeline.config import get_settings
  settings = get_settings()
  service = ChessComSyncService(
      ingest_month_limit=settings.ingest_month_limit,
      user_agent=settings.chess_com_user_agent,
  )
  ```

- [ ] **Step 4: Delete the now-redundant files from stockfish_worker**

  ```bash
  rm services/stockfish_worker/stockfish_pipeline/storage/models.py
  rm services/stockfish_worker/stockfish_pipeline/storage/database.py
  rm services/stockfish_worker/stockfish_pipeline/ingest/chesscom_client.py
  rm services/stockfish_worker/stockfish_pipeline/ingest/sync_service.py
  rm services/stockfish_worker/stockfish_pipeline/services/opening_book.py
  ```

- [ ] **Step 5: Update stockfish_worker pyproject.toml to depend on shared**

  Edit `services/stockfish_worker/pyproject.toml`. Add `wood-league-shared` to dependencies and add `[tool.uv.sources]`:

  ```toml
  [project]
  name = "wood-league-stockfish-worker"
  version = "0.1.0"
  description = "RunPod Serverless worker for Stockfish analysis"
  readme = "README.md"
  requires-python = ">=3.11"
  dependencies = [
      "wood-league-shared",
      "runpod>=1.7.0",
      "pydantic-settings>=2.8.0",
  ]

  [tool.uv.sources]
  wood-league-shared = { workspace = true }

  [tool.setuptools.packages.find]
  where = ["."]
  include = ["stockfish_pipeline*"]

  [build-system]
  requires = ["setuptools>=68", "wheel"]
  build-backend = "setuptools.build_meta"
  ```

- [ ] **Step 6: Verify imports resolve**

  ```bash
  grep -r "from stockfish_pipeline\.storage\.models\|from stockfish_pipeline\.storage\.database\|from stockfish_pipeline\.ingest\.chesscom_client\|from stockfish_pipeline\.ingest\.sync_service\|from stockfish_pipeline\.services\.opening_book" \
    services/stockfish_worker/ --include="*.py"
  ```

  Expected: no output.

- [ ] **Step 7: Commit**

  ```bash
  git add services/stockfish_worker/
  git commit -m "refactor(stockfish_worker): import shared modules from wood_league_shared"
  ```

---

### Task 13: Update imports in services/lc0_worker

**Files:**
- Modify: `services/lc0_worker/lc0_worker/storage/models.py` (delete — now in shared)
- Modify: `services/lc0_worker/lc0_worker/storage/database.py` (delete if exists — now in shared)
- Modify: all files that import from the above

- [ ] **Step 1: Find all files with shared-module imports**

  ```bash
  grep -rl "from lc0_worker\.storage\.models\|from lc0_worker\.storage\.database" \
    services/lc0_worker/ --include="*.py"
  ```

- [ ] **Step 2: Update imports**

  ```bash
  find services/lc0_worker -name "*.py" -exec sed -i '' \
    -e 's/from lc0_worker\.storage\.models import/from wood_league_shared.storage.models import/g' \
    -e 's/from lc0_worker\.storage\.database import/from wood_league_shared.storage.database import/g' \
    {} \;
  ```

- [ ] **Step 3: Delete the redundant files**

  ```bash
  rm services/lc0_worker/lc0_worker/storage/models.py
  # Only delete database.py if it exists:
  [ -f services/lc0_worker/lc0_worker/storage/database.py ] && \
    rm services/lc0_worker/lc0_worker/storage/database.py
  ```

- [ ] **Step 4: Update lc0_worker pyproject.toml**

  Edit `services/lc0_worker/pyproject.toml`:

  ```toml
  [project]
  name = "wood-league-lc0-runpod"
  version = "0.1.0"
  description = "RunPod Serverless worker for Lc0 analysis"
  readme = "README.md"
  requires-python = ">=3.11"
  dependencies = [
      "wood-league-shared",
      "runpod>=1.6.0",
  ]

  [tool.uv.sources]
  wood-league-shared = { workspace = true }

  [tool.setuptools.packages.find]
  where = ["."]
  include = ["lc0_worker*"]

  [build-system]
  requires = ["setuptools>=68", "wheel"]
  build-backend = "setuptools.build_meta"
  ```

- [ ] **Step 5: Verify no stale imports**

  ```bash
  grep -r "from lc0_worker\.storage\.models\|from lc0_worker\.storage\.database" \
    services/lc0_worker/ --include="*.py"
  ```

  Expected: no output.

- [ ] **Step 6: Commit**

  ```bash
  git add services/lc0_worker/
  git commit -m "refactor(lc0_worker): import shared modules from wood_league_shared"
  ```

---

### Task 14: Update imports in services/dispatchers

The dispatchers package uses `dispatchers.models` and `dispatchers.db` (not `storage/models` and `storage/database`). Path mapping is different from the other services.

**Files:**
- Modify: `services/dispatchers/dispatchers/models.py` (delete — now in shared)
- Modify: `services/dispatchers/dispatchers/db.py` (delete — now in shared)
- Modify: `services/dispatchers/dispatchers/ingest/chesscom_client.py` (delete)
- Modify: `services/dispatchers/dispatchers/ingest/sync_service.py` (delete)

- [ ] **Step 1: Find all files with shared-module imports**

  ```bash
  grep -rl "from dispatchers\.models\|from dispatchers\.db\|from dispatchers\.ingest\.chesscom_client\|from dispatchers\.ingest\.sync_service" \
    services/dispatchers/ --include="*.py"
  ```

- [ ] **Step 2: Update imports**

  ```bash
  find services/dispatchers -name "*.py" -exec sed -i '' \
    -e 's/from dispatchers\.models import/from wood_league_shared.storage.models import/g' \
    -e 's/from dispatchers\.db import/from wood_league_shared.storage.database import/g' \
    -e 's/from dispatchers\.ingest\.chesscom_client import/from wood_league_shared.ingest.chesscom_client import/g' \
    -e 's/from dispatchers\.ingest\.sync_service import/from wood_league_shared.ingest.sync_service import/g' \
    {} \;
  ```

- [ ] **Step 3: Delete the redundant files**

  ```bash
  rm services/dispatchers/dispatchers/models.py
  rm services/dispatchers/dispatchers/db.py
  rm services/dispatchers/dispatchers/ingest/chesscom_client.py
  rm services/dispatchers/dispatchers/ingest/sync_service.py
  ```

- [ ] **Step 4: Update dispatchers pyproject.toml**

  Edit `services/dispatchers/pyproject.toml`:

  ```toml
  [project]
  name = "wood-league-dispatchers"
  version = "0.1.0"
  description = "Unified Railway dispatchers for Stockfish and Lc0 RunPod endpoints"
  readme = "README.md"
  requires-python = ">=3.11"
  dependencies = [
      "wood-league-shared",
      "runpod>=1.7.0",
  ]

  [project.optional-dependencies]
  dev = ["pytest>=8.2.0"]

  [tool.uv.sources]
  wood-league-shared = { workspace = true }

  [tool.setuptools.packages.find]
  where = ["."]
  include = ["dispatchers*"]

  [build-system]
  requires = ["setuptools>=68", "wheel"]
  build-backend = "setuptools.build_meta"
  ```

- [ ] **Step 5: Verify no stale imports**

  ```bash
  grep -r "from dispatchers\.models\|from dispatchers\.db\|from dispatchers\.ingest\.chesscom_client\|from dispatchers\.ingest\.sync_service" \
    services/dispatchers/ --include="*.py"
  ```

  Expected: no output.

- [ ] **Step 6: Commit**

  ```bash
  git add services/dispatchers/
  git commit -m "refactor(dispatchers): import shared modules from wood_league_shared"
  ```

---

### Task 15: Update imports in services/app (opening_book only)

The Django app only shares `opening_book.py`. Leave all other app imports untouched.

**Files:**
- Modify: `services/app/app/services/opening_book.py` (delete — now in shared)
- Modify: any file that imports from `app.services.opening_book`

- [ ] **Step 1: Find callers of opening_book in the app**

  ```bash
  grep -rl "from app\.services\.opening_book\|import opening_book" \
    services/app/ --include="*.py"
  ```

- [ ] **Step 2: Update those imports**

  For each file found, change:
  ```python
  from app.services.opening_book import X
  ```
  to:
  ```python
  from wood_league_shared.services.opening_book import X
  ```

- [ ] **Step 3: Delete the redundant file**

  ```bash
  rm services/app/app/services/opening_book.py
  ```

- [ ] **Step 4: Update app pyproject.toml to add the shared dependency**

  Edit `services/app/pyproject.toml` — add to `dependencies` and add `[tool.uv.sources]`:

  ```toml
  dependencies = [
    "wood-league-shared",
    "django>=5.0",
    # ... rest of existing deps unchanged ...
  ]

  [tool.uv.sources]
  wood-league-shared = { workspace = true }
  ```

- [ ] **Step 5: Run the Django tests to verify nothing broke**

  ```bash
  cd services/app
  python manage.py test
  ```

  Expected: all tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add services/app/
  git commit -m "refactor(app): import opening_book from wood_league_shared"
  git push origin main
  ```

---

## Phase C: Deployment Configuration (Phases 4–5 of spec)

### Task 16: Rewrite services/stockfish_worker/Dockerfile for repo-root build context

**Files:**
- Modify: `services/stockfish_worker/Dockerfile`

- [ ] **Step 1: Replace the Dockerfile**

  Overwrite `services/stockfish_worker/Dockerfile` with:

  ```dockerfile
  # services/stockfish_worker/Dockerfile
  # Build from REPO ROOT: docker build -f services/stockfish_worker/Dockerfile .

  FROM python:3.11-slim

  RUN apt-get update \
      && apt-get install -y --no-install-recommends wget tar \
      && rm -rf /var/lib/apt/lists/*

  RUN wget -q "https://github.com/official-stockfish/Stockfish/releases/download/sf_18/stockfish-ubuntu-x86-64-avx2.tar" \
          -O /tmp/stockfish.tar \
      && tar -xf /tmp/stockfish.tar -C /tmp \
      && find /tmp -name "stockfish*" -type f -perm /111 | head -1 \
           | xargs -I{} mv {} /usr/games/stockfish \
      && chmod +x /usr/games/stockfish \
      && rm -f /tmp/stockfish.tar

  ENV STOCKFISH_PATH=/usr/games/stockfish \
      PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1

  WORKDIR /app

  # Install uv
  RUN pip install --no-cache-dir uv

  # Copy shared package first (better layer caching — changes less often)
  COPY packages/shared ./packages/shared

  # Copy service code
  COPY services/stockfish_worker/pyproject.toml .
  COPY services/stockfish_worker/handler.py .
  COPY services/stockfish_worker/stockfish_pipeline ./stockfish_pipeline

  # Install all deps (uv resolves wood-league-shared from the local packages/shared dir)
  RUN uv pip install --system --no-cache packages/shared && \
      uv pip install --system --no-cache .

  CMD ["python", "handler.py"]
  ```

- [ ] **Step 2: Test the build from the repo root**

  ```bash
  docker build -f services/stockfish_worker/Dockerfile . -t wood-league-stockfish:test
  ```

  Expected: build completes successfully, Stockfish binary installed, Python packages installed.

- [ ] **Step 3: Commit**

  ```bash
  git add services/stockfish_worker/Dockerfile
  git commit -m "chore(stockfish_worker): rewrite Dockerfile for monorepo root build context"
  ```

---

### Task 17: Rewrite services/lc0_worker/Dockerfile for repo-root build context

**Files:**
- Modify: `services/lc0_worker/Dockerfile`

- [ ] **Step 1: Replace the Dockerfile**

  Overwrite `services/lc0_worker/Dockerfile` with (preserving the multi-stage CUDA build, adding shared package copy):

  ```dockerfile
  # services/lc0_worker/Dockerfile
  # Build from REPO ROOT: docker build -f services/lc0_worker/Dockerfile .

  # ── Stage 1: build lc0 from source against CUDA 12.8 ─────────────────────────
  FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04 AS builder

  ENV DEBIAN_FRONTEND=noninteractive

  RUN apt-get update \
      && apt-get install -y --no-install-recommends \
          git meson ninja-build build-essential libopenblas-dev zlib1g-dev \
      && rm -rf /var/lib/apt/lists/*

  RUN git clone --branch v0.32.1 --depth 1 --recurse-submodules \
          https://github.com/LeelaChessZero/lc0.git /tmp/lc0 \
      && cd /tmp/lc0 \
      && ./build.sh -Dcudnn=true -Dgtest=false -Ddefault_backend=cudnn-fp16 \
      && cp build/release/lc0 /usr/local/bin/lc0 \
      && chmod +x /usr/local/bin/lc0 \
      && rm -rf /tmp/lc0

  # ── Stage 2: slim runtime image ───────────────────────────────────────────────
  FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

  ENV PYTHONDONTWRITEBYTECODE=1 \
      PYTHONUNBUFFERED=1 \
      LC0_NETWORK=/usr/local/share/lc0-network.pb.gz \
      LC0_PATH=/usr/local/bin/lc0 \
      VIRTUAL_ENV=/opt/venv \
      PATH=/opt/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      DEBIAN_FRONTEND=noninteractive

  WORKDIR /app

  RUN apt-get update \
      && apt-get install -y --no-install-recommends \
          python3 python3-venv curl libopenblas0 zlib1g \
      && python3 -m venv /opt/venv \
      && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
      && rm -rf /var/lib/apt/lists/*

  COPY --from=builder /usr/local/bin/lc0 /usr/local/bin/lc0

  RUN curl --connect-timeout 10 --max-time 60 -fsSL \
          "https://storage.lczero.org/files/networks-contrib/t1-512x15x8h-distilled-swa-3395000.pb.gz" \
          -o /usr/local/share/lc0-network.pb.gz || true

  # Copy shared package first for layer caching
  COPY packages/shared ./packages/shared

  # Copy service code
  COPY services/lc0_worker/pyproject.toml .
  COPY services/lc0_worker/handler.py .
  COPY services/lc0_worker/lc0_worker ./lc0_worker

  RUN /opt/venv/bin/pip install --no-cache-dir packages/shared && \
      /opt/venv/bin/pip install --no-cache-dir .

  CMD ["python", "handler.py"]
  ```

- [ ] **Step 2: Test the build (requires NVIDIA Docker runtime for GPU; test build only)**

  ```bash
  docker build -f services/lc0_worker/Dockerfile . -t wood-league-lc0:test
  ```

  Expected: build completes (lc0 compile takes several minutes). GPU is only needed at runtime, not build time.

- [ ] **Step 3: Commit**

  ```bash
  git add services/lc0_worker/Dockerfile
  git commit -m "chore(lc0_worker): rewrite Dockerfile for monorepo root build context"
  ```

---

### Task 18: Create the build-runpod.sh script

**Files:**
- Create: `scripts/build-runpod.sh`

- [ ] **Step 1: Create the scripts directory and build script**

  ```bash
  mkdir -p scripts
  ```

  Create `scripts/build-runpod.sh`:

  ```bash
  #!/usr/bin/env bash
  # build-runpod.sh — Build and push a RunPod worker Docker image from the monorepo root.
  #
  # Usage: ./scripts/build-runpod.sh <service> <tag> <registry>
  #   service:  stockfish_worker | lc0_worker
  #   tag:      image tag (e.g. v1.2.3 or latest)
  #   registry: Docker registry prefix (e.g. docker.io/christophersw)
  #
  # Example:
  #   ./scripts/build-runpod.sh stockfish_worker v1.0.0 docker.io/christophersw

  set -euo pipefail

  SERVICE="${1:?Usage: $0 <service> <tag> <registry>}"
  TAG="${2:?Usage: $0 <service> <tag> <registry>}"
  REGISTRY="${3:?Usage: $0 <service> <tag> <registry>}"

  VALID_SERVICES=("stockfish_worker" "lc0_worker")
  if [[ ! " ${VALID_SERVICES[*]} " =~ " ${SERVICE} " ]]; then
      echo "Error: service must be one of: ${VALID_SERVICES[*]}"
      exit 1
  fi

  IMAGE="${REGISTRY}/${SERVICE}:${TAG}"
  DOCKERFILE="services/${SERVICE}/Dockerfile"

  echo "Building ${IMAGE} from repo root using ${DOCKERFILE}..."
  docker build -f "${DOCKERFILE}" -t "${IMAGE}" .

  echo "Pushing ${IMAGE}..."
  docker push "${IMAGE}"

  echo "Done: ${IMAGE}"
  ```

- [ ] **Step 2: Make it executable**

  ```bash
  chmod +x scripts/build-runpod.sh
  ```

- [ ] **Step 3: Test with a dry run**

  ```bash
  # This should print the usage error (no args = expected failure)
  ./scripts/build-runpod.sh 2>&1 | head -3
  ```

  Expected: `Usage: ./scripts/build-runpod.sh <service> <tag> <registry>`

- [ ] **Step 4: Commit**

  ```bash
  git add scripts/build-runpod.sh
  git commit -m "chore: add build-runpod.sh script for building RunPod worker images"
  git push origin main
  ```

---

### Task 19: Update Railway service configurations

This task is partly manual (Railway dashboard) and partly code changes.

**Files:**
- Modify: `services/app/pyproject.toml` (git dep for Railway builds)
- Modify: `services/dispatchers/pyproject.toml` (git dep for Railway builds)

- [ ] **Step 1: Update Railway app service pyproject.toml for git dependency**

  Edit `services/app/pyproject.toml`. Railway's Railpack builder uses pip (not uv), so it can't resolve `{ workspace = true }`. Add a PEP 440 git URL to the dependencies list — pip/Railpack will use this; uv will prefer the `[tool.uv.sources]` workspace entry and ignore the URL. Both entries must be present:

  ```toml
  [project]
  dependencies = [
    # PEP 440 git URL — used by Railway's Railpack (pip) at build time
    "wood-league-shared @ git+https://github.com/christophersw/wood_league.git#subdirectory=packages/shared",
    "django>=5.0",
    # ... rest of existing deps unchanged ...
  ]

  # uv workspace source — takes precedence over the git URL during local uv sync
  [tool.uv.sources]
  wood-league-shared = { workspace = true }
  ```

- [ ] **Step 2: Update Railway dispatchers pyproject.toml similarly**

  Same pattern as Step 1 for `services/dispatchers/pyproject.toml`:

  ```toml
  [project]
  dependencies = [
    "wood-league-shared @ git+https://github.com/christophersw/wood_league.git#subdirectory=packages/shared",
    "runpod>=1.7.0",
  ]

  [tool.uv.sources]
  wood-league-shared = { workspace = true }
  ```

- [ ] **Step 3: Configure Railway dashboard for monorepo (manual)**

  For each Railway service, in the Railway dashboard:

  **App service:**
  - Settings → Source → Root Directory: `services/app`
  - Builder: Railpack (unchanged)
  - Watch Paths: `services/app/**`, `packages/shared/**`

  **Dispatchers service:**
  - Settings → Source → Root Directory: `services/dispatchers`
  - Builder: Dockerfile (unchanged)
  - Watch Paths: `services/dispatchers/**`, `packages/shared/**`

- [ ] **Step 4: Trigger a test deployment of each Railway service**

  Push a small change and verify both Railway services deploy successfully and pass health checks.

  ```bash
  git add services/app/pyproject.toml services/dispatchers/pyproject.toml
  git commit -m "chore: update Railway pyproject.toml files with git dep for wood_league_shared"
  git push origin main
  ```

  In Railway dashboard: monitor deployment logs for both services. Verify health checks pass.

---

## Phase D: Tooling & Cleanup (Phases 6–7 of spec)

### Task 20: Initialize git-issue and write core documentation

**Files:**
- Create: `.issues/` (via git issue init)
- Create: `docs/architecture.md`
- Create: `docs/deployment.md`
- Create: `docs/adr/001-monorepo.md`

- [ ] **Step 1: Initialize git-issue at the monorepo root**

  ```bash
  git issue init
  ```

  Expected: `.issues/` directory created.

- [ ] **Step 2: Copy the issue config from the app service**

  ```bash
  cp services/app/.issues/.config.yml .issues/.config.yml
  ```

- [ ] **Step 3: Create docs/architecture.md**

  Create `docs/architecture.md`:

  ```markdown
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
  ```

- [ ] **Step 4: Create docs/deployment.md**

  Create `docs/deployment.md`:

  ```markdown
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
  ```

- [ ] **Step 5: Create docs/adr/001-monorepo.md**

  ```bash
  mkdir -p docs/adr
  ```

  Create `docs/adr/001-monorepo.md`:

  ```markdown
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
  ```

- [ ] **Step 6: Commit everything**

  ```bash
  git add .issues/ docs/
  git commit -m "docs: add architecture, deployment, ADR, and initialize git-issue"
  git push origin main
  ```

---

### Task 21: Archive the old repos

- [ ] **Step 1: Add a deprecation notice to each old repo's README**

  For each of the four old repos, push a final commit with this README change:

  ```markdown
  # ⚠️ Archived

  This repo has been merged into the Wood League monorepo:
  https://github.com/christophersw/wood_league

  This repo is archived and no longer maintained.
  ```

- [ ] **Step 2: Archive each repo on GitHub**

  For each repo, go to: Settings → Danger Zone → Archive this repository.

  Repos to archive:
  - `https://github.com/christophersw/wood_league_app`
  - `https://github.com/christophersw/wood_league_dispatchers`
  - `https://github.com/christophersw/wood_league_stockfish_runpod`
  - `https://github.com/christophersw/wood_league_lc0_runpod`

---

## Verification Checklist

After all tasks complete, verify:

- [ ] `uv sync` at repo root succeeds with no errors
- [ ] `cd services/app && python manage.py test` — all Django tests pass
- [ ] `docker build -f services/stockfish_worker/Dockerfile . -t test:sf` succeeds
- [ ] `docker build -f services/lc0_worker/Dockerfile . -t test:lc0` succeeds
- [ ] Railway `app` service deploys and health check passes
- [ ] Railway `dispatchers` service deploys and stays running
- [ ] `git issue list` works from the repo root
- [ ] `grep -r "from dispatchers\.models\|from stockfish_pipeline\.storage\.models\|from lc0_worker\.storage\.models" services/ --include="*.py"` → no output
