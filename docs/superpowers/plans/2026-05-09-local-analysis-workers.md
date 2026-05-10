# Local Analysis Workers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Agents must use vexp `run_pipeline` before every task — do NOT grep/glob the codebase.**

**Goal:** Build a standalone Python CLI (`wood-league-worker`) that club members run at home to claim, analyse with Stockfish or Lc0, and submit chess game results to the Wood League API.

**Architecture:** Fresh implementation using `python-chess` for engine communication — no dependency on the internal `stockfish_pipeline` or `lc0_worker` packages, so the tool can be published and installed standalone via pip. All analysis math is implemented strictly per `services/app/documentation/analysis-math.md` (which intentionally diverges from the legacy RunPod implementation in several ways — see "Math spec deltas" below). The `WorkerClient` from `packages/shared` is reused for HTTP calls.

### Math spec deltas (vs legacy RunPod workers)

These are the points where this implementation must follow `analysis-math.md` and **not** copy the legacy code:

1. **Win% formula** — the canonical form is `Win% = 100 / (1 + exp(-0.00368208 · cp))` (with `cp` from the mover's perspective).
2. **Move accuracy** — `103.1668… · exp(-0.04354… · drop) - 3.16692…`. There is **no `+ 1` constant** at the end. Result clamped to `[0, 100]`.
3. **Mate scores are flat ±10000** — mate-in-1 and mate-in-10 both yield 10000, so two mate-scoring moves give CPL = 0. Distinguishing them is the classification layer's job, not the CPL formula's.
4. **CPL sign convention is explicit per side** — for Black, the cp value must be negated to reach the mover's perspective before subtracting (python-chess `score.pov(mover)` does this for us).
5. **Game-accuracy weighted mean uses windowed Win%-std-dev weights**, window size `k = 8`, centered on each move, truncated at game boundaries. **Not** a per-move-distance-from-100 weight (that was my earlier draft and is wrong).
6. **ACPL is per-player** — `n` is the player's own move count, not the total game ply count.
7. **Capture / sacrifice = Static Exchange Evaluation (SEE)** — a move qualifies only if SEE on the destination square is *negative* for the mover (they end up with material loss after the full exchange). Pure equal/winning captures do **not** qualify. This requires a real SEE pass, not a piece-value comparison.
8. **Lc0 Q → cp constants** — `cp_equiv = 111.714640912 · tan(1.5620688421 · Q)`, with `Q` clamped away from ±1.
9. **Classifications applied in declared order; first match wins** — implementations must be a top-down `if`/`elif` ladder, not a bag of independent rules.

**Tech Stack:** Python 3.11+, `typer` (CLI), `rich` (progress/display), `questionary` (interactive menus), `python-chess` (Stockfish + lc0 UCI), `httpx` (HTTP, via WorkerClient), `platformdirs` (cross-platform config paths)

---

## File Map

```
services/local_worker/
├── local_worker/
│   ├── __init__.py
│   ├── cli.py              # Typer app — all commands
│   ├── config.py           # Persistent settings (platformdirs + JSON)
│   ├── detector.py         # Engine binary detection + hardware sensing
│   ├── display.py          # Rich Live progress bars + stats panel
│   ├── loop.py             # Claim → analyse → submit worker loop + stats
│   └── analysis/
│       ├── __init__.py
│       ├── math.py         # Win%, accuracy, CPL, classification formulas
│       ├── models.py       # Result dataclasses (MoveResult, GameResult)
│       ├── stockfish.py    # Stockfish UCI analysis → API payload
│       └── lc0.py          # Lc0 UCI analysis → API payload
├── tests/
│   ├── __init__.py
│   ├── test_math.py
│   ├── test_config.py
│   ├── test_detector.py
│   └── test_loop.py
├── pyproject.toml
└── README.md
```

---

## Task 1: Project Scaffolding

**Files:**
- Create: `services/local_worker/pyproject.toml`
- Create: `services/local_worker/local_worker/__init__.py`
- Create: `services/local_worker/local_worker/analysis/__init__.py`
- Create: `services/local_worker/tests/__init__.py`
- Create: `services/local_worker/README.md`

- [ ] **Step 1: Create directory structure**

```bash
cd services/local_worker
mkdir -p local_worker/analysis tests
touch local_worker/__init__.py local_worker/analysis/__init__.py tests/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "wood-league-worker"
version = "0.1.0"
description = "Local analysis worker for the Wood League chess platform"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "rich>=13",
    "questionary>=2.0",
    "python-chess>=1.11",
    "httpx>=0.27",
    "platformdirs>=4",
    "wood-league-shared @ file://../../packages/shared",
]

[project.scripts]
wood-league-worker = "local_worker.cli:app"

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov", "ruff", "mypy"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 100
```

- [ ] **Step 3: Write `local_worker/__init__.py`**

```python
"""
Title: __init__.py — Wood League local analysis worker
Description:
    Standalone CLI tool for club members to run Stockfish/Lc0 analysis
    locally and submit results to the Wood League API.

Changelog:
    2026-05-09: Initial creation
"""
```

- [ ] **Step 4: Install in dev mode and verify imports**

```bash
cd services/local_worker
pip install -e ".[dev]"
python -c "import local_worker; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add services/local_worker/
git commit -m "feat(local-worker): scaffold project structure and pyproject.toml"
```

---

## Task 2: Persistent Config

**Files:**
- Create: `services/local_worker/local_worker/config.py`
- Create: `services/local_worker/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
"""
Title: test_config.py — Tests for persistent configuration
Description: Verifies load/save/defaults for the Settings object.
Changelog:
    2026-05-09: Initial creation
"""
import json
import os
from pathlib import Path

import pytest

from local_worker.config import Settings, load_settings, save_settings


def test_defaults_when_no_file(tmp_path):
    cfg_file = tmp_path / "settings.json"
    s = load_settings(cfg_file)
    assert s.api_url == ""
    assert s.api_key == ""
    assert s.stockfish_path == ""
    assert s.lc0_path == ""
    assert s.default_batch_size == 5
    assert s.stockfish_depth == 20
    assert s.stockfish_threads == 4
    assert s.stockfish_hash_mb == 512
    assert s.lc0_nodes == 10000
    assert s.default_engines == ["stockfish"]
    assert s.syzygy_path == ""


def test_round_trip(tmp_path):
    cfg_file = tmp_path / "settings.json"
    s = Settings(api_url="https://example.com", api_key="mykey", stockfish_depth=25)
    save_settings(s, cfg_file)
    loaded = load_settings(cfg_file)
    assert loaded.api_url == "https://example.com"
    assert loaded.api_key == "mykey"
    assert loaded.stockfish_depth == 25


def test_is_configured_false_without_key(tmp_path):
    cfg_file = tmp_path / "settings.json"
    s = load_settings(cfg_file)
    assert not s.is_configured()


def test_is_configured_true_with_url_and_key(tmp_path):
    cfg_file = tmp_path / "settings.json"
    s = Settings(api_url="https://example.com", api_key="mykey")
    save_settings(s, cfg_file)
    loaded = load_settings(cfg_file)
    assert loaded.is_configured()
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd services/local_worker
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'local_worker.config'`

- [ ] **Step 3: Implement `local_worker/config.py`**

```python
"""
Title: config.py — Persistent worker configuration
Description:
    Loads and saves worker settings to a JSON file in the platform-standard
    user data directory. Provides sensible defaults for all settings.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import platformdirs


def _default_config_path() -> Path:
    """Return the platform-appropriate path for the settings file."""
    data_dir = Path(platformdirs.user_data_dir("wood-league-worker", "WoodLeague"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "settings.json"


@dataclass
class Settings:
    """All persistent worker settings."""

    api_url: str = ""
    api_key: str = ""
    worker_id: str = ""
    stockfish_path: str = ""
    lc0_path: str = ""
    syzygy_path: str = ""
    lc0_backend: str = ""
    default_engines: list[str] = field(default_factory=lambda: ["stockfish"])
    default_batch_size: int = 5
    batch_time_minutes: Optional[int] = None
    stockfish_depth: int = 20
    stockfish_threads: int = 4
    stockfish_hash_mb: int = 512
    lc0_nodes: int = 10000

    def is_configured(self) -> bool:
        """Return True if the minimum required settings are present."""
        return bool(self.api_url and self.api_key)


def load_settings(path: Optional[Path] = None) -> Settings:
    """Load settings from disk, returning defaults if the file does not exist.

    Args:
        path: Path to the JSON settings file. Defaults to platform data dir.

    Returns:
        A Settings instance populated from the file (or all defaults).
    """
    cfg_path = path or _default_config_path()
    if not cfg_path.exists():
        return Settings()
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    known = {f.name for f in Settings.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in known}
    return Settings(**filtered)


def save_settings(settings: Settings, path: Optional[Path] = None) -> None:
    """Persist settings to disk as JSON.

    Args:
        settings: The Settings instance to save.
        path: Path to write. Defaults to platform data dir.
    """
    cfg_path = path or _default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add local_worker/config.py tests/test_config.py
git commit -m "feat(local-worker): persistent settings with platformdirs"
```

---

## Task 3: Analysis Math Module

This module implements every formula in `services/app/documentation/analysis-math.md` exactly as specified there. Re-read that doc before starting; do **not** crib formulas from the legacy `stockfish_pipeline` or `lc0_worker` packages — they differ from this spec.

**Files:**
- Create: `services/local_worker/local_worker/analysis/models.py`
- Create: `services/local_worker/local_worker/analysis/math.py`
- Create: `services/local_worker/local_worker/analysis/see.py`
- Create: `services/local_worker/tests/test_math.py`
- Create: `services/local_worker/tests/test_see.py`

- [ ] **Step 1: Write `analysis/models.py`**

```python
"""
Title: models.py — Analysis result dataclasses
Description:
    Dataclasses representing per-move and per-game analysis results for both
    Stockfish and Lc0 engines.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StockfishMoveResult:
    """Per-move result from Stockfish analysis."""

    ply: int
    san: str
    fen: str
    cp_eval: int
    cpl: int
    best_move: str
    classification: str


@dataclass
class StockfishGameResult:
    """Aggregated Stockfish analysis result for a full game."""

    engine_depth: int
    white_accuracy: float
    black_accuracy: float
    white_acpl: float
    black_acpl: float
    white_blunders: int
    white_mistakes: int
    white_inaccuracies: int
    black_blunders: int
    black_mistakes: int
    black_inaccuracies: int
    moves: list[StockfishMoveResult] = field(default_factory=list)


@dataclass
class Lc0MoveResult:
    """Per-move result from Lc0 analysis."""

    ply: int
    san: str
    fen: str
    wdl_win: int
    wdl_draw: int
    wdl_loss: int
    cp_equiv: Optional[int]
    best_move: str
    arrow_uci: str
    arrow_uci_2: str
    arrow_uci_3: str
    arrow_score_1: Optional[float]
    arrow_score_2: Optional[float]
    arrow_score_3: Optional[float]
    move_win_delta: float
    classification: str
    pv_san_1: Optional[str]
    pv_san_2: Optional[str]
    pv_san_3: Optional[str]


@dataclass
class Lc0GameResult:
    """Aggregated Lc0 analysis result for a full game."""

    engine_nodes: int
    network_name: str
    white_win_prob: float
    white_draw_prob: float
    white_loss_prob: float
    black_win_prob: float
    black_draw_prob: float
    black_loss_prob: float
    white_blunders: int
    white_mistakes: int
    white_inaccuracies: int
    black_blunders: int
    black_mistakes: int
    black_inaccuracies: int
    moves: list[Lc0MoveResult] = field(default_factory=list)
```

- [ ] **Step 2: Write the failing tests**

These tests are written against the formulas in `analysis-math.md`. Numeric expectations match the spec exactly; do not loosen them to match a different implementation.

```python
# tests/test_math.py
"""
Title: test_math.py — Tests for analysis math formulas
Description:
    Verifies that win%, accuracy, CPL classification, game accuracy aggregation,
    and Q→cp conversion match analysis-math.md exactly.

Changelog:
    2026-05-09: Initial creation
"""
import math
import pytest
from local_worker.analysis.math import (
    win_pct,
    move_accuracy,
    game_accuracy,
    classify_stockfish_move,
    classify_lc0_move,
    cp_equiv_from_q,
    cpl_from_evals,
)


class TestWinPct:
    def test_zero_cp_is_fifty(self):
        # Win% = 100 / (1 + exp(0)) = 50 exactly
        assert win_pct(0) == pytest.approx(50.0, abs=1e-9)

    def test_positive_cp_above_fifty(self):
        assert win_pct(100) > 50
        assert win_pct(100) < 100

    def test_negative_cp_below_fifty(self):
        assert win_pct(-100) < 50
        assert win_pct(-100) > 0

    def test_symmetric(self):
        # win_pct(x) + win_pct(-x) == 100 by the sigmoid identity
        assert win_pct(200) + win_pct(-200) == pytest.approx(100.0, abs=1e-9)

    def test_mate_score_saturates(self):
        assert win_pct(10000) > 99.9
        assert win_pct(-10000) < 0.1

    def test_canonical_value(self):
        # Spot-check against the closed-form value at cp=300
        expected = 100.0 / (1.0 + math.exp(-0.00368208 * 300))
        assert win_pct(300) == pytest.approx(expected, abs=1e-9)


class TestMoveAccuracy:
    def test_perfect_move_no_drop(self):
        # drop=0 → 103.1668... - 3.1669... = 99.99989... → clamped/returned just under 100
        acc = move_accuracy(60.0, 60.0)
        assert acc == pytest.approx(99.999916, abs=0.001)

    def test_blunder_is_low(self):
        acc = move_accuracy(70.0, 20.0)
        assert acc < 20

    def test_clamped_to_zero(self):
        acc = move_accuracy(95.0, 0.0)
        assert acc >= 0.0

    def test_clamped_to_hundred(self):
        # Negative drop (mover got better) → formula returns >100, must clamp
        acc = move_accuracy(50.0, 80.0)
        assert acc <= 100.0


class TestCplFromEvals:
    def test_white_perspective(self):
        # White goes from +50 to +30 → CPL 20 (no negation)
        assert cpl_from_evals(50, 30, mover_is_white=True) == 20

    def test_black_perspective_negates(self):
        # Black goes from cp=-50 (good for Black) to cp=-30 (worse for Black).
        # mover-perspective: before=+50, after=+30 → CPL 20
        assert cpl_from_evals(-50, -30, mover_is_white=False) == 20

    def test_clamped_at_zero(self):
        # Mover *gained* cp → CPL clamped to 0
        assert cpl_from_evals(20, 60, mover_is_white=True) == 0

    def test_two_mate_scores_zero_cpl(self):
        # mate-in-1 and mate-in-10 both = 10000; CPL must be 0
        assert cpl_from_evals(10000, 10000, mover_is_white=True) == 0


class TestGameAccuracyWindowed:
    def test_all_perfect_is_near_hundred(self):
        # All-100 accuracies → both means are 100 → average is 100
        result = game_accuracy([100.0] * 30, win_pcts=[50.0] * 30)
        assert result == pytest.approx(100.0, abs=0.01)

    def test_empty_is_zero(self):
        assert game_accuracy([], win_pcts=[]) == 0.0

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            game_accuracy([100.0, 90.0], win_pcts=[50.0])

    def test_volatile_window_increases_weight(self):
        # A swing-heavy section should pull the weighted mean toward those moves
        accs = [100.0] * 5 + [40.0] * 3 + [100.0] * 5
        win_pcts = [50.0] * 5 + [80.0, 30.0, 75.0] + [50.0] * 5  # high std-dev in middle
        result = game_accuracy(accs, win_pcts=win_pcts)
        assert 0 < result < 100

    def test_harmonic_penalises_severe_blunders(self):
        # One catastrophic blunder should drag the harmonic mean low
        accs = [100.0] * 10 + [0.5]
        win_pcts = [50.0] * 11
        result = game_accuracy(accs, win_pcts=win_pcts)
        # Harmonic mean of values including one ~0 will be small; full result well below 100
        assert result < 50


class TestClassifyStockfish:
    # Order: Brilliant > Great > Best > Excellent > Inaccuracy > Mistake > Blunder
    # First match wins.
    def test_best_move(self):
        assert classify_stockfish_move(
            cpl=0, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Best"

    def test_excellent(self):
        assert classify_stockfish_move(
            cpl=30, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Excellent"

    def test_inaccuracy_lower_bound(self):
        assert classify_stockfish_move(
            cpl=50, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Inaccuracy"

    def test_mistake_lower_bound(self):
        assert classify_stockfish_move(
            cpl=100, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Mistake"

    def test_blunder_lower_bound(self):
        assert classify_stockfish_move(
            cpl=300, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Blunder"

    def test_great_move(self):
        assert classify_stockfish_move(
            cpl=5, second_best_gap=90, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Great"

    def test_brilliant_requires_all_conditions(self):
        assert classify_stockfish_move(
            cpl=5, second_best_gap=160, mover_win_pct=65, is_capture_or_sacrifice=True
        ) == "Brilliant"

    def test_brilliant_blocked_by_high_winpct(self):
        result = classify_stockfish_move(
            cpl=5, second_best_gap=160, mover_win_pct=80, is_capture_or_sacrifice=True
        )
        assert result == "Great"  # second_best_gap=160 also satisfies Great threshold

    def test_brilliant_blocked_without_capture(self):
        result = classify_stockfish_move(
            cpl=5, second_best_gap=160, mover_win_pct=65, is_capture_or_sacrifice=False
        )
        assert result == "Great"


class TestClassifyLc0:
    def test_best(self):
        assert classify_lc0_move(
            delta_win_pct=0.5, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Best"

    def test_excellent(self):
        # 1% < Δ < 2% — strictly greater than 1%
        assert classify_lc0_move(
            delta_win_pct=1.5, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Excellent"

    def test_inaccuracy_lower_bound(self):
        assert classify_lc0_move(
            delta_win_pct=2.0, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Inaccuracy"

    def test_mistake_lower_bound(self):
        assert classify_lc0_move(
            delta_win_pct=5.0, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Mistake"

    def test_blunder_lower_bound(self):
        assert classify_lc0_move(
            delta_win_pct=10.0, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Blunder"

    def test_great(self):
        assert classify_lc0_move(
            delta_win_pct=0.5, second_best_gap=7.0, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Great"

    def test_brilliant(self):
        assert classify_lc0_move(
            delta_win_pct=0.5, second_best_gap=11.0, mover_win_pct=65, is_capture_or_sacrifice=True
        ) == "Brilliant"


class TestCpEquiv:
    def test_zero_q_is_zero(self):
        assert cp_equiv_from_q(0.0) == 0

    def test_positive_q_positive_cp(self):
        assert cp_equiv_from_q(0.5) > 0

    def test_negative_q_negative_cp(self):
        assert cp_equiv_from_q(-0.5) < 0

    def test_symmetric(self):
        assert cp_equiv_from_q(0.4) == -cp_equiv_from_q(-0.4)

    def test_clamped_near_one(self):
        # tan(1.5620688421 · 1) blows up → must clamp Q before tan()
        assert cp_equiv_from_q(0.99999999) > 0  # finite, not NaN/inf
        assert cp_equiv_from_q(-0.99999999) < 0

    def test_canonical_value(self):
        # Spot-check against closed-form
        q = 0.3
        expected = round(111.714640912 * math.tan(1.5620688421 * q))
        assert cp_equiv_from_q(q) == expected
```

- [ ] **Step 3: Run to verify they fail**

```bash
pytest tests/test_math.py -v
```

Expected: `ModuleNotFoundError: No module named 'local_worker.analysis.math'`

- [ ] **Step 4: Implement `analysis/math.py`**

```python
"""
Title: math.py — Chess analysis math formulas
Description:
    Implements every formula in services/app/documentation/analysis-math.md:
    Win% (sigmoid), per-move accuracy, mover-perspective CPL, windowed-stddev
    weighted game accuracy, harmonic-mean game accuracy, Stockfish CPL-based
    classification, Lc0 ΔWin%-based classification, and Lc0 Q→cp conversion.

    Numeric constants and ordering match the spec exactly. Do not change them
    to match a different implementation.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

MATE_SCORE = 10000

# Stockfish CPL classification thresholds (analysis-math.md)
_SF_EXCELLENT_CPL = 10
_SF_INACCURACY_CPL = 50
_SF_MISTAKE_CPL = 100
_SF_BLUNDER_CPL = 300
_SF_BRILLIANT_GAP = 150
_SF_GREAT_GAP = 80
_SF_BRILLIANT_WINPCT_CEILING = 70.0

# Lc0 ΔWin% classification thresholds (analysis-math.md)
_LC0_EXCELLENT_MIN = 1.0   # exclusive
_LC0_INACCURACY_MIN = 2.0  # inclusive
_LC0_MISTAKE_MIN = 5.0     # inclusive
_LC0_BLUNDER_MIN = 10.0    # inclusive
_LC0_BRILLIANT_GAP = 10.0
_LC0_GREAT_GAP = 6.0
_LC0_BRILLIANT_WINPCT_CEILING = 70.0

# Game-accuracy aggregation
_WINDOW_SIZE = 8
_HARMONIC_EPSILON = 0.001

# Lc0 Q → cp conversion constants (precise values from spec)
_Q_CP_SCALE = 111.714640912
_Q_CP_INNER = 1.5620688421


def win_pct(cp: float) -> float:
    """Win% from cp evaluation, using the Lichess sigmoid.

    Args:
        cp: Centipawn evaluation from the mover's perspective. Mate scores
            are passed in as ±MATE_SCORE (10000) — the sigmoid saturates
            naturally at those values.

    Returns:
        Win probability as a percentage (0–100).
    """
    return 100.0 / (1.0 + math.exp(-0.00368208 * cp))


def move_accuracy(win_pct_before: float, win_pct_after: float) -> float:
    """Per-move accuracy from the mover's Win% drop.

    Formula (analysis-math.md):
        Accuracy% = 103.1668100711649 · exp(-0.04354415386753951 · drop)
                    - 3.166924740191411
    Result clamped to [0, 100]. There is *no* trailing `+ 1` term — that
    was present in the legacy implementation and has been removed.

    Args:
        win_pct_before: Win% for the mover before the move (0–100).
        win_pct_after: Win% for the mover after the move (0–100).

    Returns:
        Accuracy in [0, 100].
    """
    drop = win_pct_before - win_pct_after
    acc = (
        103.1668100711649 * math.exp(-0.04354415386753951 * drop)
        - 3.166924740191411
    )
    return max(0.0, min(100.0, acc))


def cpl_from_evals(eval_before_cp: int, eval_after_cp: int, *, mover_is_white: bool) -> int:
    """Compute CPL from before/after cp evaluations expressed in White's frame.

    Stockfish reports cp from White's perspective. To compute CPL from the
    mover's perspective, Black's evaluations must be negated first.

    Args:
        eval_before_cp: cp evaluation before the move, White's perspective.
        eval_after_cp: cp evaluation after the move, White's perspective.
        mover_is_white: True if the side to move was White.

    Returns:
        CPL as a non-negative integer (clamped at 0 — the mover is never
        credited with negative loss).
    """
    if mover_is_white:
        before_mover = eval_before_cp
        after_mover = eval_after_cp
    else:
        before_mover = -eval_before_cp
        after_mover = -eval_after_cp
    return max(0, before_mover - after_mover)


def _windowed_std(values: list[float], center: int, window: int) -> float:
    """Standard deviation of `values` in a window of size `window` centered on
    index `center`, truncated at sequence boundaries.

    Args:
        values: Numeric sequence.
        center: Center index.
        window: Window size (e.g., 8).

    Returns:
        Population standard deviation. Returns 0.0 if the window contains
        fewer than 2 samples.
    """
    half = window // 2
    lo = max(0, center - half)
    hi = min(len(values), center + half + (window % 2))
    sample = values[lo:hi]
    if len(sample) < 2:
        return 0.0
    return statistics.pstdev(sample)


def game_accuracy(move_accuracies: list[float], *, win_pcts: list[float]) -> float:
    """Game accuracy = (windowed-stddev weighted mean + harmonic mean) / 2.

    Both inputs must be **per-player** sequences (only the moves made by the
    player being evaluated, in order). They must be the same length.

    The weighted mean weights each move by the population standard deviation
    of Win% across a window of size 8 centered on that move (truncated at
    boundaries) — moves played in volatile positions count more.

    The harmonic mean clamps each accuracy at ε=0.001 to avoid division by
    zero and to penalize severe blunders.

    Args:
        move_accuracies: Per-player accuracy values, one per move (0–100 each).
        win_pcts: Per-player Win% values aligned with move_accuracies — these
            are the Win% values *before* each of the player's moves, used to
            compute volatility weights.

    Returns:
        Game accuracy in [0, 100]. Returns 0.0 if the list is empty.

    Raises:
        ValueError: If the two input lists differ in length.
    """
    if not move_accuracies:
        return 0.0
    if len(move_accuracies) != len(win_pcts):
        raise ValueError(
            f"move_accuracies (len={len(move_accuracies)}) and "
            f"win_pcts (len={len(win_pcts)}) must have equal length"
        )
    n = len(move_accuracies)

    harmonic = n / sum(1.0 / max(a, _HARMONIC_EPSILON) for a in move_accuracies)

    weights = [_windowed_std(win_pcts, i, _WINDOW_SIZE) for i in range(n)]
    total_weight = sum(weights)
    if total_weight <= 0.0:
        # Degenerate case (e.g., constant Win%) — fall back to arithmetic mean
        weighted_mean = sum(move_accuracies) / n
    else:
        weighted_mean = sum(w * a for w, a in zip(weights, move_accuracies)) / total_weight

    return max(0.0, min(100.0, (weighted_mean + harmonic) / 2.0))


def classify_stockfish_move(
    *,
    cpl: int,
    second_best_gap: Optional[int],
    mover_win_pct: float,
    is_capture_or_sacrifice: bool,
) -> str:
    """Classify a Stockfish move per analysis-math.md (first match wins).

    Order: Brilliant → Great → Best → Excellent → Inaccuracy → Mistake → Blunder.
    `is_capture_or_sacrifice` must be the SEE-based determination (see
    `analysis/see.py`).

    Args:
        cpl: Centipawn loss (≥0) for this move from the mover's perspective.
        second_best_gap: cp gap between the best and second-best legal moves
            from the position before the move. None if MultiPV ≥ 2 was not
            available.
        mover_win_pct: Win% for the mover before the move (0–100).
        is_capture_or_sacrifice: True iff SEE on the destination square is
            negative for the mover.

    Returns:
        One of: Brilliant, Great, Best, Excellent, Inaccuracy, Mistake, Blunder.
    """
    if cpl < _SF_EXCELLENT_CPL:
        if (
            second_best_gap is not None
            and second_best_gap >= _SF_BRILLIANT_GAP
            and mover_win_pct < _SF_BRILLIANT_WINPCT_CEILING
            and is_capture_or_sacrifice
        ):
            return "Brilliant"
        if second_best_gap is not None and second_best_gap >= _SF_GREAT_GAP:
            return "Great"
        return "Best"
    if cpl < _SF_INACCURACY_CPL:
        return "Excellent"
    if cpl < _SF_MISTAKE_CPL:
        return "Inaccuracy"
    if cpl < _SF_BLUNDER_CPL:
        return "Mistake"
    return "Blunder"


def classify_lc0_move(
    *,
    delta_win_pct: float,
    second_best_gap: Optional[float],
    mover_win_pct: float,
    is_capture_or_sacrifice: bool,
) -> str:
    """Classify an Lc0 move per analysis-math.md (first match wins).

    Order: Brilliant → Great → Best → Excellent → Inaccuracy → Mistake → Blunder.

    Args:
        delta_win_pct: Win% loss from the mover's perspective (≥0).
        second_best_gap: Win% gap between best and second-best move from the
            position before the move. None if unavailable.
        mover_win_pct: Win% for the mover before the move (0–100).
        is_capture_or_sacrifice: True iff SEE on the destination square is
            negative for the mover.

    Returns:
        One of: Brilliant, Great, Best, Excellent, Inaccuracy, Mistake, Blunder.
    """
    if delta_win_pct <= _LC0_EXCELLENT_MIN:  # Δ ≤ 1%
        if (
            second_best_gap is not None
            and second_best_gap >= _LC0_BRILLIANT_GAP
            and mover_win_pct < _LC0_BRILLIANT_WINPCT_CEILING
            and is_capture_or_sacrifice
        ):
            return "Brilliant"
        if second_best_gap is not None and second_best_gap >= _LC0_GREAT_GAP:
            return "Great"
        return "Best"
    if delta_win_pct < _LC0_INACCURACY_MIN:   # 1% < Δ < 2%
        return "Excellent"
    if delta_win_pct < _LC0_MISTAKE_MIN:      # 2% ≤ Δ < 5%
        return "Inaccuracy"
    if delta_win_pct < _LC0_BLUNDER_MIN:      # 5% ≤ Δ < 10%
        return "Mistake"
    return "Blunder"                          # Δ ≥ 10%


def cp_equiv_from_q(q: float) -> int:
    """Convert an Lc0 Q value to its centipawn equivalent.

    Formula (analysis-math.md):
        cp_equiv = 111.714640912 · tan(1.5620688421 · Q)

    Q is clamped to (-0.9999999, 0.9999999) to avoid the tangent singularity
    at ±1.

    Args:
        q: Lc0 Q value in (-1, 1).

    Returns:
        Integer centipawn equivalent.
    """
    q_clamped = max(-0.9999999, min(0.9999999, q))
    return round(_Q_CP_SCALE * math.tan(_Q_CP_INNER * q_clamped))
```

- [ ] **Step 5: Run math tests to verify they pass**

```bash
pytest tests/test_math.py -v
```

Expected: All tests pass.

- [ ] **Step 6: Write the failing SEE tests**

```python
# tests/test_see.py
"""
Title: test_see.py — Tests for Static Exchange Evaluation
Description:
    Verifies that see_capture_or_sacrifice() returns True only when the
    full exchange sequence on the destination square is a net material
    loss for the mover.

Changelog:
    2026-05-09: Initial creation
"""
import chess
import pytest
from local_worker.analysis.see import see_value, see_capture_or_sacrifice


def test_unprotected_pawn_capture_is_winning():
    # White pawn on e4 captures undefended pawn on d5 — SEE = +pawn
    board = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("e4d5")
    assert see_value(board, move) > 0
    assert not see_capture_or_sacrifice(board, move)


def test_queen_takes_defended_pawn_is_sacrifice():
    # White queen takes pawn on h7 defended by king — SEE strongly negative
    board = chess.Board("rnbqk2r/pppp1ppp/5n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 0 1")
    # Construct a clean test: White queen on h5 takes h7 defended by king
    board2 = chess.Board("4k2r/7p/8/7Q/8/8/8/4K3 w k - 0 1")
    move = chess.Move.from_uci("h5h7")
    assert see_value(board2, move) < 0
    assert see_capture_or_sacrifice(board2, move)


def test_equal_trade_is_not_sacrifice():
    # White knight takes Black knight, defended only by a pawn — net 0 (knight for knight)
    board = chess.Board("4k3/8/3p4/4n3/3N4/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("d4e5")
    # SEE: +knight (320) -knight (320) = 0
    assert see_value(board, move) == 0
    assert not see_capture_or_sacrifice(board, move)


def test_quiet_move_returns_zero():
    board = chess.Board()
    move = chess.Move.from_uci("e2e4")
    assert see_value(board, move) == 0
    assert not see_capture_or_sacrifice(board, move)
```

- [ ] **Step 7: Run to verify it fails**

```bash
pytest tests/test_see.py -v
```

Expected: `ModuleNotFoundError: No module named 'local_worker.analysis.see'`

- [ ] **Step 8: Implement `analysis/see.py`**

`python-chess` does not expose SEE in the public API, so we implement it directly using `Board.attackers()` to enumerate exchange participants in least-valuable-attacker order. The algorithm follows the standard SEE swap-list method.

```python
"""
Title: see.py — Static Exchange Evaluation
Description:
    Computes Static Exchange Evaluation (SEE) for a move, returning the
    net material gain/loss in centipawns for the side initiating the
    capture sequence on the destination square.

    SEE simulates the full exchange — the moving side captures, the
    opponent recaptures with the least valuable attacker, and so on —
    minimaxing the running material balance. A move is classified as a
    "capture or sacrifice" iff SEE is strictly negative for the mover.

    Implementation note: python-chess has no public SEE method, so we
    enumerate attackers via Board.attackers() and process them in
    increasing piece value, swapping sides each step. X-ray attackers
    behind sliding pieces are revealed by removing the captured square
    from the occupancy and re-querying attackers.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import chess

# Centipawn values used for SEE balance arithmetic.
_PIECE_CP = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}


def _least_valuable_attacker(
    board: chess.Board, attackers: chess.SquareSet, color: chess.Color
) -> int | None:
    """Return the square of the cheapest attacker in `attackers`, or None.

    Args:
        board: Position (used to read piece type at each attacker square).
        attackers: SquareSet of pieces of `color` attacking the target.
        color: The side whose attackers we are scanning.

    Returns:
        Square index of the least-valuable attacker, or None if `attackers`
        is empty.
    """
    best_sq: int | None = None
    best_val: int | None = None
    for sq in attackers:
        piece = board.piece_at(sq)
        if piece is None or piece.color != color:
            continue
        val = _PIECE_CP[piece.piece_type]
        if best_val is None or val < best_val:
            best_val = val
            best_sq = sq
    return best_sq


def see_value(board: chess.Board, move: chess.Move) -> int:
    """Compute SEE for `move` from the moving side's perspective.

    For non-capture moves SEE returns 0. For captures, returns the net
    centipawn balance after the full exchange sequence on the destination
    square, assuming both sides play the SEE-optimal recapture order
    (cheapest attacker first; either side may stand pat).

    Args:
        board: Position before the move.
        move: A pseudo-legal move on `board`.

    Returns:
        Centipawn balance: positive = mover gains material, negative =
        mover loses material, 0 = even or non-capture.
    """
    target = move.to_square
    captured = board.piece_at(target)
    moving = board.piece_at(move.from_square)
    if captured is None or moving is None:
        return 0

    # Build a working occupancy we can mutate to reveal x-ray attackers.
    occupancy = board.occupied
    side = not board.turn  # after the initial capture, opponent moves next
    gain: list[int] = [_PIECE_CP[captured.piece_type]]
    moved_piece_type = moving.piece_type
    occupancy &= ~chess.BB_SQUARES[move.from_square]

    while True:
        # Find cheapest attacker of `target` for `side` given current occupancy
        attackers_bb = (
            board.attackers_mask(side, target) & occupancy
        )
        if not attackers_bb:
            break
        attackers = chess.SquareSet(attackers_bb)
        from_sq = _least_valuable_attacker(board, attackers, side)
        if from_sq is None:
            break

        # The piece doing the recapture is the moved piece for the next swap step
        gain.append(_PIECE_CP[moved_piece_type] - gain[-1])
        moved_piece_type = board.piece_type_at(from_sq) or chess.PAWN
        occupancy &= ~chess.BB_SQUARES[from_sq]
        side = not side

        # Pruning: if even capturing optimally cannot improve, stop.
        if max(-gain[-2], gain[-1]) < 0:
            break

    # Minimax the gain list
    while len(gain) > 1:
        gain[-2] = -max(-gain[-2], gain[-1])
        gain.pop()
    return gain[0]


def see_capture_or_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """Return True iff SEE on the destination square is negative for the mover.

    Per analysis-math.md, this is the canonical "capture or sacrifice"
    predicate used by the Brilliant classification gate.

    Args:
        board: Position before the move.
        move: The move being played.

    Returns:
        True if the mover ends the exchange down material, False otherwise
        (including for quiet moves and equal/winning captures).
    """
    return see_value(board, move) < 0
```

- [ ] **Step 9: Run SEE tests**

```bash
pytest tests/test_see.py -v
```

Expected: All tests pass. If any fail, fix the SEE implementation — do **not** loosen the test assertions.

- [ ] **Step 10: Commit**

```bash
git add local_worker/analysis/ tests/test_math.py tests/test_see.py
git commit -m "feat(local-worker): analysis math + SEE per analysis-math.md spec"
```

---

## Task 4: Engine Detector

**Files:**
- Create: `services/local_worker/local_worker/detector.py`
- Create: `services/local_worker/tests/test_detector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_detector.py
"""
Title: test_detector.py — Tests for engine detection
Description:
    Tests that binary search and hardware detection produce valid output.

Changelog:
    2026-05-09: Initial creation
"""
import sys
import pytest
from unittest.mock import patch
from local_worker.detector import (
    find_binary,
    detect_lc0_backend,
    suggest_stockfish_settings,
    HardwareInfo,
    detect_hardware,
)


def test_find_binary_returns_none_for_nonexistent():
    result = find_binary("definitely_not_a_real_binary_xyz123")
    assert result is None


def test_find_binary_finds_python():
    # Python itself must be findable on PATH
    result = find_binary("python") or find_binary("python3")
    assert result is not None


def test_detect_hardware_returns_hardware_info():
    info = detect_hardware()
    assert isinstance(info, HardwareInfo)
    assert info.cpu_count >= 1
    assert info.ram_mb > 0


def test_suggest_stockfish_settings_sane_bounds():
    info = HardwareInfo(cpu_count=8, ram_mb=16384, has_cuda=False, has_apple_silicon=False)
    settings = suggest_stockfish_settings(info)
    assert 1 <= settings["threads"] <= 16
    assert 128 <= settings["hash_mb"] <= 8192


def test_detect_lc0_backend_returns_string():
    backend = detect_lc0_backend()
    assert backend in ("cuda-auto", "metal", "cpu")
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_detector.py -v
```

Expected: `ModuleNotFoundError: No module named 'local_worker.detector'`

- [ ] **Step 3: Implement `local_worker/detector.py`**

```python
"""
Title: detector.py — Engine binary detection and hardware sensing
Description:
    Locates Stockfish and Lc0 binaries across Windows/Mac/Linux, detects
    available compute backends (CUDA, Metal, CPU), and suggests default
    engine settings based on available hardware.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class HardwareInfo:
    """Snapshot of locally available compute resources."""

    cpu_count: int
    ram_mb: int
    has_cuda: bool
    has_apple_silicon: bool


_STOCKFISH_CANDIDATES = [
    "stockfish",
    "/usr/games/stockfish",
    "/usr/local/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
    r"C:\Program Files\Stockfish\stockfish.exe",
]

_LC0_CANDIDATES = [
    "lc0",
    "/usr/local/bin/lc0",
    "/opt/homebrew/bin/lc0",
    r"C:\Program Files\Lc0\lc0.exe",
]


def find_binary(name: str, extra_paths: Optional[list[str]] = None) -> Optional[str]:
    """Search PATH and known locations for a binary by name.

    Args:
        name: Binary name or absolute path to try.
        extra_paths: Additional candidate paths to check.

    Returns:
        Absolute path string if found, None otherwise.
    """
    found = shutil.which(name)
    if found:
        return found
    for candidate in (extra_paths or []):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def find_stockfish() -> Optional[str]:
    """Search for a Stockfish binary.

    Returns:
        Path to stockfish binary, or None if not found.
    """
    return find_binary("stockfish", _STOCKFISH_CANDIDATES)


def find_lc0() -> Optional[str]:
    """Search for an Lc0 binary.

    Returns:
        Path to lc0 binary, or None if not found.
    """
    return find_binary("lc0", _LC0_CANDIDATES)


def _has_cuda() -> bool:
    """Return True if an NVIDIA GPU with CUDA is available."""
    return shutil.which("nvidia-smi") is not None


def _has_apple_silicon() -> bool:
    """Return True if running on Apple Silicon (M1/M2/M3/M4)."""
    return sys.platform == "darwin" and platform.machine() == "arm64"


def detect_hardware() -> HardwareInfo:
    """Probe the system for CPU, RAM, and GPU capabilities.

    Returns:
        HardwareInfo with cpu_count, ram_mb, has_cuda, has_apple_silicon.
    """
    import os
    cpu_count = os.cpu_count() or 1

    ram_mb = 4096  # safe default
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            )
            ram_mb = int(result.stdout.strip()) // (1024 * 1024)
        elif sys.platform.startswith("linux"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        ram_mb = int(line.split()[1]) // 1024
                        break
        elif sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            c_ulong = ctypes.c_ulong
            mem_status = ctypes.c_ulong(0)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status))
    except Exception:
        pass

    return HardwareInfo(
        cpu_count=cpu_count,
        ram_mb=ram_mb,
        has_cuda=_has_cuda(),
        has_apple_silicon=_has_apple_silicon(),
    )


def detect_lc0_backend() -> str:
    """Determine the best Lc0 compute backend for this machine.

    Returns:
        Backend string: 'cuda-auto', 'metal', or 'cpu'.
    """
    if _has_cuda():
        return "cuda-auto"
    if _has_apple_silicon():
        return "metal"
    return "cpu"


def suggest_stockfish_settings(hw: HardwareInfo) -> dict[str, int]:
    """Suggest sensible Stockfish thread/hash settings for this hardware.

    Args:
        hw: HardwareInfo from detect_hardware().

    Returns:
        Dict with 'threads' and 'hash_mb' keys.
    """
    threads = max(1, hw.cpu_count - 1)
    threads = min(threads, 16)
    hash_mb = max(128, min(hw.ram_mb // 4, 8192))
    return {"threads": threads, "hash_mb": hash_mb}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_detector.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add local_worker/detector.py tests/test_detector.py
git commit -m "feat(local-worker): engine detection and hardware sensing"
```

---

## Task 5: Stockfish Analyser

**Files:**
- Create: `services/local_worker/local_worker/analysis/stockfish.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_math.py` (or create `tests/test_stockfish.py` if you prefer a real engine in CI):

The following test uses a mock engine — no real Stockfish binary required for the unit test.

```python
# Add to tests/test_math.py or create tests/test_stockfish_payload.py
"""
Title: test_stockfish_payload.py — Tests for Stockfish payload building
Description:
    Tests that the build_stockfish_payload helper produces valid API payloads
    from pre-canned move results.

Changelog:
    2026-05-09: Initial creation
"""
import pytest
from local_worker.analysis.models import StockfishMoveResult, StockfishGameResult
from local_worker.analysis.stockfish import build_stockfish_payload


def test_payload_structure():
    game = StockfishGameResult(
        engine_depth=20,
        white_accuracy=92.1,
        black_accuracy=87.3,
        white_acpl=15.2,
        black_acpl=23.8,
        white_blunders=0,
        white_mistakes=1,
        white_inaccuracies=2,
        black_blunders=1,
        black_mistakes=2,
        black_inaccuracies=3,
        moves=[
            StockfishMoveResult(
                ply=1, san="e4",
                fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
                cp_eval=35, cpl=0, best_move="e4", classification="Best",
            )
        ],
    )
    payload = build_stockfish_payload(game, worker_id="test-worker")
    assert payload["engine"] == "stockfish"
    assert payload["worker_id"] == "test-worker"
    assert payload["engine_depth"] == 20
    assert 0 <= payload["white_accuracy"] <= 100
    assert len(payload["moves"]) == 1
    move = payload["moves"][0]
    assert move["ply"] == 1
    assert move["classification"] == "Best"
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_stockfish_payload.py -v
```

Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement `analysis/stockfish.py`**

```python
"""
Title: stockfish.py — Stockfish UCI analysis engine
Description:
    Runs Stockfish analysis on a PGN string via the python-chess UCI interface.
    Produces a StockfishGameResult with per-move evaluations and classifications
    that conform exactly to services/app/documentation/analysis-math.md:
      - cp values are stored from White's frame; mover-perspective is derived
        via cpl_from_evals() and pov(mover).
      - Capture/sacrifice detection uses SEE (analysis/see.py).
      - Game accuracy uses windowed Win%-stddev weighting plus harmonic mean.
      - ACPL is per-player.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import io
import logging
from typing import Callable, Optional

import chess
import chess.engine
import chess.pgn

from .math import (
    MATE_SCORE,
    classify_stockfish_move,
    cpl_from_evals,
    game_accuracy,
    move_accuracy,
    win_pct,
)
from .models import StockfishGameResult, StockfishMoveResult
from .see import see_capture_or_sacrifice

log = logging.getLogger(__name__)


def _white_cp(score: chess.engine.PovScore) -> int:
    """Return the cp evaluation from White's perspective, mate flattened to ±MATE_SCORE.

    Args:
        score: PovScore from engine analysis.

    Returns:
        cp value in [-MATE_SCORE, MATE_SCORE].
    """
    return score.pov(chess.WHITE).score(mate_score=MATE_SCORE)


def analyze_pgn(
    pgn_text: str,
    stockfish_path: str,
    depth: int = 20,
    threads: int = 4,
    hash_mb: int = 512,
    syzygy_path: str = "",
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> StockfishGameResult:
    """Analyse a PGN game with Stockfish per analysis-math.md.

    Args:
        pgn_text: Full PGN string for the game.
        stockfish_path: Absolute path to the Stockfish binary.
        depth: Analysis depth (default 20).
        threads: Engine thread count (default 4).
        hash_mb: Engine hash table size in MB (default 512).
        syzygy_path: Path to Syzygy tablebase directory, or empty string.
        progress_callback: Optional callable(ply, total_plies) called per move.

    Returns:
        StockfishGameResult containing per-move evaluations, per-player
        accuracy/ACPL, and classification counts.
    """
    parsed = chess.pgn.read_game(io.StringIO(pgn_text))
    if parsed is None:
        raise ValueError("Failed to parse PGN")

    moves_list = list(parsed.mainline_moves())
    total_plies = len(moves_list)

    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    try:
        opts: dict = {"Threads": threads, "Hash": hash_mb, "MultiPV": 2}
        if syzygy_path:
            opts["SyzygyPath"] = syzygy_path
        engine.configure(opts)

        board = parsed.board()
        move_results: list[StockfishMoveResult] = []

        # Per-player accumulators (only the player's own moves).
        white_accs: list[float] = []
        white_winpcts_before: list[float] = []
        white_cpls: list[int] = []
        black_accs: list[float] = []
        black_winpcts_before: list[float] = []
        black_cpls: list[int] = []

        cls_counts: dict = {
            chess.WHITE: {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
            chess.BLACK: {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
        }
        limit = chess.engine.Limit(depth=depth)

        for ply_index, move in enumerate(moves_list, start=1):
            mover = board.turn
            fen_before = board.fen()
            move_san = board.san(move)
            is_cap_or_sac = see_capture_or_sacrifice(board, move)

            info_before = engine.analyse(board, limit, multipv=2)
            eval_before_white = _white_cp(info_before[0]["score"])
            mover_eval_before = (
                eval_before_white if mover == chess.WHITE else -eval_before_white
            )
            mover_win_pct_before = win_pct(mover_eval_before)

            second_best_gap: Optional[int] = None
            if len(info_before) >= 2:
                eval_second_white = _white_cp(info_before[1]["score"])
                mover_eval_second = (
                    eval_second_white if mover == chess.WHITE else -eval_second_white
                )
                second_best_gap = mover_eval_before - mover_eval_second

            best_pv = info_before[0].get("pv") or []
            best_move_san = board.san(best_pv[0]) if best_pv else ""

            board.push(move)

            info_after = engine.analyse(board, limit)
            eval_after_white = _white_cp(info_after["score"])
            mover_eval_after = (
                eval_after_white if mover == chess.WHITE else -eval_after_white
            )
            mover_win_pct_after = win_pct(mover_eval_after)

            cpl = cpl_from_evals(
                eval_before_white,
                eval_after_white,
                mover_is_white=(mover == chess.WHITE),
            )
            move_acc = move_accuracy(mover_win_pct_before, mover_win_pct_after)
            classification = classify_stockfish_move(
                cpl=cpl,
                second_best_gap=second_best_gap,
                mover_win_pct=mover_win_pct_before,
                is_capture_or_sacrifice=is_cap_or_sac,
            )

            move_results.append(StockfishMoveResult(
                ply=ply_index,
                san=move_san,
                fen=fen_before,
                cp_eval=eval_after_white,  # API stores White's-frame cp
                cpl=cpl,
                best_move=best_move_san,
                classification=classification,
            ))

            if mover == chess.WHITE:
                white_accs.append(move_acc)
                white_winpcts_before.append(mover_win_pct_before)
                white_cpls.append(cpl)
            else:
                black_accs.append(move_acc)
                black_winpcts_before.append(mover_win_pct_before)
                black_cpls.append(cpl)

            if classification in cls_counts[mover]:
                cls_counts[mover][classification] += 1

            if progress_callback:
                progress_callback(ply_index, total_plies)

        def _avg(nums: list[int] | list[float]) -> float:
            return float(sum(nums)) / len(nums) if nums else 0.0

        return StockfishGameResult(
            engine_depth=depth,
            white_accuracy=game_accuracy(white_accs, win_pcts=white_winpcts_before),
            black_accuracy=game_accuracy(black_accs, win_pcts=black_winpcts_before),
            white_acpl=_avg(white_cpls),
            black_acpl=_avg(black_cpls),
            white_blunders=cls_counts[chess.WHITE]["Blunder"],
            white_mistakes=cls_counts[chess.WHITE]["Mistake"],
            white_inaccuracies=cls_counts[chess.WHITE]["Inaccuracy"],
            black_blunders=cls_counts[chess.BLACK]["Blunder"],
            black_mistakes=cls_counts[chess.BLACK]["Mistake"],
            black_inaccuracies=cls_counts[chess.BLACK]["Inaccuracy"],
            moves=move_results,
        )
    finally:
        engine.quit()


def build_stockfish_payload(result: StockfishGameResult, *, worker_id: str) -> dict:
    """Serialize a StockfishGameResult into the API complete payload dict.

    Args:
        result: StockfishGameResult from analyze_pgn().
        worker_id: Worker identifier string to include in the payload.

    Returns:
        Dict matching the StockfishCompleteSerializer schema.
    """
    return {
        "engine": "stockfish",
        "worker_id": worker_id,
        "engine_depth": result.engine_depth,
        "white_accuracy": result.white_accuracy,
        "black_accuracy": result.black_accuracy,
        "white_acpl": result.white_acpl,
        "black_acpl": result.black_acpl,
        "white_blunders": result.white_blunders,
        "white_mistakes": result.white_mistakes,
        "white_inaccuracies": result.white_inaccuracies,
        "black_blunders": result.black_blunders,
        "black_mistakes": result.black_mistakes,
        "black_inaccuracies": result.black_inaccuracies,
        "moves": [
            {
                "ply": m.ply,
                "san": m.san,
                "fen": m.fen,
                "cp_eval": m.cp_eval,
                "cpl": m.cpl,
                "best_move": m.best_move,
                "classification": m.classification,
            }
            for m in result.moves
        ],
    }
```

- [ ] **Step 4: Run payload tests**

```bash
pytest tests/test_stockfish_payload.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add local_worker/analysis/stockfish.py tests/test_stockfish_payload.py
git commit -m "feat(local-worker): Stockfish UCI analyser with SEE-based classification"
```

---

## Task 6: Lc0 Analyser

**Files:**
- Create: `services/local_worker/local_worker/analysis/lc0.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lc0_payload.py
"""
Title: test_lc0_payload.py — Tests for Lc0 payload building
Description:
    Tests that build_lc0_payload() produces a valid API payload from pre-canned results.

Changelog:
    2026-05-09: Initial creation
"""
import pytest
from local_worker.analysis.models import Lc0MoveResult, Lc0GameResult
from local_worker.analysis.lc0 import build_lc0_payload


def test_payload_structure():
    game = Lc0GameResult(
        engine_nodes=10000,
        network_name="BT4",
        white_win_prob=0.42,
        white_draw_prob=0.35,
        white_loss_prob=0.23,
        black_win_prob=0.23,
        black_draw_prob=0.35,
        black_loss_prob=0.42,
        white_blunders=0,
        white_mistakes=1,
        white_inaccuracies=2,
        black_blunders=1,
        black_mistakes=0,
        black_inaccuracies=1,
        moves=[
            Lc0MoveResult(
                ply=1, san="d4",
                fen="rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
                wdl_win=420, wdl_draw=350, wdl_loss=230,
                cp_equiv=28, best_move="d4",
                arrow_uci="d2d4", arrow_uci_2="", arrow_uci_3="",
                arrow_score_1=None, arrow_score_2=None, arrow_score_3=None,
                move_win_delta=0.7, classification="Best",
                pv_san_1=None, pv_san_2=None, pv_san_3=None,
            )
        ],
    )
    payload = build_lc0_payload(game, worker_id="test-lc0")
    assert payload["engine"] == "lc0"
    assert payload["worker_id"] == "test-lc0"
    assert payload["engine_nodes"] == 10000
    assert payload["network_name"] == "BT4"
    assert len(payload["moves"]) == 1
    m = payload["moves"][0]
    assert m["wdl_win"] == 420
    assert m["classification"] == "Best"
    assert m["move_win_delta"] == pytest.approx(0.7)
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_lc0_payload.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `analysis/lc0.py`**

```python
"""
Title: lc0.py — Lc0 UCI analysis engine
Description:
    Runs Lc0 analysis on a PGN string via the python-chess UCI interface.
    Requests MultiPV=3 to capture candidate arrows. Produces Lc0GameResult
    with WDL scores from White's perspective and win%-delta classifications.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import io
import json
import logging
from typing import Optional, Callable

import chess
import chess.engine
import chess.pgn

from .math import classify_lc0_move, cp_equiv_from_q, MATE_SCORE
from .models import Lc0MoveResult, Lc0GameResult
from .see import see_capture_or_sacrifice

log = logging.getLogger(__name__)


def _wdl_to_white(wdl: chess.engine.Wdl, turn: chess.Color) -> tuple[int, int, int]:
    """Convert engine WDL (from current player's perspective) to White's perspective.

    Args:
        wdl: WDL from python-chess (current player's perspective, 0–1000 each).
        turn: The colour to move when the engine was called.

    Returns:
        (win, draw, loss) from White's perspective as integers 0–1000.
    """
    w, d, l = wdl.wins, wdl.draws, wdl.losses
    if turn == chess.WHITE:
        return w, d, l
    return l, d, w


def _mover_win_pct_from_wdl(wdl: chess.engine.Wdl) -> float:
    """Win% for the current mover from WDL permille values.

    Args:
        wdl: WDL from engine (current player's perspective).

    Returns:
        Win% as 0–100.
    """
    return (wdl.wins + wdl.draws * 0.5) / 10.0


def analyze_pgn(
    pgn_text: str,
    lc0_path: str,
    nodes: int = 10000,
    weights_path: str = "",
    syzygy_path: str = "",
    backend: str = "cpu",
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Lc0GameResult:
    """Analyse a PGN game with Lc0 and return per-move WDL results.

    Args:
        pgn_text: Full PGN string for the game.
        lc0_path: Absolute path to the lc0 binary.
        nodes: Node budget per move (default 10000).
        weights_path: Path to network weights file, or empty for default.
        syzygy_path: Path to Syzygy tablebase directory, or empty string.
        backend: Lc0 backend ('cuda-auto', 'metal', 'cpu').
        progress_callback: Optional callable(ply, total_plies) called per move.

    Returns:
        Lc0GameResult with per-move WDL evaluations and game statistics.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Failed to parse PGN")

    moves_list = list(game.mainline_moves())
    total_plies = len(moves_list)
    network_name = ""

    engine = chess.engine.SimpleEngine.popen_uci(lc0_path)
    try:
        opts: dict = {"Backend": backend}
        if weights_path:
            opts["WeightsFile"] = weights_path
        if syzygy_path:
            opts["SyzygyPath"] = syzygy_path
        engine.configure(opts)

        # Try to get network name from engine info
        try:
            info = engine.id
            network_name = info.get("name", "")
        except Exception:
            pass

        board = game.board()
        move_results: list[Lc0MoveResult] = []
        white_wdl_wins: list[float] = []
        white_wdl_draws: list[float] = []
        white_wdl_losses: list[float] = []
        black_wdl_wins: list[float] = []
        black_wdl_draws: list[float] = []
        black_wdl_losses: list[float] = []
        cls_counts: dict = {
            "white": {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
            "black": {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
        }
        limit = chess.engine.Limit(nodes=nodes)

        for ply_index, move in enumerate(moves_list, start=1):
            mover = board.turn
            fen_before = board.fen()
            move_san = board.san(move)
            is_cap_or_sac = see_capture_or_sacrifice(board, move)

            info_before_list = engine.analyse(board, limit, multipv=3)
            info_before = info_before_list[0]
            wdl_before = info_before["score"].pov(mover).wdl()
            mover_win_pct_before = _mover_win_pct_from_wdl(wdl_before)

            # Candidate arrows (MultiPV)
            arrows = []
            arrow_scores = []
            pv_sans = []
            for pv_info in info_before_list[:3]:
                pv = pv_info.get("pv", [])
                if pv:
                    arrows.append(pv[0].uci())
                    pv_wdl = pv_info["score"].pov(mover).wdl()
                    arrow_scores.append(_mover_win_pct_from_wdl(pv_wdl))
                    # SAN continuation
                    pv_board = board.copy()
                    pv_san_list = []
                    for pv_move in pv[:5]:
                        try:
                            pv_san_list.append(pv_board.san(pv_move))
                            pv_board.push(pv_move)
                        except Exception:
                            break
                    pv_sans.append(json.dumps(pv_san_list) if pv_san_list else None)
                else:
                    arrows.append("")
                    arrow_scores.append(None)
                    pv_sans.append(None)

            best_move_uci = arrows[0] if arrows else ""
            best_move_san = board.san(chess.Move.from_uci(best_move_uci)) if best_move_uci else ""

            second_best_gap: Optional[float] = None
            if len(arrow_scores) >= 2 and arrow_scores[0] is not None and arrow_scores[1] is not None:
                second_best_gap = arrow_scores[0] - arrow_scores[1]

            board.push(move)
            info_after = engine.analyse(board, limit)
            wdl_after = info_after["score"].pov(mover).wdl()
            mover_win_pct_after = _mover_win_pct_from_wdl(wdl_after)

            delta_win_pct = max(0.0, mover_win_pct_before - mover_win_pct_after)
            classification = classify_lc0_move(
                delta_win_pct=delta_win_pct,
                second_best_gap=second_best_gap,
                mover_win_pct=mover_win_pct_before,
                is_capture_or_sacrifice=is_cap_or_sac,
            )

            # WDL stored from White's perspective
            wdl_white = _wdl_to_white(wdl_after, board.turn)  # board.turn is now opponent

            # cp_equiv from Q value
            q = (wdl_after.wins - wdl_after.losses) / 1000.0
            cp_eq = cp_equiv_from_q(q)

            side = "white" if mover == chess.WHITE else "black"
            if classification in cls_counts[side]:
                cls_counts[side][classification] += 1

            if mover == chess.WHITE:
                white_wdl_wins.append(wdl_white[0] / 1000)
                white_wdl_draws.append(wdl_white[1] / 1000)
                white_wdl_losses.append(wdl_white[2] / 1000)
            else:
                black_wdl_wins.append(wdl_white[0] / 1000)
                black_wdl_draws.append(wdl_white[1] / 1000)
                black_wdl_losses.append(wdl_white[2] / 1000)

            move_results.append(Lc0MoveResult(
                ply=ply_index,
                san=move_san,
                fen=fen_before,
                wdl_win=wdl_white[0],
                wdl_draw=wdl_white[1],
                wdl_loss=wdl_white[2],
                cp_equiv=cp_eq,
                best_move=best_move_san,
                arrow_uci=arrows[0] if len(arrows) > 0 else "",
                arrow_uci_2=arrows[1] if len(arrows) > 1 else "",
                arrow_uci_3=arrows[2] if len(arrows) > 2 else "",
                arrow_score_1=arrow_scores[0] if len(arrow_scores) > 0 else None,
                arrow_score_2=arrow_scores[1] if len(arrow_scores) > 1 else None,
                arrow_score_3=arrow_scores[2] if len(arrow_scores) > 2 else None,
                move_win_delta=delta_win_pct,
                classification=classification,
                pv_san_1=pv_sans[0] if len(pv_sans) > 0 else None,
                pv_san_2=pv_sans[1] if len(pv_sans) > 1 else None,
                pv_san_3=pv_sans[2] if len(pv_sans) > 2 else None,
            ))

            if progress_callback:
                progress_callback(ply_index, total_plies)

        def _avg(lst: list[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0

        return Lc0GameResult(
            engine_nodes=nodes,
            network_name=network_name,
            white_win_prob=_avg(white_wdl_wins),
            white_draw_prob=_avg(white_wdl_draws),
            white_loss_prob=_avg(white_wdl_losses),
            black_win_prob=_avg(black_wdl_wins),
            black_draw_prob=_avg(black_wdl_draws),
            black_loss_prob=_avg(black_wdl_losses),
            white_blunders=cls_counts["white"]["Blunder"],
            white_mistakes=cls_counts["white"]["Mistake"],
            white_inaccuracies=cls_counts["white"]["Inaccuracy"],
            black_blunders=cls_counts["black"]["Blunder"],
            black_mistakes=cls_counts["black"]["Mistake"],
            black_inaccuracies=cls_counts["black"]["Inaccuracy"],
            moves=move_results,
        )
    finally:
        engine.quit()


def build_lc0_payload(result: Lc0GameResult, *, worker_id: str) -> dict:
    """Serialize a Lc0GameResult into the API complete payload dict.

    Args:
        result: Lc0GameResult from analyze_pgn().
        worker_id: Worker identifier string.

    Returns:
        Dict matching the Lc0CompleteSerializer schema.
    """
    return {
        "engine": "lc0",
        "worker_id": worker_id,
        "engine_nodes": result.engine_nodes,
        "network_name": result.network_name,
        "white_win_prob": result.white_win_prob,
        "white_draw_prob": result.white_draw_prob,
        "white_loss_prob": result.white_loss_prob,
        "black_win_prob": result.black_win_prob,
        "black_draw_prob": result.black_draw_prob,
        "black_loss_prob": result.black_loss_prob,
        "white_blunders": result.white_blunders,
        "white_mistakes": result.white_mistakes,
        "white_inaccuracies": result.white_inaccuracies,
        "black_blunders": result.black_blunders,
        "black_mistakes": result.black_mistakes,
        "black_inaccuracies": result.black_inaccuracies,
        "moves": [
            {
                "ply": m.ply,
                "san": m.san,
                "fen": m.fen,
                "wdl_win": m.wdl_win,
                "wdl_draw": m.wdl_draw,
                "wdl_loss": m.wdl_loss,
                "cp_equiv": m.cp_equiv,
                "best_move": m.best_move,
                "arrow_uci": m.arrow_uci,
                "arrow_uci_2": m.arrow_uci_2,
                "arrow_uci_3": m.arrow_uci_3,
                "arrow_score_1": m.arrow_score_1,
                "arrow_score_2": m.arrow_score_2,
                "arrow_score_3": m.arrow_score_3,
                "move_win_delta": m.move_win_delta,
                "classification": m.classification,
                "pv_san_1": m.pv_san_1,
                "pv_san_2": m.pv_san_2,
                "pv_san_3": m.pv_san_3,
            }
            for m in result.moves
        ],
    }
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_lc0_payload.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add local_worker/analysis/lc0.py tests/test_lc0_payload.py
git commit -m "feat(local-worker): Lc0 UCI analyser with WDL classification and arrow capture"
```

---

## Task 7: Worker Loop + Stats

**Files:**
- Create: `services/local_worker/local_worker/loop.py`
- Create: `services/local_worker/tests/test_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_loop.py
"""
Title: test_loop.py — Tests for the worker loop stats tracking
Description:
    Tests that WorkerStats accumulates counts correctly and that
    run_one_job dispatches to the right engine analyser.

Changelog:
    2026-05-09: Initial creation
"""
from unittest.mock import MagicMock, patch
from local_worker.loop import WorkerStats


def test_stats_initial_state():
    s = WorkerStats()
    assert s.games_processed == 0
    assert s.stockfish_count == 0
    assert s.lc0_count == 0
    assert s.total_seconds == 0.0


def test_stats_record_game_stockfish():
    s = WorkerStats()
    s.record_game("stockfish", 3.5)
    assert s.games_processed == 1
    assert s.stockfish_count == 1
    assert s.lc0_count == 0
    assert s.total_seconds == pytest.approx(3.5)


def test_stats_avg_seconds_per_game():
    import pytest
    s = WorkerStats()
    s.record_game("stockfish", 4.0)
    s.record_game("lc0", 6.0)
    assert s.avg_seconds_per_game() == pytest.approx(5.0)


def test_stats_avg_seconds_no_games():
    s = WorkerStats()
    assert s.avg_seconds_per_game() == 0.0
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_loop.py -v
```

Expected: `ModuleNotFoundError: No module named 'local_worker.loop'`

- [ ] **Step 3: Implement `local_worker/loop.py`**

```python
"""
Title: loop.py — Claim-analyse-submit worker loop with stats tracking
Description:
    Implements the main processing loop: checks out jobs from the API,
    dispatches to the appropriate engine analyser, submits results, and
    sends periodic heartbeats. Tracks per-session statistics.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Optional, Callable

from wood_league_shared.worker_client import WorkerClient, WorkerClientError
from local_worker.analysis.stockfish import analyze_pgn as sf_analyze, build_stockfish_payload
from local_worker.analysis.lc0 import analyze_pgn as lc0_analyze, build_lc0_payload
from local_worker.config import Settings

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 30.0


@dataclass
class WorkerStats:
    """Tracks per-session analysis statistics."""

    games_processed: int = 0
    stockfish_count: int = 0
    lc0_count: int = 0
    total_seconds: float = 0.0
    errors: int = 0

    def record_game(self, engine: str, elapsed: float) -> None:
        """Record a successfully processed game.

        Args:
            engine: 'stockfish' or 'lc0'.
            elapsed: Wall-clock seconds taken.
        """
        self.games_processed += 1
        self.total_seconds += elapsed
        if engine == "stockfish":
            self.stockfish_count += 1
        else:
            self.lc0_count += 1

    def avg_seconds_per_game(self) -> float:
        """Return average wall-clock seconds per game, or 0.0 if none processed."""
        if self.games_processed == 0:
            return 0.0
        return self.total_seconds / self.games_processed


def _worker_id(settings: Settings) -> str:
    """Return the worker_id to send to the API.

    Args:
        settings: Current worker settings.

    Returns:
        Configured worker_id, or hostname-based fallback.
    """
    if settings.worker_id:
        return settings.worker_id
    return f"local-{socket.gethostname()}"[:64]


def run_one_job(
    *,
    job,
    settings: Settings,
    stats: WorkerStats,
    client: WorkerClient,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> bool:
    """Claim, analyse, and submit a single job.

    Args:
        job: Job dataclass from WorkerClient.checkout().
        settings: Current worker settings.
        stats: WorkerStats to update on completion.
        client: Authenticated WorkerClient for API calls.
        progress_callback: Optional callable(ply, total_plies) for per-move progress.

    Returns:
        True if the job completed successfully, False on error.
    """
    worker_id = _worker_id(settings)
    start = time.monotonic()

    try:
        if job.engine == "stockfish":
            result = sf_analyze(
                pgn_text=job.pgn,
                stockfish_path=settings.stockfish_path,
                depth=settings.stockfish_depth,
                threads=settings.stockfish_threads,
                hash_mb=settings.stockfish_hash_mb,
                syzygy_path=settings.syzygy_path,
                progress_callback=progress_callback,
            )
            payload = build_stockfish_payload(result, worker_id=worker_id)
            client.complete_stockfish(job_id=job.id, worker_id=worker_id, payload=payload)
        elif job.engine == "lc0":
            nodes = job.nodes or settings.lc0_nodes
            result = lc0_analyze(
                pgn_text=job.pgn,
                lc0_path=settings.lc0_path,
                nodes=nodes,
                syzygy_path=settings.syzygy_path,
                backend=settings.lc0_backend or "cpu",
                progress_callback=progress_callback,
            )
            payload = build_lc0_payload(result, worker_id=worker_id)
            client.complete_lc0(job_id=job.id, worker_id=worker_id, payload=payload)
        else:
            log.error("Unknown engine: %s — failing job %d", job.engine, job.id)
            client.fail(job_id=job.id, worker_id=worker_id, error=f"Unknown engine: {job.engine}")
            return False

        elapsed = time.monotonic() - start
        stats.record_game(job.engine, elapsed)
        return True

    except Exception as exc:
        elapsed = time.monotonic() - start
        stats.errors += 1
        log.exception("Failed to process job %d: %s", job.id, exc)
        try:
            client.fail(job_id=job.id, worker_id=worker_id, error=str(exc)[:2000])
        except Exception:
            log.warning("Failed to report failure for job %d", job.id)
        return False


def run_batch(
    *,
    settings: Settings,
    engines: list[str],
    batch_size: int = 5,
    batch_time_minutes: Optional[int] = None,
    game_id: Optional[str] = None,
    on_job_start: Optional[Callable] = None,
    on_job_done: Optional[Callable] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    stop_event=None,
) -> WorkerStats:
    """Run the main claim→analyse→submit loop.

    Processes jobs until the batch_time_minutes limit is reached, all queues
    are empty, or stop_event is set. Heartbeats are sent every 30 seconds.

    Args:
        settings: Worker settings (API URL, key, engine paths, etc.).
        engines: List of engines to claim jobs for, e.g. ['stockfish', 'lc0'].
        batch_size: Jobs to claim per checkout call (1–10).
        batch_time_minutes: If set, stop after this many minutes.
        game_id: If set, request a specific game (single checkout).
        on_job_start: Optional callable(job) called before analysis.
        on_job_done: Optional callable(job, success, elapsed) called after.
        on_progress: Optional callable(ply, total_plies) for per-move progress.
        stop_event: Optional threading.Event; loop exits when set.

    Returns:
        WorkerStats with totals for the batch.
    """
    client = WorkerClient(base_url=settings.api_url, api_key=settings.api_key)
    stats = WorkerStats()
    worker_id = _worker_id(settings)
    start_time = time.monotonic()
    last_heartbeat = 0.0

    def _time_limit_exceeded() -> bool:
        if batch_time_minutes is None:
            return False
        return (time.monotonic() - start_time) >= batch_time_minutes * 60

    def _send_heartbeat(engine: str) -> None:
        nonlocal last_heartbeat
        now = time.monotonic()
        if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
            try:
                client.heartbeat(
                    worker_id=worker_id,
                    engine=engine,
                    status_message=f"processed={stats.games_processed}",
                )
            except WorkerClientError:
                pass
            last_heartbeat = now

    for engine in engines:
        if _time_limit_exceeded() or (stop_event and stop_event.is_set()):
            break

        while True:
            if _time_limit_exceeded() or (stop_event and stop_event.is_set()):
                break

            _send_heartbeat(engine)

            try:
                jobs = client.checkout(
                    engine=engine,
                    worker_id=worker_id,
                    batch_size=batch_size if not game_id else 1,
                    game_id=game_id,
                    dispatch_mode="pull",
                )
            except WorkerClientError as exc:
                log.error("Checkout failed for %s: %s", engine, exc)
                break

            if not jobs:
                break

            for job in jobs:
                if stop_event and stop_event.is_set():
                    break
                if on_job_start:
                    on_job_start(job)
                job_start = time.monotonic()
                success = run_one_job(
                    job=job,
                    settings=settings,
                    stats=stats,
                    client=client,
                    progress_callback=on_progress,
                )
                if on_job_done:
                    on_job_done(job, success, time.monotonic() - job_start)

    return stats
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_loop.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add local_worker/loop.py tests/test_loop.py
git commit -m "feat(local-worker): claim-analyse-submit worker loop with heartbeat and stats"
```

---

## Task 8: Rich Display

**Files:**
- Create: `services/local_worker/local_worker/display.py`

No unit tests for the display layer — it is thin wiring around Rich primitives. Manual smoke-test instead.

- [ ] **Step 1: Implement `local_worker/display.py`**

```python
"""
Title: display.py — Rich terminal display for the worker
Description:
    Provides a WorkerDisplay context manager that renders a Live layout
    with a per-move progress bar, a batch progress bar, and a stats panel.
    Uses Rich's Progress and Layout APIs.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from local_worker.loop import WorkerStats

console = Console()


def _make_stats_panel(stats: WorkerStats, engine: str, job_desc: str) -> Panel:
    """Build a Rich Panel showing current session statistics.

    Args:
        stats: Current WorkerStats.
        engine: Currently active engine name.
        job_desc: Short description of the current job.

    Returns:
        A Rich Panel renderable.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", justify="right")
    table.add_column(style="white")

    table.add_row("Games processed", str(stats.games_processed))
    table.add_row("Stockfish", str(stats.stockfish_count))
    table.add_row("Lc0", str(stats.lc0_count))
    table.add_row("Avg time/game", f"{stats.avg_seconds_per_game():.1f}s")
    table.add_row("Errors", str(stats.errors))
    table.add_row("Active engine", engine)
    table.add_row("Current job", job_desc)

    return Panel(table, title="[bold green]Session Stats", border_style="green")


@contextmanager
def worker_display(stats: WorkerStats) -> Generator["DisplayHandle", None, None]:
    """Context manager that renders a live worker display.

    Usage:
        with worker_display(stats) as display:
            display.set_job("game-abc", "stockfish", total_moves=80)
            display.advance_move()

    Args:
        stats: WorkerStats shared reference (mutated externally by loop).

    Yields:
        A DisplayHandle for updating the display.
    """
    batch_progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )
    move_progress = Progress(
        TextColumn("[cyan]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
    )

    batch_task = batch_progress.add_task("[bold]Batch progress", total=None)
    move_task = move_progress.add_task("Analysing moves", total=100, visible=False)

    handle = DisplayHandle(
        stats=stats,
        batch_progress=batch_progress,
        move_progress=move_progress,
        batch_task=batch_task,
        move_task=move_task,
    )

    with Live(console=console, refresh_per_second=4) as live:
        handle._live = live
        live.update(handle._render())
        yield handle


class DisplayHandle:
    """Mutable handle for updating the live display from the worker loop."""

    def __init__(
        self,
        stats: WorkerStats,
        batch_progress: Progress,
        move_progress: Progress,
        batch_task,
        move_task,
    ) -> None:
        self.stats = stats
        self._batch_progress = batch_progress
        self._move_progress = move_progress
        self._batch_task = batch_task
        self._move_task = move_task
        self._live: Optional[Live] = None
        self._current_engine = ""
        self._current_job = "idle"

    def set_job(self, game_id: str, engine: str, total_moves: int) -> None:
        """Signal that a new job has started.

        Args:
            game_id: Game identifier string.
            engine: Engine being used ('stockfish' or 'lc0').
            total_moves: Total plies in the game.
        """
        self._current_engine = engine
        self._current_job = game_id
        self._move_progress.update(
            self._move_task,
            description=f"[{engine}] {game_id}",
            total=total_moves,
            completed=0,
            visible=True,
        )
        self._batch_progress.advance(self._batch_task, 0)
        self._refresh()

    def advance_move(self, ply: int, total: int) -> None:
        """Update the per-move progress bar.

        Args:
            ply: Current ply number (1-based).
            total: Total plies in the game.
        """
        self._move_progress.update(self._move_task, completed=ply, total=total)
        self._refresh()

    def job_done(self) -> None:
        """Signal that the current job has finished."""
        self._move_progress.update(self._move_task, visible=False)
        self._batch_progress.advance(self._batch_task, 1)
        self._refresh()

    def _render(self):
        stats_panel = _make_stats_panel(self.stats, self._current_engine, self._current_job)
        columns = Columns([self._batch_progress, self._move_progress], equal=False, expand=True)
        layout = Table.grid()
        layout.add_row(stats_panel)
        layout.add_row(Panel(columns, title="Progress", border_style="blue"))
        return layout

    def _refresh(self) -> None:
        if self._live:
            self._live.update(self._render())
```

- [ ] **Step 2: Smoke-test manually**

```bash
cd services/local_worker
python -c "
from local_worker.loop import WorkerStats
from local_worker.display import worker_display
import time

stats = WorkerStats()
with worker_display(stats) as d:
    d.set_job('game-abc', 'stockfish', 40)
    for i in range(1, 41):
        d.advance_move(i, 40)
        time.sleep(0.05)
    stats.record_game('stockfish', 2.0)
    d.job_done()
    time.sleep(1)
print('Display smoke test passed')
"
```

Expected: A live progress display renders and updates cleanly, then exits.

- [ ] **Step 3: Commit**

```bash
git add local_worker/display.py
git commit -m "feat(local-worker): Rich live display with progress bars and stats panel"
```

---

## Task 9: CLI Commands

**Files:**
- Create: `services/local_worker/local_worker/cli.py`

- [ ] **Step 1: Implement `local_worker/cli.py`**

```python
"""
Title: cli.py — Typer CLI entry point for wood-league-worker
Description:
    Defines the `wood-league-worker` CLI with four commands:
    - setup: interactive first-time configuration
    - run: interactive session to configure and start the worker loop
    - analyze: analyse a specific game by game_id
    - status: show queue counts from the API

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import sys
import threading
from typing import Optional

import questionary
import typer
from rich.console import Console
from rich.table import Table

from local_worker.config import Settings, load_settings, save_settings
from local_worker.detector import (
    detect_hardware,
    detect_lc0_backend,
    find_lc0,
    find_stockfish,
    suggest_stockfish_settings,
)
from local_worker.display import worker_display
from local_worker.loop import WorkerStats, run_batch
from wood_league_shared.worker_client import WorkerClient, WorkerClientError

app = typer.Typer(
    name="wood-league-worker",
    help="Local analysis worker for the Wood League chess platform.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def setup() -> None:
    """Interactive first-time configuration wizard."""
    console.rule("[bold cyan]Wood League Worker — Setup")
    settings = load_settings()

    api_url = questionary.text(
        "API URL (e.g. https://your-app.railway.app):",
        default=settings.api_url or "",
    ).ask()
    if not api_url:
        console.print("[red]Setup cancelled.")
        raise typer.Exit(1)

    api_key = questionary.password("Worker API key:").ask()
    if not api_key:
        console.print("[red]Setup cancelled.")
        raise typer.Exit(1)

    # Detect engines
    console.print("\n[bold]Detecting engines…")
    sf_path = find_stockfish()
    lc0_path = find_lc0()
    hw = detect_hardware()
    backend = detect_lc0_backend()
    sf_settings = suggest_stockfish_settings(hw)

    console.print(f"  Stockfish: [green]{sf_path or 'not found'}")
    console.print(f"  Lc0:       [green]{lc0_path or 'not found'}")
    console.print(f"  Lc0 backend detected: [cyan]{backend}")
    console.print(f"  CPU cores: {hw.cpu_count}  RAM: {hw.ram_mb} MB")
    console.print(f"  Suggested Stockfish threads: {sf_settings['threads']}  hash: {sf_settings['hash_mb']} MB")

    if sf_path:
        sf_path = questionary.text("Stockfish path:", default=sf_path).ask() or sf_path
    else:
        sf_path = questionary.text("Stockfish path (leave blank to skip):").ask() or ""

    if lc0_path:
        lc0_path = questionary.text("Lc0 path:", default=lc0_path).ask() or lc0_path
    else:
        lc0_path = questionary.text("Lc0 path (leave blank to skip):").ask() or ""

    syzygy_path = questionary.text(
        "Syzygy tablebase path (leave blank to skip):",
        default=settings.syzygy_path or "",
    ).ask() or ""

    threads = int(
        questionary.text("Stockfish threads:", default=str(sf_settings["threads"])).ask()
        or sf_settings["threads"]
    )
    hash_mb = int(
        questionary.text("Stockfish hash MB:", default=str(sf_settings["hash_mb"])).ask()
        or sf_settings["hash_mb"]
    )
    sf_depth = int(
        questionary.text("Stockfish depth:", default=str(settings.stockfish_depth)).ask()
        or settings.stockfish_depth
    )
    lc0_nodes = int(
        questionary.text("Lc0 nodes per move:", default=str(settings.lc0_nodes)).ask()
        or settings.lc0_nodes
    )

    new_settings = Settings(
        api_url=api_url.rstrip("/"),
        api_key=api_key,
        stockfish_path=sf_path,
        lc0_path=lc0_path,
        lc0_backend=backend,
        syzygy_path=syzygy_path,
        stockfish_threads=threads,
        stockfish_hash_mb=hash_mb,
        stockfish_depth=sf_depth,
        lc0_nodes=lc0_nodes,
    )
    save_settings(new_settings)
    console.print("\n[bold green]Settings saved! Run `wood-league-worker run` to start.")


@app.command()
def run(
    engine: Optional[str] = typer.Option(None, help="Force engine: stockfish, lc0, or both"),
    batch_size: Optional[int] = typer.Option(None, help="Jobs per checkout (1–10)"),
    batch_time: Optional[int] = typer.Option(None, help="Run for this many minutes then stop"),
) -> None:
    """Start the analysis worker loop (interactive if options omitted)."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    if engine is None:
        engine_choice = questionary.select(
            "Which engines should this worker process?",
            choices=["stockfish", "lc0", "both"],
        ).ask()
        engine = engine_choice

    if batch_size is None:
        batch_size = int(
            questionary.text("Batch size (jobs per checkout, 1–10):", default="5").ask() or 5
        )

    if batch_time is None:
        bt_raw = questionary.text("Run for how many minutes? (leave blank to run until queue empty):").ask()
        batch_time = int(bt_raw) if bt_raw and bt_raw.strip().isdigit() else None

    engines = ["stockfish", "lc0"] if engine == "both" else [engine]

    # Validate engine paths
    if "stockfish" in engines and not settings.stockfish_path:
        console.print("[red]Stockfish path not configured. Run setup.")
        raise typer.Exit(1)
    if "lc0" in engines and not settings.lc0_path:
        console.print("[red]Lc0 path not configured. Run setup.")
        raise typer.Exit(1)

    console.rule(f"[bold cyan]Starting worker — engines: {', '.join(engines)}")
    stop_event = threading.Event()

    stats = WorkerStats()

    def handle_interrupt():
        console.print("\n[yellow]Stopping after current job…")
        stop_event.set()

    try:
        with worker_display(stats) as display:
            def on_job_start(job):
                total_moves = len(job.pgn.split("\n")) * 2  # rough estimate
                display.set_job(job.game_id, job.engine, total_moves)

            def on_progress(ply, total):
                display.advance_move(ply, total)

            def on_job_done(job, success, elapsed):
                display.job_done()

            run_batch(
                settings=settings,
                engines=engines,
                batch_size=batch_size,
                batch_time_minutes=batch_time,
                on_job_start=on_job_start,
                on_job_done=on_job_done,
                on_progress=on_progress,
                stop_event=stop_event,
            )
    except KeyboardInterrupt:
        stop_event.set()

    console.rule("[bold green]Session complete")
    console.print(f"Games processed: [cyan]{stats.games_processed}")
    console.print(f"Stockfish: {stats.stockfish_count}  Lc0: {stats.lc0_count}")
    console.print(f"Avg time/game: {stats.avg_seconds_per_game():.1f}s")
    console.print(f"Errors: {stats.errors}")


@app.command()
def analyze(
    game_id: str = typer.Argument(help="Game ID to analyse"),
    engine: str = typer.Option("stockfish", help="Engine to use: stockfish or lc0"),
) -> None:
    """Analyse a specific game by game_id."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    console.print(f"Requesting game [cyan]{game_id}[/] with [bold]{engine}…")
    stats = WorkerStats()

    with worker_display(stats) as display:
        def on_progress(ply, total):
            display.advance_move(ply, total)

        result = run_batch(
            settings=settings,
            engines=[engine],
            batch_size=1,
            game_id=game_id,
            on_progress=on_progress,
        )

    if result.games_processed == 0:
        console.print("[yellow]No job claimed — game may already be analysed, queued for another engine, or not found.")
    else:
        console.print(f"[green]Done! Analysed in {result.total_seconds:.1f}s")


@app.command()
def status() -> None:
    """Show queue counts from the API."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    client = WorkerClient(base_url=settings.api_url, api_key=settings.api_key)
    try:
        import httpx
        resp = httpx._client.Client(
            headers={"X-Api-Key": settings.api_key}
        ).get(f"{settings.api_url}/api/v1/jobs/status/")
        data = resp.json()
    except Exception as exc:
        console.print(f"[red]Failed to fetch status: {exc}")
        raise typer.Exit(1)

    table = Table(title="Queue Status")
    table.add_column("Engine", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Count", justify="right", style="bold")

    for row in data.get("queue", []):
        table.add_row(row["engine"], row["status"], str(row["count"]))

    console.print(table)
```

**Fix the status command** — use `httpx` directly with a simple GET. Replace the broken import block in `status()`:

```python
@app.command()
def status() -> None:
    """Show queue counts from the API."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    import httpx
    try:
        resp = httpx.get(
            f"{settings.api_url}/api/v1/jobs/status/",
            headers={"X-Api-Key": settings.api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        console.print(f"[red]Failed to fetch status: {exc}")
        raise typer.Exit(1)

    table = Table(title="Queue Status")
    table.add_column("Engine", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Count", justify="right", style="bold")

    for row in data.get("queue", []):
        table.add_row(row["engine"], row["status"], str(row["count"]))

    console.print(table)
```

- [ ] **Step 2: Verify CLI entry point works**

```bash
cd services/local_worker
wood-league-worker --help
```

Expected: Help text listing setup, run, analyze, status commands.

```bash
wood-league-worker setup --help
wood-league-worker run --help
wood-league-worker analyze --help
wood-league-worker status --help
```

Expected: Each command shows its options without errors.

- [ ] **Step 3: Commit**

```bash
git add local_worker/cli.py
git commit -m "feat(local-worker): CLI commands — setup, run, analyze, status"
```

---

## Task 10: Logging + Final Wiring

**Files:**
- Create: `services/local_worker/local_worker/logging_setup.py`
- Modify: `services/local_worker/local_worker/cli.py` (add `@app.callback()`)

- [ ] **Step 1: Implement `local_worker/logging_setup.py`**

```python
"""
Title: logging_setup.py — File-based logging for the worker
Description:
    Configures a rotating file handler that writes warnings and errors to a
    platform-standard log directory. Console output is left to Rich.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import platformdirs


def configure_logging(log_dir: str = "") -> Path:
    """Set up a rotating file log at the platform log directory.

    Args:
        log_dir: Override path for log directory. Defaults to platform log dir.

    Returns:
        Path to the log file.
    """
    if log_dir:
        log_path = Path(log_dir)
    else:
        log_path = Path(platformdirs.user_log_dir("wood-league-worker", "WoodLeague"))
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "worker.log"

    handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setLevel(logging.WARNING)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    root.addHandler(handler)

    return log_file
```

- [ ] **Step 2: Wire logging into the CLI app callback**

Add this before the `setup` command in `cli.py`:

```python
from local_worker.logging_setup import configure_logging

@app.callback()
def _startup(
    log_dir: str = typer.Option("", envvar="WLW_LOG_DIR", help="Override log file directory", hidden=True),
) -> None:
    """Configure file logging on every invocation."""
    log_file = configure_logging(log_dir)
    # Intentionally not printing the log path — visible via `wood-league-worker logs` if added later
```

- [ ] **Step 3: Verify help still works**

```bash
wood-league-worker --help
```

Expected: Help text unchanged (callback is hidden).

- [ ] **Step 4: Run full test suite**

```bash
cd services/local_worker
pytest -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 5: Run ruff**

```bash
ruff check local_worker/ tests/
```

Expected: No errors. Fix any that appear.

- [ ] **Step 6: Commit**

```bash
git add local_worker/logging_setup.py local_worker/cli.py
git commit -m "feat(local-worker): rotating file logging and CLI startup wiring"
```

---

## Self-Review

### Spec Coverage

| Requirement | Task |
|---|---|
| Uses API to claim and submit work | Task 7 (loop.py — `WorkerClient.checkout` + `complete_*`) |
| Batch processing with configurable size | Task 7 (`batch_size` param) |
| Request Stockfish, Lc0, or both | Task 9 (`run` command engine menu) |
| Configurable node depth (from claim) | Task 7 (`job.nodes or settings.lc0_nodes`) |
| Syzygy tablebase support | Tasks 5 + 6 (`syzygy_path` param to engine) |
| Modern Python CLI | Task 9 (Typer) |
| Menus for engine/batch settings | Task 9 (questionary selects + prompts) |
| Batch size and batch time | Task 9 (`run` command options) |
| Internal stats tracking (games, avg time) | Task 7 (WorkerStats dataclass) |
| Analyse specific game by game_id | Task 9 (`analyze` command) |
| Persist API key | Task 2 (config.py + platformdirs) |
| Rich progress bars | Task 8 (display.py) |
| Warnings/errors in accessible location | Task 10 (rotating log file) |
| Auto-detect lc0 (CUDA, Metal) | Task 4 (detector.py) |
| Cross-platform Windows/Mac/Linux | Tasks 2 + 4 (platformdirs, shutil.which) |
| Configurable thread counts, memory | Tasks 4 + 9 (suggest + setup wizard) |

### analysis-math.md spec coverage (delta from legacy)

| Spec point | Implementation |
|---|---|
| Win% canonical form | `math.win_pct` uses `100/(1+exp(-0.00368208·cp))` |
| Move accuracy without `+1` | `math.move_accuracy` matches spec exactly |
| Mate scores flat at ±10000 | `_white_cp` calls `score(mate_score=MATE_SCORE)`; CPL test covers two-mate case |
| CPL sign per side | `math.cpl_from_evals(eval_before_cp, eval_after_cp, mover_is_white=…)` |
| Game accuracy windowed std-dev | `math.game_accuracy(accs, win_pcts=…)` with `_WINDOW_SIZE=8` |
| ACPL per player | Stockfish + Lc0 analysers split into `white_cpls` / `black_cpls` and average each |
| Capture/sacrifice = SEE | `analysis/see.py` (`see_capture_or_sacrifice`); used by both engine analysers |
| Lc0 Q→cp precise constants | `_Q_CP_SCALE = 111.714640912`, `_Q_CP_INNER = 1.5620688421` |
| Classification first-match-wins | Top-down `if`/`return` ladders in `classify_stockfish_move` and `classify_lc0_move` |

### No Placeholders

Reviewed — no TBD/TODO present in code blocks.

### Type Consistency

- `WorkerStats` defined in Task 7, used in Tasks 8 and 9 ✓
- `Settings` defined in Task 2, used in Tasks 7 and 9 ✓
- `StockfishGameResult` / `Lc0GameResult` defined in Task 3 models, used in Tasks 5 and 6 ✓
- `classify_*_move` parameter renamed `is_capture` → `is_capture_or_sacrifice` in math.py; both analysers updated ✓
- `game_accuracy` now requires `win_pcts=` kwarg; both analysers track per-player Win% before each move ✓
- `cpl_from_evals` is the single source of CPL truth (no inline `max(0, …)` elsewhere) ✓
- `build_stockfish_payload` / `build_lc0_payload` return dicts passed directly to `client.complete_*` ✓
- `dispatch_mode='pull'` hardcoded in `run_batch` — correct for local workers ✓
- SEE module used by both Stockfish and Lc0 analysers; no piece-value heuristic remains ✓

---
