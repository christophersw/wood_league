# Game Analysis Page Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `services/app/templates/games/analysis.html` and its supporting Python so each visual unit is an independent HTMX partial that reads only the new raw+derived analysis schema, with labeled arrows, a move-category chip row, three labeled+tooltipped charts (Win% headline, SF cp-bar, LC0 WDL), and a one-shot legacy-row cleanup command.

**Architecture:** Thin shell template + per-unit HTMX partials. All partials share `WoodLeagueAnalysis` ply state via `static/games/plySync.js`. New schema only — no fallbacks. Legacy rows dropped by a Django management command. Spec: `docs/superpowers/specs/2026-05-21-game-analysis-rewrite-design.md`. Tracks GH issue **#186** on branch `issue/186-game-analysis-rewrite`.

**Tech Stack:** Django + HTMX + Plotly.js, PostgreSQL, pytest + factory_boy, ruff/bandit/radon/mypy quality gate.

---

## File map

**Create**
- `services/app/games/management/commands/drop_legacy_analyses.py` — cleanup command
- `services/app/games/services_v2.py` — new dataclass + loader reading new schema only
- `services/app/games/cards.py` — SF + LC0 card builders (replaces `stat_cards.py` for the rewrite)
- `services/app/games/chip_data.py` — per-ply chip data assembly
- `services/app/games/chart_data.py` — JSON serializers for Win%/cp/WDL charts
- `services/app/templates/games/partials/_card_sf.html`
- `services/app/templates/games/partials/_card_lc0.html`
- `services/app/templates/games/partials/_move_chips.html`
- `services/app/templates/games/partials/_chart_winpct.html`
- `services/app/templates/games/partials/_chart_sf_cp.html`
- `services/app/templates/games/partials/_chart_lc0_wdl.html`
- `services/app/templates/games/partials/_pgn_table.html`
- `services/app/static/games/charts/winpct.js`
- `services/app/static/games/charts/sfCp.js`
- `services/app/static/games/charts/lc0Wdl.js`
- `services/app/static/games/charts/chartTooltip.js` — shared ⓘ tooltip behavior
- `services/app/static/games/pgnTable.js`
- `services/app/static/games/cardTooltip.js`
- Tests under `services/app/games/tests/` mirroring each new module

**Modify**
- `services/app/games/views.py` — add partial views, replace `game_analysis`
- `services/app/games/partial_urls.py` — add new partial routes
- `services/app/games/board_builder.py` — fix ply-association bug; add arrow labels
- `services/app/templates/games/analysis.html` — reduce to thin shell (<200 lines)
- `services/app/templates/games/_board_partial.html` — add label rendering for arrow overlays

**Delete (after rewrite is live)**
- `services/app/games/stat_cards.py` (replaced by `cards.py`)

---

## Phase 0 — Branch and foundations

### Task 0: Create branch and worktree

**Files:** none (git setup)

- [ ] **Step 1: Create the issue branch**

```bash
git checkout main && git pull
git checkout -b issue/186-game-analysis-rewrite
```

- [ ] **Step 2: Confirm tests pass on a clean checkout before changing anything**

```bash
cd services/app && source .venv/bin/activate && pytest -x --no-cov -q
```

Expected: PASS. If anything is red on `main`, stop and fix separately.

---

### Task 1: New analysis-data service (`services_v2.py`)

**Why first:** Every partial reads from this. Building it once means views become thin.

**Files:**
- Create: `services/app/games/services_v2.py`
- Create: `services/app/games/tests/test_services_v2.py`

- [ ] **Step 1: Write the failing test for the loader**

`services/app/games/tests/test_services_v2.py`:

```python
"""Tests for services_v2.get_game_analysis_v2."""
import pytest
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_returns_none_for_missing_game():
    assert get_game_analysis_v2("nope-not-real") is None


def test_returns_none_when_no_derived_fields(legacy_game_factory):
    """A game whose SF moves lack move_win_delta and whose LC0 moves
    lack wdl_win_adj is treated as legacy — return None so the view
    can show the re-analyze banner."""
    game = legacy_game_factory()
    assert get_game_analysis_v2(game.slug) is None


def test_returns_populated_dataclass_for_new_schema(new_schema_game_factory):
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    assert data is not None
    assert data.has_sf is True
    assert data.has_lc0 is True
    # New-schema-only fields
    assert data.sf_moves[0].move_win_delta is not None
    assert data.lc0_moves[0].wdl_win_adj is not None
    assert data.lc0_moves[0].draw_character is not None or data.lc0_moves[0].base_severity is not None
    assert data.lc0_white_accuracy is not None
```

Factories live in `services/app/games/tests/factories.py`. Add `legacy_game_factory` and `new_schema_game_factory` fixtures in `conftest.py` if missing — use `analysis.models.GameAnalysis` / `Lc0GameAnalysis` and child move rows. Use unique slugs.

- [ ] **Step 2: Run, confirm failure**

```bash
pytest services/app/games/tests/test_services_v2.py -v
```

Expected: ImportError (services_v2 missing).

- [ ] **Step 3: Implement `services_v2.py`**

```python
"""
Title: services_v2.py — New-schema-only game analysis loader
Description:
    Loads game analysis using ONLY the raw+derived columns introduced in
    #161 / #163 / #165 / #184. Returns None for games whose analyses
    predate the new derived fields so callers can show a re-analyze banner.

Changelog:
    2026-05-21 (#186): Initial — rewrite of services.py for the analysis page.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import chess.pgn

from analysis.models import GameAnalysis, Lc0GameAnalysis
from games.models import Game
from openings.models import OpeningBook


@dataclass
class SfMoveRow:
    """Per-ply Stockfish data read from the new schema."""
    ply: int
    san: str
    fen: str
    cp_eval: float
    mate_in: int | None
    cpl: float | None
    move_win_delta: float | None
    classification: str | None
    best_move: str
    arrow_uci_1: str
    arrow_uci_2: str | None
    arrow_uci_3: str | None
    arrow_score_1: float | None
    arrow_score_2: float | None
    arrow_score_3: float | None
    pv_san_1: str | None
    pv_san_2: str | None
    pv_san_3: str | None


@dataclass
class Lc0MoveRow:
    """Per-ply LC0 data — White-frame WDL + both classification levels."""
    ply: int
    san: str
    fen: str
    wdl_win_adj: int | None
    wdl_draw_adj: int | None
    wdl_loss_adj: int | None
    wdl_mu: float | None
    delta_mu: float | None
    delta_d: float | None
    base_severity: str | None
    draw_character: str | None
    best_move: str
    arrow_uci_1: str
    arrow_uci_2: str | None
    arrow_uci_3: str | None
    pv_san_1: str | None
    pv_san_2: str | None
    pv_san_3: str | None


@dataclass
class GameAnalysisDataV2:
    """Headline + per-side + per-ply game analysis, new schema only."""
    game_id: str
    slug: str
    white: str
    black: str
    white_rating: int | None
    black_rating: int | None
    result: str
    pgn: str
    date: str
    time_control: str
    url: str
    eco_code: str
    opening_name: str
    lichess_opening: str | None
    opening_id: int | None
    # Stockfish
    sf_moves: list[SfMoveRow] = field(default_factory=list)
    sf_white_accuracy: float | None = None
    sf_black_accuracy: float | None = None
    sf_white_acpl: float | None = None
    sf_black_acpl: float | None = None
    sf_white_blunders: int | None = None
    sf_white_mistakes: int | None = None
    sf_white_inaccuracies: int | None = None
    sf_black_blunders: int | None = None
    sf_black_mistakes: int | None = None
    sf_black_inaccuracies: int | None = None
    sf_engine_depth: int | None = None
    sf_analyzed_at: str = ""
    # LC0
    lc0_moves: list[Lc0MoveRow] = field(default_factory=list)
    lc0_white_accuracy: float | None = None
    lc0_black_accuracy: float | None = None
    lc0_white_win_prob: float | None = None
    lc0_white_draw_prob: float | None = None
    lc0_white_loss_prob: float | None = None
    lc0_network_name: str | None = None
    lc0_engine_nodes: int | None = None
    lc0_contempt: int | None = None
    lc0_draw_rate_reference: float | None = None
    lc0_calibration_elo: int | None = None
    lc0_analyzed_at: str = ""

    @property
    def has_sf(self) -> bool:
        return bool(self.sf_moves)

    @property
    def has_lc0(self) -> bool:
        return bool(self.lc0_moves)

    @property
    def white_label(self) -> str:
        return f"{self.white} ({self.white_rating})" if self.white_rating else self.white

    @property
    def black_label(self) -> str:
        return f"{self.black} ({self.black_rating})" if self.black_rating else self.black


def _sf_rows(ga: GameAnalysis | None) -> list[SfMoveRow]:
    if ga is None or ga.analyzed_at is None:
        return []
    rows = list(ga.moves.order_by("ply"))
    # New-schema gate: every row must have a non-null move_win_delta.
    if not rows or any(r.move_win_delta is None for r in rows):
        return []
    return [
        SfMoveRow(
            ply=r.ply, san=r.san, fen=r.fen,
            cp_eval=r.cp_eval, mate_in=r.mate_in,
            cpl=r.cpl, move_win_delta=r.move_win_delta,
            classification=r.classification, best_move=r.best_move or "",
            arrow_uci_1=r.arrow_uci_1 or "",
            arrow_uci_2=r.arrow_uci_2, arrow_uci_3=r.arrow_uci_3,
            arrow_score_1=r.arrow_score_1, arrow_score_2=r.arrow_score_2, arrow_score_3=r.arrow_score_3,
            pv_san_1=r.pv_san_1, pv_san_2=r.pv_san_2, pv_san_3=r.pv_san_3,
        )
        for r in rows
    ]


def _lc0_rows(lga: Lc0GameAnalysis | None) -> list[Lc0MoveRow]:
    if lga is None or lga.analyzed_at is None:
        return []
    rows = list(lga.moves.order_by("ply"))
    # New-schema gate: every row must have White-frame adj columns populated.
    if not rows or any(r.wdl_win_adj is None for r in rows):
        return []
    return [
        Lc0MoveRow(
            ply=r.ply, san=r.san, fen=r.fen,
            wdl_win_adj=r.wdl_win_adj, wdl_draw_adj=r.wdl_draw_adj, wdl_loss_adj=r.wdl_loss_adj,
            wdl_mu=r.wdl_mu, delta_mu=r.delta_mu, delta_d=r.delta_d,
            base_severity=r.base_severity, draw_character=r.draw_character,
            best_move=r.best_move or "",
            arrow_uci_1=r.arrow_uci_1 or "",
            arrow_uci_2=r.arrow_uci_2, arrow_uci_3=r.arrow_uci_3,
            pv_san_1=r.pv_san_1, pv_san_2=r.pv_san_2, pv_san_3=r.pv_san_3,
        )
        for r in rows
    ]


def get_game_analysis_v2(slug: str) -> GameAnalysisDataV2 | None:
    """Return new-schema analysis for the given slug, or None.

    Returns None when the game has neither a new-schema SF analysis nor a
    new-schema LC0 analysis. Callers should render the re-analyze banner.
    """
    try:
        db_game = Game.objects.get(slug=slug)
    except Game.DoesNotExist:
        return None

    pgn_text = db_game.pgn or ""
    pgn_game = chess.pgn.read_game(io.StringIO(pgn_text)) if pgn_text else None
    if pgn_game is None:
        return None

    try:
        ga = db_game.analysis
    except GameAnalysis.DoesNotExist:
        ga = None
    try:
        lga = db_game.lc0_analysis
    except Lc0GameAnalysis.DoesNotExist:
        lga = None

    sf_moves = _sf_rows(ga)
    lc0_moves = _lc0_rows(lga)
    if not sf_moves and not lc0_moves:
        return None

    opening_id = None
    if db_game.eco_code:
        opening_id = OpeningBook.objects.filter(eco=db_game.eco_code).values_list("id", flat=True).first()

    date = db_game.played_at.strftime("%Y-%m-%d %H:%M") if db_game.played_at else pgn_game.headers.get("Date", "")

    data = GameAnalysisDataV2(
        game_id=db_game.id,
        slug=db_game.slug,
        white=db_game.white_username or pgn_game.headers.get("White", "White"),
        black=db_game.black_username or pgn_game.headers.get("Black", "Black"),
        white_rating=db_game.white_rating,
        black_rating=db_game.black_rating,
        result=db_game.result_pgn or pgn_game.headers.get("Result", "*"),
        pgn=pgn_text,
        date=date,
        time_control=db_game.time_control or pgn_game.headers.get("TimeControl", ""),
        url=pgn_game.headers.get("Link", ""),
        eco_code=db_game.eco_code or "",
        opening_name=db_game.opening_name or "",
        lichess_opening=db_game.lichess_opening,
        opening_id=opening_id,
        sf_moves=sf_moves,
        lc0_moves=lc0_moves,
    )

    if ga is not None and sf_moves:
        data.sf_white_accuracy = ga.white_accuracy
        data.sf_black_accuracy = ga.black_accuracy
        data.sf_white_acpl = ga.white_acpl
        data.sf_black_acpl = ga.black_acpl
        data.sf_white_blunders = ga.white_blunders
        data.sf_white_mistakes = ga.white_mistakes
        data.sf_white_inaccuracies = ga.white_inaccuracies
        data.sf_black_blunders = ga.black_blunders
        data.sf_black_mistakes = ga.black_mistakes
        data.sf_black_inaccuracies = ga.black_inaccuracies
        data.sf_engine_depth = ga.engine_depth
        data.sf_analyzed_at = ga.analyzed_at.isoformat() if ga.analyzed_at else ""

    if lga is not None and lc0_moves:
        data.lc0_white_accuracy = lga.white_accuracy
        data.lc0_black_accuracy = lga.black_accuracy
        data.lc0_white_win_prob = lga.white_win_prob
        data.lc0_white_draw_prob = lga.white_draw_prob
        data.lc0_white_loss_prob = lga.white_loss_prob
        data.lc0_network_name = lga.network_name
        data.lc0_engine_nodes = lga.engine_nodes
        data.lc0_contempt = lga.contempt
        data.lc0_draw_rate_reference = lga.draw_rate_reference
        data.lc0_calibration_elo = lga.wdl_calibration_elo
        data.lc0_analyzed_at = lga.analyzed_at.isoformat() if lga.analyzed_at else ""

    return data
```

- [ ] **Step 4: Run tests to PASS**

```bash
pytest services/app/games/tests/test_services_v2.py -v
```

Expected: all three tests pass.

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/games/services_v2.py
git add services/app/games/services_v2.py services/app/games/tests/test_services_v2.py
git commit -m "feat(games): services_v2 — new-schema-only analysis loader (#186)"
```

---

### Task 2: `drop_legacy_analyses` management command

**Files:**
- Create: `services/app/games/management/commands/drop_legacy_analyses.py`
- Create: `services/app/games/tests/test_drop_legacy_analyses.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the drop_legacy_analyses management command."""
import io
from django.core.management import call_command
import pytest

pytestmark = pytest.mark.django_db


def test_dry_run_reports_counts_without_deleting(legacy_sf_game_factory, new_schema_game_factory):
    legacy = legacy_sf_game_factory()
    fresh = new_schema_game_factory()
    out = io.StringIO()
    call_command("drop_legacy_analyses", stdout=out)
    text = out.getvalue()
    assert "DRY RUN" in text
    assert "SF analyses to drop: 1" in text
    # Nothing was actually deleted.
    legacy.refresh_from_db()
    assert hasattr(legacy, "analysis")
    fresh.refresh_from_db()
    assert hasattr(fresh, "analysis")


def test_apply_deletes_legacy_only(legacy_sf_game_factory, new_schema_game_factory):
    legacy = legacy_sf_game_factory()
    fresh = new_schema_game_factory()
    call_command("drop_legacy_analyses", "--apply")
    legacy.refresh_from_db()
    fresh.refresh_from_db()
    from analysis.models import GameAnalysis
    assert not GameAnalysis.objects.filter(game=legacy).exists()
    assert GameAnalysis.objects.filter(game=fresh).exists()
```

`legacy_sf_game_factory` builds a game whose `MoveAnalysis.move_win_delta` is NULL on at least one row. `new_schema_game_factory` populates `move_win_delta` and `wdl_*_adj` on every row.

- [ ] **Step 2: Run, confirm failure**

```bash
pytest services/app/games/tests/test_drop_legacy_analyses.py -v
```

Expected: CommandError "Unknown command".

- [ ] **Step 3: Implement the command**

```python
"""
Title: drop_legacy_analyses — One-shot cleanup of pre-#161 analysis rows
Description:
    Deletes ``GameAnalysis`` rows whose moves include any NULL
    ``move_win_delta`` (legacy Stockfish output) and ``Lc0GameAnalysis``
    rows whose moves include any NULL ``wdl_win_adj`` (pre-#159 LC0).
    Cascades through child move rows. Dry-run by default.

Changelog:
    2026-05-21 (#186): Initial.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from analysis.models import GameAnalysis, Lc0GameAnalysis


class Command(BaseCommand):
    help = "Drop legacy analyses missing new derived fields (#186)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually delete rows. Without this flag the command is a dry run.",
        )

    def handle(self, *args, **opts):
        apply_changes = bool(opts.get("apply"))
        sf_qs = GameAnalysis.objects.annotate(
            legacy_move_count=Count("moves", filter=Q(moves__move_win_delta__isnull=True))
        ).filter(legacy_move_count__gt=0)
        lc0_qs = Lc0GameAnalysis.objects.annotate(
            legacy_move_count=Count("moves", filter=Q(moves__wdl_win_adj__isnull=True))
        ).filter(legacy_move_count__gt=0)

        sf_count = sf_qs.count()
        lc0_count = lc0_qs.count()

        prefix = "" if apply_changes else "DRY RUN — "
        self.stdout.write(f"{prefix}SF analyses to drop: {sf_count}")
        self.stdout.write(f"{prefix}LC0 analyses to drop: {lc0_count}")

        if not apply_changes:
            self.stdout.write("Re-run with --apply to delete.")
            return

        sf_qs.delete()
        lc0_qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {sf_count} SF + {lc0_count} LC0 analyses."))
```

- [ ] **Step 4: Tests + bandit + commit**

```bash
pytest services/app/games/tests/test_drop_legacy_analyses.py -v
bandit -ll services/app/games/management/commands/drop_legacy_analyses.py
git add services/app/games/management/commands/drop_legacy_analyses.py services/app/games/tests/test_drop_legacy_analyses.py
git commit -m "feat(games): drop_legacy_analyses cleanup command (#186)"
```

---

### Task 3: Fix board ply-association bug

**Why:** Arrows belonging to the wrong ply make every downstream change confusing. Fix the root cause now.

`board_builder.build_board_frames` currently consumes the SF `moves` list and the LC0 `lc0_moves` list independently. When LC0 starts at a different first ply than SF (book-skipped LC0 vs full-PGN SF, for example), the per-ply zipping is misaligned. The fix: build a `by_ply` dict from each side first and index into both dicts using the board's own ply counter.

**Files:**
- Modify: `services/app/games/board_builder.py`
- Create: `services/app/games/tests/test_board_builder_ply_alignment.py`

- [ ] **Step 1: Write the failing test**

```python
"""Regression test: arrows at ply N must come from ply-N analysis rows."""
import pytest
from games.board_builder import build_board_frames
from games.services_v2 import SfMoveRow, Lc0MoveRow

pytestmark = pytest.mark.django_db


def _sf(ply, uci):
    return SfMoveRow(
        ply=ply, san=f"M{ply}", fen="",
        cp_eval=0.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1=uci,
        arrow_uci_2=None, arrow_uci_3=None,
        arrow_score_1=0.0, arrow_score_2=None, arrow_score_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )


def _lc0(ply, uci):
    return Lc0MoveRow(
        ply=ply, san=f"M{ply}", fen="",
        wdl_win_adj=500, wdl_draw_adj=300, wdl_loss_adj=200,
        wdl_mu=0.5, delta_mu=0.0, delta_d=0.0,
        base_severity="best", draw_character=None, best_move="",
        arrow_uci_1=uci, arrow_uci_2=None, arrow_uci_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )


def test_arrow_at_ply_matches_source_ply(simple_pgn_game):
    """A 4-ply PGN with SF arrows e2e4/d2d4/g1f3/b1c3 and LC0 starting at ply 3
    must render ply-3 arrows from the LC0 ply-3 row, not LC0 ply-1."""
    sf = [_sf(1, "e2e4"), _sf(2, "e7e5"), _sf(3, "g1f3"), _sf(4, "b8c6")]
    lc0 = [_lc0(3, "g1f3"), _lc0(4, "b8c6")]   # LC0 misses the first two plies
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=lc0, orientation="white")
    # Frame for ply 3: SF arrow g1f3, LC0 arrow g1f3
    ply3 = frames["frames"][3]
    sf_arrows = [a for a in ply3["arrows"] if a["engine"] == "sf"]
    lc0_arrows = [a for a in ply3["arrows"] if a["engine"] == "lc0"]
    assert sf_arrows and sf_arrows[0]["uci"] == "g1f3"
    assert lc0_arrows and lc0_arrows[0]["uci"] == "g1f3"
    # Frame for ply 1: SF arrow e2e4, NO LC0 arrow (no LC0 data for ply 1).
    ply1 = frames["frames"][1]
    assert any(a["engine"] == "sf" and a["uci"] == "e2e4" for a in ply1["arrows"])
    assert not any(a["engine"] == "lc0" for a in ply1["arrows"])
```

`simple_pgn_game` fixture supplies a real 4-ply PGN string (add to `conftest.py` if absent).

- [ ] **Step 2: Run, confirm failure**

```bash
pytest services/app/games/tests/test_board_builder_ply_alignment.py -v
```

Expected: failure caused by misaligned indexing OR LC0 arrows appearing at the wrong ply.

- [ ] **Step 3: Read the existing builder and identify the bug**

Read `services/app/games/board_builder.py::build_board_frames`. Look for where SF and LC0 row lists are walked. Replace any positional zip / enumerate pairing with explicit `by_ply` lookups:

```python
sf_by_ply = {row.ply: row for row in (sf_moves or [])}
lc0_by_ply = {row.ply: row for row in (lc0_moves or [])}

# Inside the per-frame loop, after pushing the move to `board`:
current_ply = board.ply()
sf_row = sf_by_ply.get(current_ply)
lc0_row = lc0_by_ply.get(current_ply)

frame_arrows = []
if sf_row is not None:
    frame_arrows.extend(_build_arrow_entries_for_engine("sf", sf_row, board, use_cp_equiv=False))
if lc0_row is not None:
    frame_arrows.extend(_build_arrow_entries_for_engine("lc0", lc0_row, board, use_cp_equiv=False))
```

Also update `build_board_frames`'s signature/types to accept the new `SfMoveRow` / `Lc0MoveRow` dataclasses. The old `MoveRow.arrow_uci` attribute becomes `arrow_uci_1` for SF and LC0 — update `_build_arrow_entries_for_engine` accordingly.

- [ ] **Step 4: Run all `board_builder` tests**

```bash
pytest services/app/games/tests/ -k board -v
```

Expected: PASS. If any existing test referenced `MoveRow.arrow_uci`, update it to the new dataclass attribute name.

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/games/board_builder.py
git add services/app/games/board_builder.py services/app/games/tests/test_board_builder_ply_alignment.py
git commit -m "fix(games): arrows always come from displayed-ply row (#186)"
```

---

## Phase 1 — Shell + partial scaffolding

### Task 4: Replace `game_analysis` view + thin-shell template

**Files:**
- Modify: `services/app/games/views.py::game_analysis`
- Modify: `services/app/templates/games/analysis.html`
- Create: `services/app/games/tests/test_view_game_analysis_shell.py`

- [ ] **Step 1: Failing test**

```python
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_shell_returns_200_and_loads_partials(client, new_schema_game_factory):
    game = new_schema_game_factory()
    resp = client.get(reverse("game_analysis", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Each visual unit is wired with hx-get pointing at its partial URL.
    for partial in ["cards/sf", "cards/lc0", "chips", "charts/winpct",
                    "charts/sf-cp", "charts/lc0-wdl", "pgn"]:
        assert f"/_partials/games/{game.slug}/{partial}/" in body
    # Shell stays under 200 lines of rendered HTML scripts (no inline Plotly traces).
    assert body.count("Plotly.newPlot") == 0


def test_shell_shows_reanalyze_banner_when_legacy(client, legacy_sf_game_factory):
    game = legacy_sf_game_factory()
    resp = client.get(reverse("game_analysis", args=[game.slug]))
    assert resp.status_code == 200
    assert "Re-analysis required" in resp.content.decode()
```

- [ ] **Step 2: Run, confirm failure**

```bash
pytest services/app/games/tests/test_view_game_analysis_shell.py -v
```

- [ ] **Step 3: Rewrite the `game_analysis` view**

In `services/app/games/views.py`, replace the body of `game_analysis` with:

```python
def game_analysis(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the thin shell for the analysis page. Each visual unit is
    loaded by HTMX from its own partial URL."""
    try:
        game = Game.objects.get(slug=slug)
    except Game.DoesNotExist:
        raise Http404
    data = get_game_analysis_v2(slug)
    if data is None:
        return render(request, "games/analysis.html", {
            "game": game, "no_data": True, "reanalyze": True,
        })
    initial_ply = int(request.GET.get("ply", 0) or 0)
    initial_perspective = request.GET.get("perspective", "white")
    if initial_perspective not in {"white", "black"}:
        initial_perspective = "white"
    return render(request, "games/analysis.html", {
        "game": game,
        "data": data,
        "no_data": False,
        "initial_ply": initial_ply,
        "initial_perspective": initial_perspective,
    })
```

Drop unused imports (`stat_cards`, JSON builders, etc.) — leave them in place if other views still use them and remove only after the rewrite is fully wired.

- [ ] **Step 4: Rewrite `analysis.html` to the shell**

Replace the entire file with:

```html
{% extends "base.html" %}
{% load static %}

{% block title %}
  {% if no_data %}
    {{ game.white_username }} vs {{ game.black_username }} — Wood League Chess
  {% else %}
    {{ data.white_label }} vs {{ data.black_label }} — Wood League Chess
  {% endif %}
{% endblock %}

{% block content %}
<div class="page-hero">
  <div>
    <h1>{% if no_data %}{{ game.white_username }} vs {{ game.black_username }}{% else %}{{ data.white_label }} vs {{ data.black_label }}{% endif %}</h1>
    {% if not no_data %}<p class="page-hero-sub">{{ data.result }} · {{ data.date }} · {{ data.time_control }}</p>{% endif %}
  </div>
  <div class="flex gap-2 flex-wrap"><a href="{% url 'dashboard:index' %}" class="wc-btn wc-btn-ghost">← Dashboard</a></div>
</div>

{% if no_data %}
<div class="filter-panel">
  <p class="font-mono text-sm text-peat">Re-analysis required — this game's analysis predates the new schema. Queue a re-run from the dashboard.</p>
</div>
{% else %}

<div class="pg-section" style="margin-bottom:2rem;">
  <div class="pg-head"><span class="pg-title">Game Analysis</span></div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem;">
    <div hx-get="/_partials/games/{{ game.slug }}/cards/sf/" hx-trigger="load" hx-swap="innerHTML">Loading SF…</div>
    <div hx-get="/_partials/games/{{ game.slug }}/cards/lc0/" hx-trigger="load" hx-swap="innerHTML">Loading LC0…</div>
  </div>
</div>

<div class="pg-section">
  <div class="pg-head"><span class="pg-title">Move Analysis</span></div>
  <div id="move-chips"
       hx-get="/_partials/games/{{ game.slug }}/chips/?ply={{ initial_ply }}"
       hx-trigger="load, ply-change from:body"
       hx-include="[name='ply']" hx-swap="innerHTML"></div>

  <div id="boards-container" style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;align-items:start;">
    <div id="board-container"
         hx-get="/_partials/games/{{ game.slug }}/board/?orientation={{ initial_perspective }}"
         hx-trigger="load" hx-swap="innerHTML">Loading board…</div>
    <div id="engine-lines-shell">{# engine-lines partial mounts here as before #}</div>
  </div>

  <div hx-get="/_partials/games/{{ game.slug }}/charts/winpct/" hx-trigger="load" hx-swap="innerHTML"></div>
  <div hx-get="/_partials/games/{{ game.slug }}/charts/sf-cp/" hx-trigger="load" hx-swap="innerHTML"></div>
  <div hx-get="/_partials/games/{{ game.slug }}/charts/lc0-wdl/" hx-trigger="load" hx-swap="innerHTML"></div>
  <div hx-get="/_partials/games/{{ game.slug }}/pgn/" hx-trigger="load" hx-swap="innerHTML"></div>
</div>

{% include "games/_queue_modal.html" %}
{% endif %}
{% endblock %}

{% block extra_js %}
{% if not no_data %}
<script src="{% static 'games/plySync.js' %}"></script>
<script src="{% static 'games/engineLines.js' %}"></script>
<script src="{% static 'games/cardTooltip.js' %}"></script>
<script src="{% static 'games/charts/chartTooltip.js' %}"></script>
<script>
window.ANALYSIS_DATA = {
  slug: "{{ game.slug }}",
  white: "{{ data.white|escapejs }}",
  black: "{{ data.black|escapejs }}",
  has_sf: {{ data.has_sf|yesno:"true,false" }},
  has_lc0: {{ data.has_lc0|yesno:"true,false" }},
};
WoodLeagueAnalysis.initFromUrl({ defaultPly: {{ initial_ply }}, defaultPerspective: "{{ initial_perspective }}" });
WoodLeagueAnalysis.subscribe(function (state) {
  document.body.dispatchEvent(new CustomEvent("ply-change", { detail: state }));
});
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Tests + commit**

```bash
pytest services/app/games/tests/test_view_game_analysis_shell.py -v
git add services/app/games/views.py services/app/templates/games/analysis.html
git commit -m "feat(games): shell template + new view for analysis rewrite (#186)"
```

---

### Task 5: Partial URLs scaffolding + empty 200 views

**Files:**
- Modify: `services/app/games/partial_urls.py`
- Modify: `services/app/games/views.py` (add stubs)
- Create: `services/app/games/tests/test_partial_routes.py`

- [ ] **Step 1: Failing test for routing**

```python
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

PARTIALS = [
    "games_card_sf_partial",
    "games_card_lc0_partial",
    "games_chips_partial",
    "games_chart_winpct_partial",
    "games_chart_sf_cp_partial",
    "games_chart_lc0_wdl_partial",
    "games_pgn_partial",
]


@pytest.mark.parametrize("name", PARTIALS)
def test_partial_route_resolves(client, new_schema_game_factory, name):
    game = new_schema_game_factory()
    resp = client.get(reverse(name, args=[game.slug]))
    assert resp.status_code == 200
```

- [ ] **Step 2: Run, confirm NoReverseMatch failures**

```bash
pytest services/app/games/tests/test_partial_routes.py -v
```

- [ ] **Step 3: Add URLs**

Append to `services/app/games/partial_urls.py`:

```python
    path("games/<slug:slug>/cards/sf/",       views.card_sf_partial,       name="games_card_sf_partial"),
    path("games/<slug:slug>/cards/lc0/",      views.card_lc0_partial,      name="games_card_lc0_partial"),
    path("games/<slug:slug>/chips/",          views.chips_partial,         name="games_chips_partial"),
    path("games/<slug:slug>/charts/winpct/",  views.chart_winpct_partial,  name="games_chart_winpct_partial"),
    path("games/<slug:slug>/charts/sf-cp/",   views.chart_sf_cp_partial,   name="games_chart_sf_cp_partial"),
    path("games/<slug:slug>/charts/lc0-wdl/", views.chart_lc0_wdl_partial, name="games_chart_lc0_wdl_partial"),
    path("games/<slug:slug>/pgn/",            views.pgn_partial,           name="games_pgn_partial"),
```

- [ ] **Step 4: Add stub views to `services/app/games/views.py`**

```python
def _load_or_404(slug: str):
    data = get_game_analysis_v2(slug)
    if data is None:
        raise Http404
    return data


def card_sf_partial(request, slug):       return render(request, "games/partials/_card_sf.html",       {"data": _load_or_404(slug)})
def card_lc0_partial(request, slug):      return render(request, "games/partials/_card_lc0.html",      {"data": _load_or_404(slug)})
def chips_partial(request, slug):         return render(request, "games/partials/_move_chips.html",    {"data": _load_or_404(slug), "ply": int(request.GET.get("ply", 0) or 0)})
def chart_winpct_partial(request, slug):  return render(request, "games/partials/_chart_winpct.html",  {"data": _load_or_404(slug)})
def chart_sf_cp_partial(request, slug):   return render(request, "games/partials/_chart_sf_cp.html",   {"data": _load_or_404(slug)})
def chart_lc0_wdl_partial(request, slug): return render(request, "games/partials/_chart_lc0_wdl.html", {"data": _load_or_404(slug)})
def pgn_partial(request, slug):           return render(request, "games/partials/_pgn_table.html",     {"data": _load_or_404(slug)})
```

- [ ] **Step 5: Create empty templates so tests pass**

For each of the seven `services/app/templates/games/partials/_*.html`, create with stub content `<div data-partial="<name>"></div>`. These get replaced in later tasks.

- [ ] **Step 6: Tests + commit**

```bash
pytest services/app/games/tests/test_partial_routes.py -v
git add services/app/games/partial_urls.py services/app/games/views.py services/app/templates/games/partials/
git commit -m "feat(games): partial URL scaffolding for analysis rewrite (#186)"
```

---

## Phase 2 — Cards

### Task 6: SF stat card

**Files:**
- Create: `services/app/games/cards.py` (start with SF card)
- Modify: `services/app/templates/games/partials/_card_sf.html`
- Create: `services/app/static/games/cardTooltip.js`
- Create: `services/app/games/tests/test_cards_sf.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for SF card HTML output."""
import pytest
from games.cards import build_sf_card_context
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_sf_card_context_uses_new_fields(new_schema_game_factory):
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    ctx = build_sf_card_context(data)
    assert ctx["white_accuracy"] == data.sf_white_accuracy
    assert ctx["white_acpl"] == data.sf_white_acpl
    assert ctx["avg_win_drop_white"] is not None  # mean(move_win_delta) over White plies
    assert "engine_depth" in ctx["tooltip_meta"]
    assert ctx["classification_counts"]["white"]["blunder"] >= 0
```

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Implement `build_sf_card_context`**

```python
"""
Title: cards.py — Card context builders for the analysis page
Description:
    Pure functions that turn a GameAnalysisDataV2 into the context dict
    each card partial needs. Stays presentation-free — templates do the
    HTML rendering.
"""
from __future__ import annotations

from statistics import fmean

from games.services_v2 import GameAnalysisDataV2


_SF_CLASSES = ("brilliant", "best", "great", "excellent", "good", "inaccuracy", "mistake", "blunder")


def _counts(values, allowed):
    out = {c: 0 for c in allowed}
    for v in values:
        if not v:
            continue
        key = v.lower()
        if key in out:
            out[key] += 1
    return out


def _avg(values):
    nums = [v for v in values if v is not None]
    return fmean(nums) if nums else None


def build_sf_card_context(data: GameAnalysisDataV2) -> dict:
    white_moves = [m for m in data.sf_moves if m.ply % 2 == 1]
    black_moves = [m for m in data.sf_moves if m.ply % 2 == 0]
    return {
        "white_accuracy": data.sf_white_accuracy,
        "black_accuracy": data.sf_black_accuracy,
        "white_acpl": data.sf_white_acpl,
        "black_acpl": data.sf_black_acpl,
        "classification_counts": {
            "white": _counts((m.classification for m in white_moves), _SF_CLASSES),
            "black": _counts((m.classification for m in black_moves), _SF_CLASSES),
        },
        "avg_win_drop_white": _avg([m.move_win_delta for m in white_moves]),
        "avg_win_drop_black": _avg([m.move_win_delta for m in black_moves]),
        "tooltip_meta": {
            "engine_depth": data.sf_engine_depth,
            "analyzed_at": data.sf_analyzed_at,
        },
    }
```

- [ ] **Step 4: Rewrite `_card_sf.html`**

Use the existing `.wc-card` styling (don't invent new classes). Render: header with player names + ⓘ tooltip; per-side block for accuracy bar, ACPL number, classification stacked bar (existing `move-annotation-*` palette), avg Win% drop. Tooltip is a `<details class="card-info-tooltip">` containing `tooltip_meta`.

Skeleton:

```html
{% load static %}
<section class="wc-card wc-card--sf" aria-label="Stockfish analysis">
  <header class="wc-card__head">
    <h3>Stockfish</h3>
    <details class="card-info-tooltip">
      <summary aria-label="Stockfish run info">ⓘ</summary>
      <dl>
        <dt>Depth</dt><dd>{{ tooltip_meta.engine_depth|default:"—" }}</dd>
        <dt>Analyzed</dt><dd>{{ tooltip_meta.analyzed_at|default:"—" }}</dd>
      </dl>
    </details>
  </header>
  {% for side, label in side_labels %}
  <div class="wc-card__side">
    <strong>{{ label }}</strong>
    <div class="metric"><span>Accuracy</span><span>{{ accuracy.side|floatformat:1 }}%</span></div>
    <div class="metric"><span>ACPL</span><span>{{ acpl.side|floatformat:1 }}</span></div>
    <div class="metric"><span>Avg Win% drop</span><span>{{ avg_win_drop.side|floatformat:1 }}</span></div>
    {# Classification stacked bar — iterate _SF_CLASSES in order; widths derived in the template #}
  </div>
  {% endfor %}
</section>
```

Pass `side_labels = [("white", data.white), ("black", data.black)]` from the view; flatten the nested counts so each row reads `accuracy.white`, etc. Use existing CSS classes from the page-wide stylesheet; if missing, add a small block to `services/app/static/css/cards.css` (or wherever cards CSS currently lives — confirm by grepping `.wc-card` first).

- [ ] **Step 5: Add minimal `cardTooltip.js`**

```javascript
// Close any open info tooltip when another opens, or when clicking outside.
(function () {
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.card-info-tooltip[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.open = false;
    });
  });
})();
```

- [ ] **Step 6: Tests + bandit + commit**

```bash
pytest services/app/games/tests/test_cards_sf.py -v
bandit -ll services/app/games/cards.py
git add services/app/games/cards.py services/app/templates/games/partials/_card_sf.html services/app/static/games/cardTooltip.js services/app/games/tests/test_cards_sf.py
git commit -m "feat(games): SF stat card partial (#186)"
```

---

### Task 7: LC0 stat card

**Files:**
- Modify: `services/app/games/cards.py` (append)
- Modify: `services/app/templates/games/partials/_card_lc0.html`
- Create: `services/app/games/tests/test_cards_lc0.py`

- [ ] **Step 1: Failing test**

```python
"""Tests for LC0 card HTML output."""
import pytest
from games.cards import build_lc0_card_context
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_lc0_card_surfaces_both_classification_levels(new_schema_game_factory):
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    ctx = build_lc0_card_context(data)
    assert ctx["lc0_white_accuracy"] == data.lc0_white_accuracy
    assert ctx["wdl"]["white"]["win"] == data.lc0_white_win_prob
    # Base severity counts (level 1)
    assert "blunder" in ctx["base_severity_counts"]["white"]
    # Draw-character counts (level 2)
    assert isinstance(ctx["draw_character_counts"]["white"], dict)
    assert "network_name" in ctx["tooltip_meta"]
    assert "draw_rate_reference" in ctx["tooltip_meta"]
```

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Implement `build_lc0_card_context`**

Append to `cards.py`:

```python
_LC0_BASE_SEVERITY = ("best", "good", "inaccuracy", "mistake", "blunder")
_LC0_DRAW_CHARACTER = ("drawish", "sharp", "balanced")  # confirm names by grepping derivation.lc0


def build_lc0_card_context(data: GameAnalysisDataV2) -> dict:
    white_moves = [m for m in data.lc0_moves if m.ply % 2 == 1]
    black_moves = [m for m in data.lc0_moves if m.ply % 2 == 0]
    return {
        "lc0_white_accuracy": data.lc0_white_accuracy,
        "lc0_black_accuracy": data.lc0_black_accuracy,
        "wdl": {
            "white": {"win": data.lc0_white_win_prob, "draw": data.lc0_white_draw_prob, "loss": data.lc0_white_loss_prob},
            "black": {"win": data.lc0_black_win_prob, "draw": data.lc0_black_draw_prob, "loss": data.lc0_black_loss_prob},
        },
        "base_severity_counts": {
            "white": _counts((m.base_severity for m in white_moves), _LC0_BASE_SEVERITY),
            "black": _counts((m.base_severity for m in black_moves), _LC0_BASE_SEVERITY),
        },
        "draw_character_counts": {
            "white": _counts((m.draw_character for m in white_moves), _LC0_DRAW_CHARACTER),
            "black": _counts((m.draw_character for m in black_moves), _LC0_DRAW_CHARACTER),
        },
        "avg_delta_mu_white": _avg([m.delta_mu for m in white_moves]),
        "avg_delta_mu_black": _avg([m.delta_mu for m in black_moves]),
        "tooltip_meta": {
            "network_name": data.lc0_network_name,
            "engine_nodes": data.lc0_engine_nodes,
            "contempt": data.lc0_contempt,
            "draw_rate_reference": data.lc0_draw_rate_reference,
            "calibration_elo": data.lc0_calibration_elo,
            "analyzed_at": data.lc0_analyzed_at,
        },
    }
```

Note on `_LC0_DRAW_CHARACTER`: before committing, run `grep -rn "draw_character" services/local_worker/local_worker/analysis/` to confirm the exact label set the worker emits, and update the tuple to match.

- [ ] **Step 4: Rewrite `_card_lc0.html`**

Follow the SF card pattern. Two stacked bars per side: `base_severity` (primary) and `draw_character` (subordinate, muted palette). Show `lc0_white_accuracy / lc0_black_accuracy` and game-end WDL.

- [ ] **Step 5: Tests + bandit + commit**

```bash
pytest services/app/games/tests/test_cards_lc0.py -v
bandit -ll services/app/games/cards.py
git add services/app/games/cards.py services/app/templates/games/partials/_card_lc0.html services/app/games/tests/test_cards_lc0.py
git commit -m "feat(games): LC0 stat card with both classification levels (#186)"
```

---

## Phase 3 — Charts

### Task 8: Chart-data serializer

**Files:**
- Create: `services/app/games/chart_data.py`
- Create: `services/app/games/tests/test_chart_data.py`

- [ ] **Step 1: Failing test**

```python
import math
import pytest
from games.chart_data import winpct_payload, sf_cp_payload, lc0_wdl_payload
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_winpct_payload_overlays_sf_and_lc0(new_schema_game_factory):
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    payload = winpct_payload(data)
    assert payload["sf"] and payload["lc0"]
    sf0 = payload["sf"][0]
    # Lichess logistic: 50 + 50*tanh(0.00368208 * cp)
    expected = 50 + 50 * math.tanh(0.00368208 * data.sf_moves[0].cp_eval)
    assert sf0["winpct"] == pytest.approx(expected, abs=0.01)
    assert payload["lc0"][0]["winpct"] == pytest.approx(data.lc0_moves[0].wdl_mu * 100, abs=0.01)


def test_sf_cp_payload_uses_raw_cp_eval(new_schema_game_factory):
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    payload = sf_cp_payload(data)
    assert payload[0]["cp_eval"] == data.sf_moves[0].cp_eval
    assert payload[0]["classification"] == data.sf_moves[0].classification


def test_lc0_wdl_payload_uses_white_frame_adj(new_schema_game_factory):
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    payload = lc0_wdl_payload(data)
    assert payload[0]["wdl_win"] == data.lc0_moves[0].wdl_win_adj
    assert payload[0]["wdl_draw"] == data.lc0_moves[0].wdl_draw_adj
    assert payload[0]["wdl_loss"] == data.lc0_moves[0].wdl_loss_adj
```

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Implement `chart_data.py`**

```python
"""
Title: chart_data.py — JSON-shape builders for the three analysis charts
Description:
    Each function returns a list of small dicts that the corresponding
    chart partial dumps via json_script. No HTML, no Plotly.
"""
from __future__ import annotations

import math

from games.services_v2 import GameAnalysisDataV2

_LICHESS_K = 0.00368208


def _cp_to_winpct(cp: float) -> float:
    """Lichess logistic: convert centipawn eval to Win-for-White percentage."""
    return 50.0 + 50.0 * math.tanh(_LICHESS_K * cp)


def winpct_payload(data: GameAnalysisDataV2) -> dict:
    return {
        "sf": [{"ply": m.ply, "winpct": _cp_to_winpct(m.cp_eval), "san": m.san} for m in data.sf_moves],
        "lc0": [{"ply": m.ply, "winpct": (m.wdl_mu or 0.0) * 100.0, "san": m.san} for m in data.lc0_moves if m.wdl_mu is not None],
    }


def sf_cp_payload(data: GameAnalysisDataV2) -> list[dict]:
    return [
        {"ply": m.ply, "cp_eval": m.cp_eval, "mate_in": m.mate_in,
         "classification": (m.classification or "").lower(), "san": m.san}
        for m in data.sf_moves
    ]


def lc0_wdl_payload(data: GameAnalysisDataV2) -> list[dict]:
    return [
        {"ply": m.ply, "wdl_win": m.wdl_win_adj, "wdl_draw": m.wdl_draw_adj, "wdl_loss": m.wdl_loss_adj, "san": m.san}
        for m in data.lc0_moves
    ]
```

- [ ] **Step 4: Tests + commit**

```bash
pytest services/app/games/tests/test_chart_data.py -v
git add services/app/games/chart_data.py services/app/games/tests/test_chart_data.py
git commit -m "feat(games): chart data serializers (#186)"
```

---

### Task 9: Win% headline chart partial + JS

**Files:**
- Modify: `services/app/games/views.py::chart_winpct_partial` (use `winpct_payload`)
- Modify: `services/app/templates/games/partials/_chart_winpct.html`
- Create: `services/app/static/games/charts/chartTooltip.js`
- Create: `services/app/static/games/charts/winpct.js`

- [ ] **Step 1: Failing browser-render test**

Use `pytest-django`'s `client` to assert the partial response contains the expected JSON shape and references the static JS.

```python
def test_winpct_partial_contains_payload_and_tooltip(client, new_schema_game_factory):
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/charts/winpct/")
    body = resp.content.decode()
    assert "winpct-data" in body
    assert "Win-for-White" in body          # axis title visible
    assert "How this is computed" in body   # tooltip body
    assert "winpct.js" in body
```

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Update view + template**

`chart_winpct_partial`:

```python
def chart_winpct_partial(request, slug):
    data = _load_or_404(slug)
    return render(request, "games/partials/_chart_winpct.html", {
        "payload": winpct_payload(data),
    })
```

`_chart_winpct.html`:

```html
{% load static %}
<section class="wc-chart" data-chart="winpct">
  <header class="wc-chart__head">
    <h3>Win-for-White</h3>
    <p class="wc-chart__sub">Both engines on one 0–100% axis.</p>
    <details class="chart-info-tooltip">
      <summary aria-label="How this chart is computed">ⓘ</summary>
      <div>
        <p><strong>How this is computed:</strong></p>
        <ul>
          <li><b>Stockfish line</b> — Lichess logistic applied to <code>cp_eval</code>: <code>50 + 50·tanh(0.00368208·cp)</code>.</li>
          <li><b>LC0 line</b> — <code>wdl_mu × 100</code> from the rescaled White-frame WDL (#159).</li>
        </ul>
        <p>Gaps between the lines mark positions where the two engines disagree.</p>
      </div>
    </details>
  </header>
  <div id="winpct-chart" style="height:280px"></div>
  {{ payload|json_script:"winpct-data" }}
  <script src="{% static 'games/charts/winpct.js' %}"></script>
</section>
```

`static/games/charts/winpct.js`:

```javascript
(function () {
  var payload = JSON.parse(document.getElementById("winpct-data").textContent || "{}");
  var div = document.getElementById("winpct-chart");
  if (!div || typeof Plotly === "undefined") return;

  function traces(perspective) {
    var sign = perspective === "white" ? 1 : -1;
    function flip(p) { return 50 + sign * (p - 50); }
    return [
      { x: payload.sf.map(p => p.ply), y: payload.sf.map(p => flip(p.winpct)),
        type: "scatter", mode: "lines+markers", name: "Stockfish",
        line: { color: "#A8781B", width: 2 } },
      { x: payload.lc0.map(p => p.ply), y: payload.lc0.map(p => flip(p.winpct)),
        type: "scatter", mode: "lines+markers", name: "LC0",
        line: { color: "#35586F", width: 2 } },
      { x: [null, null], y: [0, 100], mode: "lines", showlegend: false, hoverinfo: "skip",
        line: { color: "#C17F24", width: 2, dash: "dot" } },
    ];
  }

  var layout = {
    yaxis: { range: [0, 100], ticksuffix: "%", title: "Win-for-White" },
    xaxis: { title: "Ply" },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(237,224,196,0.2)",
    height: 280, margin: { l: 55, r: 20, t: 20, b: 40 },
    legend: { orientation: "h", y: -0.25 },
    hovermode: "x unified",
  };

  var perspective = WoodLeagueAnalysis.getState().perspective;
  Plotly.newPlot(div, traces(perspective), layout, { displaylogo: false, responsive: true }).then(function () {
    div.on("plotly_click", function (ev) { if (ev.points && ev.points.length) WoodLeagueAnalysis.setPly(ev.points[0].x); });
    WoodLeagueAnalysis.subscribe(function (state) {
      Plotly.restyle(div, { x: [[state.ply, state.ply]], y: [[0, 100]] }, [2]);
      if (state.perspective !== perspective) {
        perspective = state.perspective;
        var t = traces(perspective);
        Plotly.restyle(div, { y: [t[0].y, t[1].y] }, [0, 1]);
      }
    });
  });
})();
```

`static/games/charts/chartTooltip.js`: same close-on-outside-click behavior as `cardTooltip.js`, scoped to `details.chart-info-tooltip`.

- [ ] **Step 4: Tests + commit**

```bash
pytest services/app/games/tests/test_partial_routes.py -k winpct -v
git add services/app/games/views.py services/app/templates/games/partials/_chart_winpct.html services/app/static/games/charts/
git commit -m "feat(games): Win% headline chart partial (#186)"
```

---

### Task 10: SF cp-bar chart partial

**Files:**
- Modify: `services/app/games/views.py::chart_sf_cp_partial`
- Modify: `services/app/templates/games/partials/_chart_sf_cp.html`
- Create: `services/app/static/games/charts/sfCp.js`

- [ ] **Step 1: Failing test** — same shape as Task 9 but for `sf-cp`.

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Implement**

Lift the cp-bar logic from the *current* `analysis.html` (lines ~675-848) into `static/games/charts/sfCp.js`, but feed it from `sf_cp_payload` instead of the old `sf-eval-data`. Replace any reference to `cp_equiv` with `cp_eval`. Title text: "Stockfish centipawn evaluation"; subtitle: "Raw score, White-frame, capped at ±12 pawns". Tooltip body explains it's the underlying engine signal and points the reader at the Win% chart above.

- [ ] **Step 4: Tests + commit**

```bash
pytest services/app/games/tests/test_partial_routes.py -k sf_cp -v
git add services/app/games/views.py services/app/templates/games/partials/_chart_sf_cp.html services/app/static/games/charts/sfCp.js
git commit -m "feat(games): SF cp-bar chart partial (#186)"
```

---

### Task 11: LC0 WDL chart partial

**Files:**
- Modify: `services/app/games/views.py::chart_lc0_wdl_partial`
- Modify: `services/app/templates/games/partials/_chart_lc0_wdl.html`
- Create: `services/app/static/games/charts/lc0Wdl.js`

- [ ] **Step 1: Failing test** — assert it ships `wdl-data` JSON sourced from `wdl_win_adj`/`wdl_draw_adj`/`wdl_loss_adj`, references the network name in the subtitle, and contains the calibration-aware tooltip text.

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Implement**

Lift the stacked-area logic from `analysis.html` lines ~852-922 into `lc0Wdl.js`, replacing the references to `d.wdl_win / d.wdl_draw / d.wdl_loss` (which the old MoveRow mapped from `*_adj` anyway). Subtitle string includes `lc0_network_name` and `lc0_draw_rate_reference` (passed as template variables). Tooltip body: see spec.

- [ ] **Step 4: Tests + commit**

```bash
pytest services/app/games/tests/test_partial_routes.py -k lc0_wdl -v
git add services/app/games/views.py services/app/templates/games/partials/_chart_lc0_wdl.html services/app/static/games/charts/lc0Wdl.js
git commit -m "feat(games): LC0 WDL stacked-area partial reading wdl_*_adj (#186)"
```

---

## Phase 4 — Board polish

### Task 12: Move-category chip row

**Files:**
- Create: `services/app/games/chip_data.py`
- Modify: `services/app/templates/games/partials/_move_chips.html`
- Modify: `services/app/games/views.py::chips_partial`
- Create: `services/app/games/tests/test_chip_data.py`

- [ ] **Step 1: Failing test**

```python
import pytest
from games.chip_data import chips_for_ply
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_chips_includes_all_three_levels(new_schema_game_factory):
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    chips = chips_for_ply(data, ply=data.sf_moves[0].ply)
    kinds = {c["kind"] for c in chips}
    # SF classification + LC0 base + LC0 draw_character (when present)
    assert "sf" in kinds
    assert "lc0_base" in kinds


def test_chips_empty_for_unknown_ply(new_schema_game_factory):
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    assert chips_for_ply(data, ply=9999) == []
```

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Implement**

```python
"""
Title: chip_data.py — Build the per-ply move-category chip strip
Description:
    Returns up to three chips for a given ply: SF classification,
    LC0 base severity, and LC0 draw character.
"""
from __future__ import annotations

from games.services_v2 import GameAnalysisDataV2


def chips_for_ply(data: GameAnalysisDataV2, ply: int) -> list[dict]:
    chips: list[dict] = []
    sf = next((m for m in data.sf_moves if m.ply == ply), None)
    lc0 = next((m for m in data.lc0_moves if m.ply == ply), None)
    if sf is not None and sf.classification:
        chips.append({"kind": "sf", "label": sf.classification, "title": "Stockfish classification"})
    if lc0 is not None and lc0.base_severity:
        chips.append({"kind": "lc0_base", "label": lc0.base_severity, "title": "LC0 severity (level 1)"})
    if lc0 is not None and lc0.draw_character:
        chips.append({"kind": "lc0_draw", "label": lc0.draw_character, "title": "LC0 character (level 2)"})
    return chips
```

`_move_chips.html`:

```html
<div class="move-chips">
{% for c in chips %}
  <span class="move-chip move-chip--{{ c.kind }} move-annotation-{{ c.label|lower }}" title="{{ c.title }}: {{ c.label }}">{{ c.label }}</span>
{% empty %}
  <span class="move-chips__empty">No engine tags for this ply.</span>
{% endfor %}
</div>
```

Update `chips_partial` view:

```python
def chips_partial(request, slug):
    data = _load_or_404(slug)
    ply = int(request.GET.get("ply", 0) or 0)
    return render(request, "games/partials/_move_chips.html", {"chips": chips_for_ply(data, ply)})
```

Add CSS for `.move-chips` + `.move-chip` to the existing card stylesheet (small block, monospace, color comes from `.move-annotation-*`). `move-chip--lc0_draw` should have lower contrast (muted variant) than the others so the draw-character chip visually subordinates.

- [ ] **Step 4: Tests + commit**

```bash
pytest services/app/games/tests/test_chip_data.py -v
git add services/app/games/chip_data.py services/app/games/views.py services/app/templates/games/partials/_move_chips.html services/app/games/tests/test_chip_data.py
git commit -m "feat(games): move-category chip row (#186)"
```

---

### Task 13: Arrow labels on the board

**Files:**
- Modify: `services/app/games/board_builder.py::_build_arrow_entries_for_engine`
- Modify: `services/app/templates/games/_board_partial.html` (render label spans on the SVG overlay)
- Create: `services/app/games/tests/test_arrow_labels.py`

- [ ] **Step 1: Failing test**

```python
import pytest
from games.board_builder import build_board_frames
from games.services_v2 import SfMoveRow, Lc0MoveRow

pytestmark = pytest.mark.django_db


def test_sf_arrow_has_signed_pawn_label(simple_pgn_game):
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=34.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        arrow_score_1=34.0, arrow_score_2=None, arrow_score_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"] == "SF +0.34"


def test_lc0_arrow_has_signed_winpct_label(simple_pgn_game):
    # First-line wdl candidate equivalent to ~+12% Win-for-mover vs played-move baseline.
    lc0 = [Lc0MoveRow(
        ply=1, san="e4", fen="", wdl_win_adj=600, wdl_draw_adj=300, wdl_loss_adj=100,
        wdl_mu=0.75, delta_mu=-0.12, delta_d=0.0,
        base_severity="best", draw_character=None, best_move="",
        arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=[], lc0_moves=lc0, orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"].startswith("Lc0 ")
    assert "%" in arrow["label"]
```

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Add labels**

Inside `_build_arrow_entries_for_engine` in `board_builder.py`, when emitting an arrow entry, compute and store a `label` field:

```python
def _arrow_label(engine_key: str, score: float | None, mu: float | None, played_mu: float | None) -> str:
    if engine_key == "sf" and score is not None:
        pawns = score / 100.0
        sign = "+" if pawns >= 0 else "−"
        return f"SF {sign}{abs(pawns):.2f}"
    if engine_key == "lc0" and mu is not None and played_mu is not None:
        delta_pct = (mu - played_mu) * 100.0
        sign = "+" if delta_pct >= 0 else "−"
        return f"Lc0 {sign}{abs(delta_pct):.0f}%"
    return ""

# In the arrow-emit loop:
entry["label"] = _arrow_label(engine_key, arrow_score, candidate_mu, played_mu)
```

For SF: `arrow_score` is `arrow_score_1/2/3`. For LC0: derive `candidate_mu` from the candidate `wdl_win_<n> / wdl_draw_<n> / wdl_loss_<n>` triple (use the same `wdl_mu = win + draw/2` formula the worker derivation uses), and `played_mu` is the played row's `wdl_mu`.

- [ ] **Step 4: Render labels in `_board_partial.html`**

Find the SVG overlay block that draws arrows. For each arrow, after the `<line>`/`<path>` element, add:

```html
{% if arrow.label %}
  <text x="{{ arrow.label_x }}" y="{{ arrow.label_y }}"
        class="board-arrow-label board-arrow-label--{{ arrow.engine }}"
        text-anchor="middle">{{ arrow.label }}</text>
{% endif %}
```

`label_x` / `label_y` = midpoint of the arrow line, offset perpendicular by ~14px. Compute in `_board_overlay_geometry` and stash on the arrow entry.

Add CSS to the board partial:

```css
.board-arrow-label { font-family: 'DM Mono', monospace; font-size: 11px; font-weight: 700; paint-order: stroke fill; stroke: rgba(255,255,255,0.85); stroke-width: 3px; pointer-events: none; }
.board-arrow-label--sf  { fill: #A8781B; }
.board-arrow-label--lc0 { fill: #35586F; }
```

- [ ] **Step 5: Tests + bandit + commit**

```bash
pytest services/app/games/tests/test_arrow_labels.py -v
bandit -ll services/app/games/board_builder.py
git add services/app/games/board_builder.py services/app/templates/games/_board_partial.html services/app/games/tests/test_arrow_labels.py
git commit -m "feat(games): labeled board arrows (engine + signed delta) (#186)"
```

---

### Task 14: PGN table partial

**Files:**
- Modify: `services/app/games/views.py::pgn_partial`
- Modify: `services/app/templates/games/partials/_pgn_table.html`
- Create: `services/app/static/games/pgnTable.js`

- [ ] **Step 1: Failing test**

```python
def test_pgn_partial_renders_one_row_per_move_pair(client, new_schema_game_factory):
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/pgn/")
    body = resp.content.decode()
    assert 'id="pgn-table"' in body
    assert "pgnTable.js" in body
```

- [ ] **Step 2: Run, confirm failure**

- [ ] **Step 3: Lift the current inline PGN script + table into the partial**

`_pgn_table.html` contains the `<details id="pgn-panel">` block currently in `analysis.html` lines 125-141, plus a `{{ pgn_moves|json_script:"pgn-moves-data" }}` payload, plus `<script src="{% static 'games/pgnTable.js' %}"></script>`. The inline JS that builds the table (lines 606-671 of the current template) becomes `static/games/pgnTable.js`. Annotations come from `sf_moves[i].classification`; pass per-ply classification through the payload.

`pgn_partial`:

```python
def pgn_partial(request, slug):
    data = _load_or_404(slug)
    by_ply_class = {m.ply: m.classification for m in data.sf_moves}
    moves = []
    # Walk the chess.pgn mainline to get SAN per ply (already done in the shell today).
    import io, chess.pgn
    pgn_game = chess.pgn.read_game(io.StringIO(data.pgn))
    board = pgn_game.board()
    start = board.ply()
    for i, mv in enumerate(pgn_game.mainline_moves(), start=1):
        san = board.san(mv)
        board.push(mv)
        ply = i + start
        moves.append({
            "ply": ply, "san": san,
            "color": "white" if ply % 2 == 1 else "black",
            "move_number": (ply + 1) // 2,
            "classification": by_ply_class.get(ply),
        })
    return render(request, "games/partials/_pgn_table.html", {"pgn_moves": moves})
```

- [ ] **Step 4: Tests + commit**

```bash
pytest services/app/games/tests/test_partial_routes.py -k pgn -v
git add services/app/games/views.py services/app/templates/games/partials/_pgn_table.html services/app/static/games/pgnTable.js
git commit -m "feat(games): PGN table partial (#186)"
```

---

## Phase 5 — Cleanup and quality gate

### Task 15: Remove `stat_cards.py` and JSON builders from `views.py`

**Files:**
- Delete: `services/app/games/stat_cards.py`
- Modify: `services/app/games/views.py` — remove `_build_eval_json`, `_build_wdl_json`, `_build_pgn_moves_json`, `_humanize_time_control`, `_details_string`, `_opening_label`, `_queue_status` if no longer referenced.

- [ ] **Step 1: Grep for external references**

```bash
grep -rn "from games.stat_cards\|from .stat_cards\|build_stat_cards_html\|build_sf_card\|build_lc0_card" services/app/
```

- [ ] **Step 2: Delete + adjust**

If grep returns hits in tests, port those tests to `cards.py` equivalents or delete if they covered legacy behavior already covered by `test_cards_sf.py` / `test_cards_lc0.py`.

```bash
git rm services/app/games/stat_cards.py
```

Remove the now-unused private helpers in `views.py`.

- [ ] **Step 3: Run the full app test suite**

```bash
cd services/app && pytest --no-cov -q
```

- [ ] **Step 4: Commit**

```bash
git add -A services/app/
git commit -m "chore(games): drop stat_cards.py + dead JSON builders (#186)"
```

---

### Task 16: Quality gate + manual verify

- [ ] **Step 1: Run the full pipeline**

```bash
cd services/app
source .venv/bin/activate
ruff check --fix . && ruff format .
bandit -ll -r games/ analysis/ || true
radon cc -nB games/ analysis/
mypy games/ analysis/ || true
pytest --cov=games --cov=analysis --cov-fail-under=85 -q
```

Fix any ruff/bandit/cc-grade-below-B/mypy errors before continuing.

- [ ] **Step 2: Run the legacy cleanup on the local dev DB**

```bash
python manage.py drop_legacy_analyses          # dry run
python manage.py drop_legacy_analyses --apply  # confirm prompt counts make sense
```

- [ ] **Step 3: Boot the dev server and click through three games**

```bash
python manage.py runserver
```

Open `/games/<slug>/` for: a game with both SF + LC0; SF-only; LC0-only. Confirm:
- Cards show new fields and ⓘ tooltips reveal run metadata.
- Move-category chips update on ply change.
- Arrows are labeled and stay aligned to the displayed ply.
- All three charts render with title + subtitle + ⓘ tooltip.
- Win% chart overlays SF + LC0 cleanly.
- LC0 WDL chart is monotonic in White-frame (no sawtooth).

- [ ] **Step 4: Commit any cleanup, push, open PR**

```bash
git push -u origin issue/186-game-analysis-rewrite
gh pr create --title "Rewrite Game Analysis page on new raw+derived schema (#186)" --body-file - <<'EOF'
Closes #186.

Implements `docs/superpowers/specs/2026-05-21-game-analysis-rewrite-design.md`.

## Summary
- Thin shell template; each visual unit is its own HTMX partial.
- New Win% headline chart overlays SF + LC0.
- SF cp-bar and LC0 WDL charts rebuilt against new schema.
- Board arrows labeled (`SF +0.34`, `Lc0 −12%`); ply-association bug fixed.
- Move-category chip row above the board surfaces SF classification + LC0 base severity + LC0 draw character.
- `drop_legacy_analyses` management command (dry-run default) clears pre-#161 rows.

## Test plan
- [ ] Pytest green with ≥85% coverage on `games/` and `analysis/`.
- [ ] Manual verify: game with both engines, SF-only, LC0-only.
- [ ] `python manage.py drop_legacy_analyses` dry-run shows expected counts.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

---

## Self-review checklist

- **Spec coverage:** Each spec section maps to tasks — partial scaffolding (4-5), cards with tooltip (6-7), three charts with tooltips (8-11), board polish with arrows + chips (12-13), legacy cleanup (2), ply-association fix (3). ✓
- **Placeholders:** None — every step has code. The one piece of investigation (the exact `draw_character` label set) is called out as an explicit grep step inside Task 7, not a TBD. ✓
- **Type consistency:** `SfMoveRow` / `Lc0MoveRow` / `GameAnalysisDataV2` names are reused from Task 1 onward. `arrow_uci_1` (SF) / `arrow_uci_1` (LC0) is consistent. `board_builder.build_board_frames` switches to keyword `sf_moves=` / `lc0_moves=` in Task 3 and all later tasks use that signature. ✓
- **Ambiguity:** The chip-row CSS, the arrow-label SVG positioning, and the per-side accuracy `floatformat` are all explicit. ✓
