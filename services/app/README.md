# Wood League Chess (`wood_league_app`)

Django web app for Wood League Chess: dashboard, games, openings, search, and admin views over club data and engine analysis results.

## Scope of this repo

This repository is the UI/API application layer.

- Serves the web experience and admin tools
- Stores and displays Stockfish/Lc0 analysis results
- Exposes the worker-facing Analysis Worker API (`/api/v1/*`)

Ingest orchestration and remote worker runtime are handled in sibling repos.

## Related repositories

| Repo | Purpose |
|---|---|
| [`wood_league_app`](.) | Django app (this repo) |
| [`wood_league_dispatchers`](https://github.com/christophersw/wood_league_dispatchers) | Ingest + queue dispatch orchestration |
| [`wood_league_stockfish_runpod`](https://github.com/christophersw/wood_league_stockfish_runpod) | Stockfish remote worker |
| [`wood_league_lc0_runpod`](https://github.com/christophersw/wood_league_lc0_runpod) | Lc0 remote worker |

## Documentation

- [Analysis Worker API](documentation/worker-api.md)
- [Analysis Math and Classification](documentation/analysis-math.md)
- [Database ERD](docs/database-erd.md)
- [ERD source](docs/erd.mmd)

## App routes

| Area | URL |
|---|---|
| Dashboard | `/` |
| Games | `/games/` |
| Openings | `/openings/<id>/` |
| Search | `/search/` |
| Login / Logout | `/auth/login/`, `/auth/logout/` |
| Analysis status (admin) | `/admin/analysis-status/` |
| Club members (admin) | `/admin/members/` |
| Worker API key admin | `/admin/api-keys/` |
| Worker API base | `/api/v1/` |
| Django admin | `/django-admin/` |

HTMX partials are under `/_partials/`.

## Django app structure

| App | Purpose |
|---|---|
| `accounts` | User model, auth, login middleware |
| `dashboard` | Dashboard metrics and views |
| `games` | Game list/detail and analysis presentation |
| `analysis` | Analysis queue/status models and views |
| `openings` | Opening explorer and continuation stats |
| `players` | Club member management |
| `search` | Keyword and AI-assisted game search |
| `api` | Worker API and API key admin |
| `ingest` | Legacy/compat ingest integration layer |

## Local setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Key environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes (prod) | dev key | Django secret key |
| `DEBUG` | No | `True` | Debug mode |
| `ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Comma-separated hosts |
| `DATABASE_URL` | No | local Postgres settings | DB connection string |
| `CSRF_TRUSTED_ORIGINS` | No | empty | Comma-separated trusted origins |
| `AUTH_ENABLED` | No | `True` | Toggle session auth middleware |
| `ANTHROPIC_API_KEY` | No | empty | Enables AI search features |
| `ANTHROPIC_MODEL` | No | `claude-haiku-4-5-20251001` | AI model for search |
| `DEFAULT_HISTORY_DAYS` | No | `90` | Default dashboard/query range |
| `STALE_JOB_TIMEOUT_MINUTES` | No | `15` | Worker API stale-running recovery window |
| `MAX_JOB_RETRIES` | No | `3` | Worker API retry ceiling |

## Worker API quick reference

The complete endpoint docs (including full request/response examples) are in:

- [documentation/worker-api.md](documentation/worker-api.md)

Summary:

- `GET /api/v1/health/` (public)
- `POST /api/v1/jobs/checkout/`
- `POST /api/v1/jobs/{job_id}/complete/`
- `POST /api/v1/jobs/{job_id}/fail/`
- `GET /api/v1/jobs/status/`
- `POST /api/v1/heartbeat/`

Protected endpoints require:

```http
X-Api-Key: <raw-key>
```

## Security scanning

- For edited Python files: `bandit -ll <file.py>`
- Full scan script: `./security-scan.sh`

## Deployment (Railway)

Railway deploy uses `railway.toml` and starts Gunicorn after migrations.

At minimum configure production env vars:

- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS`
- database connection settings (`DATABASE_URL` or DB_* values)
