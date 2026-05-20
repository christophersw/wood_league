# Search Page Rework — Design

**Issue:** [#162](https://github.com/christophersw/wood_league/issues/162)
**Date:** 2026-05-20
**Status:** Spec — awaiting review

## Goal

Rework `/search/` so it reads like "find club games" rather than "run validated SQL against the database", give the results table the columns and shape a chess-club member expects, and replace the side-panel board preview with a reusable modal card that surfaces opening identity and per-side engine accuracy.

Out of scope: changing search semantics beyond the AI prompt edits, redesigning the keyword search backend, the opening detail page itself, the analysis page.

## Scope summary

| Area | Change |
|---|---|
| Page copy | Headline → "Find club games"; remove "validated SQL" tagline; new humanised example |
| Debug exposure | `Show SQL` and `Reasoning` hidden unless `DEBUG=True`; `Reasoning` collapsed by default |
| AI prompt | Teach it: "I/me/my/mine" → current user; "people in the club" / "club games" → club-member filter; names map to `players` table |
| Game ingest | New `Game.opening` FK → `OpeningBook`; backfill mgmt command |
| Results table | New columns: title (with trophy), time control (human), date, opening notation (≤10 ply), move count |
| Game preview | Side panel → modal, opened on row click via HTMX, with new card layout |
| Modal pattern | New reusable Tailwind+HTMX modal component (`wc-modal`) shipped via frontend-design skill |

## Architecture

```
┌─────────────────────┐         ┌──────────────────────┐
│ search/index.html   │  HTMX   │ search/views.py      │
│  • AI form          │ ──────► │  search_index        │
│  • keyword form     │         │  ai_search_partial   │
│  • <div id=results> │         │  keyword_search_part │
│  • <dialog id=modal>│         │  game_modal_partial  │ ← new
└─────────────────────┘         └──────────┬───────────┘
            ▲                              │
            │ row click → hx-get           ▼
            │                   ┌──────────────────────┐
            │                   │ search/services.py   │
            └───── modal html ──┤  generate_search_plan│
                                │   (prompt rev)       │
                                │  keyword_game_search │
                                │   (extra fields)     │
                                └──────────────────────┘

┌──────────────────────┐
│ games/services.py    │  new: format_time_control()
│ games/openings.py    │  new: resolve_opening_id(pgn) — used at ingest
│ games/templatetags/  │  new tags: time_control_human,
│   game_format.py     │           opening_notation,
│                      │           accuracy_band_class
└──────────────────────┘
```

## Components & Data Flow

### 1. AI prompt revision (`search/services.py`)

`_schema_context()` and `_player_directory_context()` get three new directives, layered into the cached system prompt (preserves cache hit):

- **Self-reference rule:** "When the request uses `I`, `me`, `my`, `my games`, `mine`, `myself`, treat the player as the user identified by `{current_user_username}`. Generate filters against `games.white_username`, `games.black_username`, or `games.winner_username`."
- **Name mapping rule:** The player directory section (already passed) is reframed: "The known club players below are the only valid mappings for player names. Real names, first names, possessive forms, display names all resolve to a `username` in this list. If a request mentions a name not in the list, return a `reasoning` field explaining and an empty result set (no SQL)."
- **Club vocabulary rule:** "`people in the club`, `part of the club`, `club member`, `club players` ⇒ filter where the username is in the directory above. `club games` ⇒ filter where both `white_username` AND `black_username` are in the directory."

`generate_search_plan` gains a `current_user_username: str | None` parameter. The view resolves the current Player via `Player.objects.get(email=request.user.email)` (returning `None` on miss) and passes it. The system prompt **omits** the self-reference rule when no current user is known, so unauthenticated calls degrade cleanly.

Cache impact: `current_user_username` rides in the per-call user message (not the cached system block), so prompt cache still hits across users.

### 2. Game ingest — `opening_id` denormalisation

**Migration:** add `Game.opening = models.ForeignKey("openings.OpeningBook", null=True, blank=True, on_delete=models.SET_NULL, related_name="games")`.

**Resolution at ingest:** new helper `games.openings.resolve_opening_id(pgn_text) -> int | None` walks the PGN through `openings.services.lookup_opening_entry` ply-by-ply, retaining the deepest hit. Called from wherever Game rows are persisted from PGN (Chess.com importer). For the modal we then just do `game.opening` — no per-row PGN walk.

**Backfill:** management command `python manage.py backfill_opening_ids [--batch=500] [--dry-run]` iterates `Game.objects.filter(opening__isnull=True)` and writes the resolved FK. Logs counts: resolved / unresolved / errors.

Unresolved games (no match in the book) keep `opening = NULL`; the template falls back to `lichess_opening or opening_name` as a non-linked label.

### 3. Results table redesign

Renders from `_normalise(rows)` (AI path) and `keyword_game_search` (keyword path). Both gain identical fields per row:

```
{game_id, slug, played_at, white_username, white_rating,
 black_username, black_rating, winner_username, result_pgn,
 opening_id, opening_name, opening_notation, time_control_human,
 move_count,
 sf_white_acc, sf_black_acc, lc0_white_acc, lc0_black_acc}
```

Columns (left to right):

| # | Header | Cell |
|---|---|---|
| 1 | Game | `bob (1125) v. alice (900) 🏆` (trophy next to winner side) |
| 2 | Time | `15+10 min` / `1 day per move` / `3 min` |
| 3 | Date | `13 May 2026` |
| 4 | Opening | mono-font notation: `1. e4 e5 2. Nf3 Nc6 3. Bb5 a6` (truncated to ≤10 plies, "…" suffix if longer) |
| 5 | Moves | integer; `_normalise` derives from `ceil(plies/2)` when present, else parses PGN |

Row click → HTMX `hx-get="{% url 'search_game_modal_partial' row.game_id %}" hx-target="#search-modal-root" hx-swap="innerHTML"` and opens the modal (no per-row "Open" button — the modal has the analysis link).

The right-hand "Board Preview" column is removed.

### 4. Modal — game preview card

**Reusable component:** `templates/components/_modal.html` — a tailwind shell with backdrop, panel, close button, and an empty content slot. Opens via the `wc-modal-open` data attribute; closes on backdrop click, Esc keydown, or `.wc-modal-close` click. Implemented with a tiny vanilla-JS controller (≈25 lines) wired in `base.html`; no Alpine dependency. The HTMX swap injects content into `#search-modal-root` and the controller observes mutations to auto-open.

**Frontend-design pass:** the modal shell is created via the `frontend-design` skill during implementation so visual treatment is consistent with the rest of the app (parchment/peat/forest palette, serif headlines, mono metadata).

**Modal card layout** (`templates/search/partials/game_modal.html`):

```
┌──────────────────────────────────────────────┐
│ ✕                                            │
│  bob (1125)  v.  alice (900) 🏆              │ ← page-hero-style headline
│                                              │
│  King's Pawn Game: Leonardis Variation       │ ← link to opening detail
│                                              │
│  13 May 2026  ·  15+10 min                   │ ← mono meta line
│                                              │
│  [Chris  SF 87%  Lc0 78%]                    │ ← only club-member chips
│                                              │
│  [ OPEN ANALYSIS → ]                         │
│                                              │
│  ┌──────────────┐                            │
│  │              │                            │
│  │ animated SVG │ (existing _board_animation │
│  │              │  _html, unchanged)         │
│  │              │                            │
│  └──────────────┘                            │
└──────────────────────────────────────────────┘
```

**Accuracy chips** — one chip per club-member side. Each chip shows: `{Player.display_name}: SF {n}% · Lc0 {n}%`. If only one engine has analysed the game, the missing half is omitted (no "—"). If a side isn't a club member, no chip. Background colour bands via `accuracy_band_class` template tag using existing palette tokens:

| Accuracy | Class | Token |
|---|---|---|
| ≥ 90 | `bg-forest text-parchment` | forest = strong green |
| 80–89 | `bg-moss text-parchment` | moss = mid green (existing palette) |
| 70–79 | `bg-honey text-ebony` | honey = warm amber |
| 60–69 | `bg-rust text-parchment` | rust = orange |
| < 60 | `bg-clay text-parchment` | clay = brick red |

Band is computed from the **average of the engines reported for that side** (so the chip background reflects the single number a reader takes away). All band tokens already exist in `tailwind.config.js` palette per `feedback_table_styles.md` — no new colours.

### 5. Debug-only SQL / reasoning

In `results.html`:

- `{% if debug %}` wraps the `Show SQL` `<details>` and Reasoning paragraph.
- `Reasoning` becomes a collapsed `<details><summary>` even in debug.
- View passes `"debug": settings.DEBUG` into the partial context.

## Time-control humanisation

`games/services.py::format_time_control(base_s, increment_s, time_class) -> str`:

```
base=None, inc=None → time_control raw string fallback
base >= 86400, inc == 0 → "{base//86400} day per move" / "{n} days per move"
base >= 60, inc == 0 → "{base//60} min"
base >= 60, inc > 0 → "{base//60}+{inc} min"
base < 60 → "{base}+{inc} sec"
```

Exposed as `{{ game|time_control_human }}` template filter.

## Opening notation truncation

`games/services.py::opening_notation(pgn_text, max_plies=10) -> str`:

Parses with `chess.pgn.read_game`, iterates mainline, formats `1. e4 e5 2. Nf3 Nc6 …`, stops at `max_plies`, appends `…` if the game has more plies. Pure function; tested with parametrised cases (empty PGN, 3-ply, 10-ply, 30-ply).

## Authentication & user resolution

Add `accounts/services.py::resolve_current_player(user) -> Player | None`: looks up by email. The search view calls this once per request; if it returns `None`, the AI prompt drops the self-reference clause and the modal hides chips for the "you" rendering case (chips for other club members are unaffected).

Anonymous access to `/search/` keeps working — accounts middleware already gates `_PUBLIC_PATHS`; `/search/` is private today and stays that way.

## Error handling

- **No `opening_id` resolved** (ingest fail or unresolved old game): opening cell renders plain text, modal opening line is plain text without link.
- **Game missing analysis**: chips section shows the players' names with `"unrated"` italic text or omitted accuracy values; no chip at all if neither engine has data.
- **No PGN**: existing "No PGN available" message in animated-board area, modal still opens.
- **AI prompt over-fits "I"**: when `current_user_username` is `None`, the prompt suppresses the rule; if a user types "show me my games" while anonymous, the model returns a `reasoning` explaining the requirement, no SQL.

## Testing

`games/tests/test_format.py`:
- `format_time_control` cases: 86400/0, 172800/0, 900/10, 180/0, 60/2, None.
- `opening_notation` cases: empty, 3-ply, exactly 10-ply, longer.
- `resolve_opening_id` against a fixture PGN with known book hit and a junk PGN.

`search/tests/test_views.py`:
- `search_index` renders new copy, no "validated SQL" phrase.
- `ai_search_partial` includes `current_user_username` in the prompt when logged in, omits it when anonymous (assert via mock on `generate_search_plan`).
- `game_modal_partial` returns 200, contains player titles and modal markup, links to analysis page when slug exists.
- `results.html` hides `Show SQL` when `debug=False`, shows when `True`.

`search/tests/test_services_prompt.py`:
- New rules render into the assembled system prompt strings (string-match for "club games" and "I/me/my").

`accounts/tests/test_services.py`:
- `resolve_current_player` by email match + null on miss.

All tests live under each app's `tests/test_<mod>.py` per the gate (`games_tests_shadowed` rule).

## Migration & rollout order

1. Add `Game.opening` FK + migration, `resolve_opening_id`, backfill command. Ship + run backfill in prod.
2. Add `format_time_control`, `opening_notation`, template tags, accuracy-band tag, `resolve_current_player`.
3. Modal pattern via `frontend-design` skill → `_modal.html` + JS controller, wired into `base.html`.
4. Search view + templates rework + new partial.
5. AI prompt update + plumb `current_user_username`.
6. Tests, then wiki docs on the Search page.

Steps 1, 2, 3 are independent and can be parallelised by Haiku subagents; 4–5 are sequential and Sonnet-grade work; tests/wiki are Haiku.

## Model routing (per global standard)

| Step | Model |
|---|---|
| 1 migration + backfill mgmt command | Sonnet (writing DB code + walking PGN logic) |
| 2 formatters + template tags + tests | Haiku |
| 3 modal component via frontend-design | Sonnet (frontend-design is a Sonnet-grade skill) |
| 4 search view + template integration | Sonnet |
| 5 AI prompt update | Sonnet (prompt design) |
| 6 wiki docs | Haiku |

## Wiki

After merge, update the GitHub wiki Search page with the new copy, screenshots, AI prompt vocabulary table, and modal behaviour — plain non-technical tone, cross-linking `[[Openings]]` and `[[Analysis]]` per the wiki memo.
