# Migration Plan — Streamlit → Django + Tailwind CSS + HTMX

**Date:** 2026-05-01  
**Architect Pass:** Phase 0 — No code written yet  
**Source:** `christophersw/wood_league_app` (Streamlit + SQLAlchemy + PostgreSQL)  
**Target:** Django 5.x + Tailwind CSS v4 + HTMX 2.x + PostgreSQL (unchanged schema)

---

## 1. Application Inventory

### App Purpose

Wood League Chess is a private chess club analytics platform. It ingests games from Chess.com, runs them through Stockfish and Lc0 (Leela Chess Zero) engines on RunPod GPU workers, and surfaces:

- Club-wide accuracy trends, ELO trends, and opening flow visualizations
- Per-game move-by-move engine analysis with Du Bois–styled stat cards
- AI-powered and keyword game search with animated board previews
- An opening position explorer with continuation trees and per-player W/D/L stats
- An admin panel for analysis job queue monitoring and club roster management

### Existing Pages → URL Mapping

| Streamlit page | URL path | Auth |
|---|---|---|
| `welcome.py` | `/` | Required |
| `game_analysis.py` | `/games/<slug>/` | Required |
| `game_search.py` | `/search/` | Required |
| `opening_position.py` | `/openings/<int:opening_id>/` | Required |
| `analysis_status.py` | `/admin/analysis-status/` | Admin only |
| `club_members.py` | `/admin/members/` | Admin only |
| Login / Logout | `/auth/login/`, `/auth/logout/` | Public |

### External Integrations

| Integration | Purpose | Notes |
|---|---|---|
| Chess.com REST API | Game ingest | `chesscom_client.py` — polled by `sync_service.py` |
| Anthropic API (claude-3-haiku) | AI game search → SQL | `game_search_service.py` |
| RunPod API | Cloud GPU workers for Stockfish + Lc0 | `analysis_worker.py`, `lc0_analysis_worker.py` |
| Stockfish (local binary) | Engine analysis (fallback / local) | `stockfish_service.py` |
| Lc0 (local binary) | Neural net analysis (fallback / local) | `lc0_service.py` |

---

## 2. Django App Structure

```
woodleague/                  ← Django project root (settings, urls, wsgi)
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── wsgi.py
├── accounts/                ← Auth: custom User, login/logout views, middleware
├── players/                 ← Player roster, admin member management
├── games/                   ← Game records, participants, analysis display views
├── analysis/                ← Engine jobs, Stockfish/Lc0 analysis models + API
├── openings/                ← OpeningBook, opening position views
├── dashboard/               ← Welcome/club dashboard views
├── search/                  ← Game search (AI + keyword), HTMX partials
├── ingest/                  ← chess.com sync, enqueue logic, SystemEvent
├── static/
│   ├── css/                 ← Tailwind build output
│   ├── js/                  ← HTMX, Alpine.js, Plotly.js, chessground
│   └── fonts/               ← Carry over existing woff2 files unchanged
└── templates/
    ├── base.html
    ├── partials/
    └── <app>/
```

### App Responsibilities

**`accounts`**
- Custom `User` model (extends `AbstractBaseUser`) with `email`, `password_hash`, `role`, `is_active`
- Password hashing already uses PBKDF2-SHA256 — compatible with Django's `PBKDF2PasswordHasher`; existing hashes are portable
- HMAC cookie token → replace with Django's session-based auth (`django.contrib.auth`)
- Views: `LoginView`, `LogoutView`
- Middleware: `require_login` enforced at view level via `@login_required` decorator; admin views via `@user_passes_test(lambda u: u.role == 'admin')`

**`players`**
- `Player` model (unchanged schema)
- Views: `MembersListView`, HTMX partials for `add_member`, `edit_member`, `delete_member`, `invite_login`
- Admin guard via decorator

**`games`**
- `Game`, `GameParticipant` models
- Views: `GameAnalysisDetailView` (primary game analysis page), HTMX partial `game_analysis_engine_panel`
- Template renders chess board SVG server-side using `python-chess` (same as current)
- Move-by-move navigation via HTMX + `hx-push-url`

**`analysis`**
- `GameAnalysis`, `MoveAnalysis`, `Lc0GameAnalysis`, `Lc0MoveAnalysis`, `AnalysisJob`, `WorkerHeartbeat`
- Views: `AnalysisStatusView` (admin), HTMX partial `analysis_queue_panel` (auto-polls)
- RunPod health check called as a service function from the view

**`openings`**
- `OpeningBook` model
- Views: `OpeningPositionDetailView`, HTMX partial `opening_stats_panel`
- Opening continuation tree rendered as SVG or JSON → client-side D3/custom JS

**`dashboard`**
- No additional models
- Views: `DashboardView` — renders charts using Plotly.js (data as JSON from view context)
- HTMX partials: `accuracy_chart_partial`, `elo_chart_partial`, `opening_sankey_partial`, `opening_node_stats_partial`

**`search`**
- No additional models (queries `games`, `analysis`)
- Views: `GameSearchView`, HTMX partials: `search_results_partial`, `board_preview_partial`

**`ingest`**
- `SystemEvent` model
- Management commands: `sync_games`, `run_analysis_worker`, `run_lc0_worker` (replacing the standalone scripts)
- `enqueue_analysis` stays as a utility function

---

## 3. Django Model Definitions

Models map 1:1 from SQLAlchemy. Key Django-specific notes:

```python
# accounts/models.py
class User(AbstractBaseUser):
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=32, default="member")  # "admin" | "member"
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    USERNAME_FIELD = "email"
    # password field provided by AbstractBaseUser (PBKDF2 by default)

# players/models.py
class Player(models.Model):
    username = models.CharField(max_length=80, unique=True, db_index=True)
    display_name = models.CharField(max_length=120)
    name = models.CharField(max_length=120, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True, unique=True, db_index=True)

# games/models.py
class Game(models.Model):
    id = models.CharField(max_length=64, primary_key=True)  # chess.com game ID (keep string PK)
    slug = models.SlugField(max_length=80, null=True, blank=True, unique=True, db_index=True)
    played_at = models.DateTimeField(db_index=True)
    time_control = models.CharField(max_length=32)
    white_username = models.CharField(max_length=120, null=True, blank=True)
    black_username = models.CharField(max_length=120, null=True, blank=True)
    white_rating = models.IntegerField(null=True, blank=True)
    black_rating = models.IntegerField(null=True, blank=True)
    result_pgn = models.CharField(max_length=16, null=True, blank=True)
    winner_username = models.CharField(max_length=120, null=True, blank=True)
    eco_code = models.CharField(max_length=8, default="")
    opening_name = models.CharField(max_length=120, default="")
    lichess_opening = models.CharField(max_length=200, null=True, blank=True)
    pgn = models.TextField(default="")

class GameParticipant(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="participants")
    player = models.ForeignKey("players.Player", on_delete=models.CASCADE)
    color = models.CharField(max_length=8)
    opponent_username = models.CharField(max_length=120)
    player_rating = models.IntegerField(null=True, blank=True)
    opponent_rating = models.IntegerField(null=True, blank=True)
    result = models.CharField(max_length=32)
    quality_score = models.FloatField(null=True, blank=True)
    blunder_count = models.IntegerField(null=True, blank=True)
    mistake_count = models.IntegerField(null=True, blank=True)
    inaccuracy_count = models.IntegerField(null=True, blank=True)
    acpl = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = [("game", "player")]
        indexes = [models.Index(fields=["game"]), models.Index(fields=["player"])]

# analysis/models.py
class GameAnalysis(models.Model):
    game = models.OneToOneField(Game, on_delete=models.CASCADE, related_name="analysis")
    analyzed_at = models.DateTimeField(null=True, blank=True)
    engine_depth = models.IntegerField(null=True, blank=True)
    summary_cp = models.FloatField(default=0.0)
    white_accuracy = models.FloatField(null=True, blank=True)
    black_accuracy = models.FloatField(null=True, blank=True)
    white_acpl = models.FloatField(null=True, blank=True)
    black_acpl = models.FloatField(null=True, blank=True)
    white_blunders = models.IntegerField(null=True, blank=True)
    white_mistakes = models.IntegerField(null=True, blank=True)
    white_inaccuracies = models.IntegerField(null=True, blank=True)
    black_blunders = models.IntegerField(null=True, blank=True)
    black_mistakes = models.IntegerField(null=True, blank=True)
    black_inaccuracies = models.IntegerField(null=True, blank=True)

class MoveAnalysis(models.Model):
    analysis = models.ForeignKey(GameAnalysis, on_delete=models.CASCADE, related_name="moves")
    ply = models.IntegerField()
    san = models.CharField(max_length=32)
    fen = models.TextField()
    cp_eval = models.FloatField()
    cpl = models.FloatField(null=True, blank=True)
    best_move = models.CharField(max_length=32, default="")
    arrow_uci = models.CharField(max_length=8, default="")
    arrow_uci_2 = models.CharField(max_length=8, null=True, blank=True)
    arrow_uci_3 = models.CharField(max_length=8, null=True, blank=True)
    arrow_score_1 = models.FloatField(null=True, blank=True)
    arrow_score_2 = models.FloatField(null=True, blank=True)
    arrow_score_3 = models.FloatField(null=True, blank=True)
    classification = models.CharField(max_length=16, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["analysis"])]

class Lc0GameAnalysis(models.Model):
    game = models.OneToOneField(Game, on_delete=models.CASCADE, related_name="lc0_analysis")
    analyzed_at = models.DateTimeField(null=True, blank=True)
    engine_nodes = models.IntegerField(null=True, blank=True)
    network_name = models.CharField(max_length=120, null=True, blank=True)
    white_win_prob = models.FloatField(null=True, blank=True)
    white_draw_prob = models.FloatField(null=True, blank=True)
    white_loss_prob = models.FloatField(null=True, blank=True)
    black_win_prob = models.FloatField(null=True, blank=True)
    black_draw_prob = models.FloatField(null=True, blank=True)
    black_loss_prob = models.FloatField(null=True, blank=True)
    white_blunders = models.IntegerField(null=True, blank=True)
    white_mistakes = models.IntegerField(null=True, blank=True)
    white_inaccuracies = models.IntegerField(null=True, blank=True)
    black_blunders = models.IntegerField(null=True, blank=True)
    black_mistakes = models.IntegerField(null=True, blank=True)
    black_inaccuracies = models.IntegerField(null=True, blank=True)

class Lc0MoveAnalysis(models.Model):
    analysis = models.ForeignKey(Lc0GameAnalysis, on_delete=models.CASCADE, related_name="moves")
    ply = models.IntegerField()
    san = models.CharField(max_length=32)
    fen = models.TextField()
    wdl_win = models.IntegerField(null=True, blank=True)
    wdl_draw = models.IntegerField(null=True, blank=True)
    wdl_loss = models.IntegerField(null=True, blank=True)
    cp_equiv = models.FloatField(null=True, blank=True)
    best_move = models.CharField(max_length=32, default="")
    arrow_uci = models.CharField(max_length=8, default="")
    arrow_uci_2 = models.CharField(max_length=8, null=True, blank=True)
    arrow_uci_3 = models.CharField(max_length=8, null=True, blank=True)
    arrow_score_1 = models.FloatField(null=True, blank=True)
    arrow_score_2 = models.FloatField(null=True, blank=True)
    arrow_score_3 = models.FloatField(null=True, blank=True)
    move_win_delta = models.FloatField(null=True, blank=True)
    classification = models.CharField(max_length=16, null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["analysis"])]

class AnalysisJob(models.Model):
    STATUS_CHOICES = [("pending","pending"),("submitted","submitted"),
                      ("running","running"),("completed","completed"),("failed","failed")]
    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="analysis_jobs")
    status = models.CharField(max_length=16, default="pending", choices=STATUS_CHOICES, db_index=True)
    priority = models.IntegerField(default=0)
    engine = models.CharField(max_length=16, default="stockfish", db_index=True)
    depth = models.IntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=64, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    duration_seconds = models.FloatField(null=True, blank=True)
    runpod_job_id = models.CharField(max_length=64, null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

class WorkerHeartbeat(models.Model):
    worker_id = models.CharField(max_length=64, primary_key=True)
    last_seen = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=16, default="idle")
    current_game_id = models.CharField(max_length=64, null=True, blank=True)
    jobs_completed = models.IntegerField(default=0)
    jobs_failed = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    cpu_model = models.CharField(max_length=256, null=True, blank=True)
    cpu_cores = models.IntegerField(null=True, blank=True)
    memory_mb = models.IntegerField(null=True, blank=True)
    stockfish_binary = models.CharField(max_length=512, null=True, blank=True)

# openings/models.py
class OpeningBook(models.Model):
    eco = models.CharField(max_length=8, db_index=True)
    name = models.CharField(max_length=200, db_index=True)
    pgn = models.TextField()
    epd = models.CharField(max_length=100, unique=True, db_index=True)

# ingest/models.py
class SystemEvent(models.Model):
    event_type = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    details = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
```

---

## 4. URL Routing Plan

```python
# config/urls.py
urlpatterns = [
    path("",            include("dashboard.urls")),
    path("games/",      include("games.urls")),
    path("search/",     include("search.urls")),
    path("openings/",   include("openings.urls")),
    path("auth/",       include("accounts.urls")),
    path("admin/",      include("players.urls")),   # club admin area
    path("admin/",      include("analysis.urls")),  # analysis status
]
```

### Full URL Table

| URL | View | Method | Description |
|---|---|---|---|
| `/` | `DashboardView` | GET | Club dashboard |
| `/_partials/dashboard/accuracy/` | `AccuracyChartPartialView` | GET | HTMX: accuracy chart |
| `/_partials/dashboard/elo/` | `EloChartPartialView` | GET | HTMX: ELO chart |
| `/_partials/dashboard/sankey/` | `OpeningSankeyPartialView` | GET | HTMX: opening Sankey |
| `/_partials/dashboard/opening-stats/` | `OpeningNodeStatsPartialView` | GET | HTMX: clicked node stats |
| `/games/<slug>/` | `GameAnalysisDetailView` | GET | Game analysis page |
| `/_partials/games/<slug>/board/<int:ply>/` | `BoardAtPlyPartialView` | GET | HTMX: board SVG at ply |
| `/search/` | `GameSearchView` | GET | Search page |
| `/_partials/search/results/` | `SearchResultsPartialView` | GET/POST | HTMX: results table |
| `/_partials/search/preview/<game_id>/` | `BoardPreviewPartialView` | GET | HTMX: board animation |
| `/openings/<int:opening_id>/` | `OpeningPositionDetailView` | GET | Opening detail page |
| `/_partials/openings/<int:opening_id>/stats/` | `OpeningStatsPartialView` | GET | HTMX: filtered stats |
| `/admin/members/` | `MembersListView` | GET | Club members page |
| `/admin/members/add/` | `AddMemberView` | POST | HTMX form submission |
| `/admin/members/<int:pk>/edit/` | `EditMemberView` | POST | HTMX inline edit |
| `/admin/members/<int:pk>/delete/` | `DeleteMemberView` | DELETE | HTMX delete |
| `/admin/members/<int:pk>/invite/` | `InviteMemberView` | POST | HTMX create login |
| `/admin/analysis-status/` | `AnalysisStatusView` | GET | Job queue dashboard |
| `/_partials/analysis/queue/` | `QueueStatusPartialView` | GET | HTMX: auto-refresh queue |
| `/auth/login/` | `LoginView` | GET/POST | Login form |
| `/auth/logout/` | `LogoutView` | POST | Logout |

---

## 5. HTMX Interaction Points

### Full Page Loads (standard Django views)
- Navigate to any primary page (dashboard, game analysis, search, opening detail, admin pages)
- Login / logout

### HTMX Partial Updates

| Trigger | Target | HTMX Attributes | Notes |
|---|---|---|---|
| Dashboard timeframe/player filter change | `#dashboard-charts` | `hx-get="/_partials/dashboard/accuracy/" hx-trigger="change delay:300ms"` | Filter params in query string; replaces chart container |
| Dashboard Sankey node click | `#opening-node-stats` | `hx-post="/_partials/dashboard/opening-stats/" hx-trigger="click"` | Node label posted; stats panel revealed below chart |
| Game analysis ply navigation (prev/next) | `#board-container` | `hx-get="/_partials/games/<slug>/board/<ply>/"` | Returns SVG + eval bar + move classification badge |
| Game search form submit | `#search-results` | `hx-post="/_partials/search/results/" hx-indicator="#search-spinner"` | Returns results table partial |
| Search result row click | `#board-preview` | `hx-get="/_partials/search/preview/<id>/"` | Returns animated board HTML (iframe or inline JS) |
| Analysis status queue panel | `#queue-panel` | `hx-get="/_partials/analysis/queue/" hx-trigger="every 30s"` | Auto-polls; returns updated queue metrics |
| Add/edit/delete member | `#members-table` | `hx-post`, `hx-swap="outerHTML"` | Form submissions replace table row or full table |
| Invite member popover form | `#invite-result-<pk>` | `hx-post` | Returns success/error message in popover |
| Opening filter change | `#opening-stats-panel` | `hx-get="/_partials/openings/<id>/stats/"` | Timeframe + player filter; replaces charts + game table |

---

## 6. Tailwind Component Plan

### Base Layout
- `templates/base.html` — sidebar navigation (forest green, Du Bois palette), font @font-face declarations, HTMX + Plotly.js + htmx-ext-response-targets script includes
- `templates/partials/sidebar_nav.html` — nav links with active state, admin section conditional

### Reusable Partials

| Partial | Used By | Description |
|---|---|---|
| `partials/game_table.html` | Dashboard, Opening detail | Ranked game list with accuracy/ACPL columns and "Open" link |
| `partials/analysis_stat_card.html` | Game analysis | Du Bois stat card (blunder/mistake/inaccuracy/accuracy count) |
| `partials/dub_bar_row.html` | Game analysis, Opening detail | Du Bois horizontal bar row (player label + bar + value) |
| `partials/wdl_stack.html` | Game analysis, Opening detail | W/D/L stacked bar |
| `partials/move_quality_stack.html` | Game analysis | Move classification stacked bar (brilliant/best/great/neut/inac/mistake/blunder) |
| `partials/board_svg.html` | Game analysis, Opening detail | `python-chess` SVG board with optional arrow overlays |
| `partials/opening_node_stats.html` | Dashboard, Opening detail | Node stats: games, W/D/L metrics, player breakdown table |
| `partials/member_row.html` | Club members | Player row with login status badge and invite popover |
| `partials/queue_metrics.html` | Analysis status | Per-engine queue counters, RunPod health badges |
| `partials/spinner.html` | Search, AI search | HTMX loading indicator |

### Tailwind CSS Notes
- Define Du Bois colour tokens in `tailwind.config.js` as custom colours (`parchment`, `ebony`, `forest`, `moss`, `whisky`, `peat`, etc.) matching the existing CSS variables
- DM Mono / EB Garamond / Playfair Display SC / Cormorant Garamond font families configured as Tailwind font stacks
- All existing analysis stat card and Du Bois bar CSS can map to Tailwind utility classes — no bespoke CSS needed for layout
- Use `@layer components` for `.dub-bar`, `.analysis-stat-card` and `.wc-table` if utility classes become verbose

---

## 7. Data Migration Risks

### Risk: Existing Schema Preserved — No Column Renames
The PostgreSQL schema must remain **identical** to the Alembic-managed schema. Django migrations will not create or alter tables on first run — we will use `managed = False` or `inspectdb`-style migration with `--fake-initial` to tell Django the tables already exist. This is the most critical migration risk.

**Resolution:** Generate migrations with `manage.py migrate --fake-initial` on first deploy. The `db_table` Meta attribute must exactly match the Alembic table names: `players`, `users`, `games`, `game_participants`, `game_analysis`, `move_analysis`, `lc0_game_analysis`, `lc0_move_analysis`, `opening_book`, `analysis_jobs`, `worker_heartbeats`, `system_events`.

### Risk: String Primary Key on `games`
The `games.id` is a chess.com game ID string (e.g. `"123456789"`). Django's default is an integer PK. Using `CharField(primary_key=True)` is valid Django but breaks `django.contrib.admin` assumptions and may cause friction with `get_object_or_404`. Use `slug` as the URL identifier everywhere to minimize exposure of the raw chess.com game ID.

### Risk: Auth Model Migration
The existing `users` table stores `password_hash` in the format `pbkdf2_sha256$260000$<salt>$<digest>` using URL-safe base64. Django's PBKDF2 hasher uses standard base64. **These are not bit-compatible.** All users will need to reset their passwords on first login, or a custom password hasher must wrap the existing scheme.

**Resolution:** Write a `LegacyWoodLeaguePbkdf2Hasher` that decodes URL-safe base64, wraps the existing verification logic, and marks itself as needing an upgrade (so Django re-hashes on next successful login). This is a one-migration-cycle concern.

### Risk: No Django `auth_user` Table
The existing schema has a `users` table, not Django's `auth_user`. The custom `User` model must set `db_table = "users"` and `app_label = "accounts"` with `AUTH_USER_MODEL = "accounts.User"` in settings. The `AUTH_PASSWORD_VALIDATORS` can stay default (new passwords will be properly hashed by Django).

### Risk: Plotly Charts
Currently `st.plotly_chart()` serializes and renders figures server-side. In Django the figure data (accuracy timeseries, ELO trends, opening Sankey) must be serialized to JSON in the view and passed to the template for client-side Plotly.js rendering. This is straightforward but all chart-building code in `charts.py` must be audited — the functions that return `go.Figure` objects can be reused directly; `fig.to_json()` outputs the required JSON string.

### Risk: Chess Board Animation in Search Results
`_board_animation_html()` in `game_search.py` generates a massive inline HTML string containing a JSON array of SVG board frames — one per ply. For a 60-move game this is ~200–400KB of HTML per search result. In Django this becomes a `/_partials/search/preview/<id>/` endpoint that generates the same structure on demand. Consider lazy-loading the animation only when a row is selected (HTMX already handles this).

### Risk: Opening Continuation Tree (SVG canvas)
`opening_position.py` renders an interactive SVG tree using `_components.html()` (a Streamlit iframe escape hatch) with `window.parent.postMessage()` for navigation. In Django, replace with a proper `<div>` + D3.js tree or a simple server-rendered `<svg>` with `hx-get` links on each node. The Python tree-building logic (`_opening_tree_html`) can be refactored into a view that returns the SVG or JSON for D3.

### Risk: Ingest / Worker Scripts
`sync_service.py`, `analysis_worker.py`, and `lc0_analysis_worker.py` are currently standalone scripts (run via Railway cron or RunPod entry points). In Django, convert to `management commands` (`manage.py sync_games`, `manage.py run_worker`, etc.) so they share the Django ORM setup and settings. The RunPod dispatchers (`wood_league_dispatchers`) remain independent.

### Risk: Timezone Handling
The dashboard uses `st.context.timezone` to detect the client's timezone for "last checked" display. Django has no equivalent server-side browser TZ access. Resolve with a small piece of JavaScript that reads `Intl.DateTimeFormat().resolvedOptions().timeZone` and posts it to a session cookie on page load, then read the cookie in the Django view.

### Risk: `AUTH_ENABLED` Feature Flag
Currently all auth is toggled by `auth_enabled = False` in settings, which hides the login page entirely. In Django, replicate with a settings flag checked in `LoginRequiredMiddleware` — if disabled, middleware passes all requests through without authentication.

---

## 8. Phase Breakdown (Post-Architecture)

| Phase | Scope | Model |
|---|---|---|
| 1 | Project scaffolding, settings, Tailwind/HTMX wiring, base templates, font setup | 🔵 Haiku |
| 2 | Django model definitions + `--fake-initial` migrations, custom auth backend | 🟡 Sonnet |
| 3 | Accounts app: login/logout views, session auth, legacy password hasher | 🟡 Sonnet |
| 4 | Dashboard app: DashboardView + HTMX chart partials (Plotly.js JSON) | 🟡 Sonnet |
| 5 | Games app: GameAnalysisDetailView, ply navigation HTMX, Du Bois stat cards | 🟡 Sonnet |
| 6 | Search app: GameSearchView, AI search, keyword search, board preview partial | 🟡 Sonnet |
| 7 | Openings app: OpeningPositionDetailView, continuation tree (D3 or SVG) | 🟡 Sonnet |
| 8 | Players app: MembersListView, add/edit/delete/invite HTMX forms | 🟡 Sonnet |
| 9 | Analysis app: AnalysisStatusView, queue auto-poll partial, RunPod health check | 🟡 Sonnet |
| 10 | Ingest management commands, Railway/Railway.toml wiring | 🔵 Haiku |
| 11 | End-to-end QA, security review, production settings | 🔴 Opus |

---

*This document is the sole output of Phase 0. No Django code has been written.*
