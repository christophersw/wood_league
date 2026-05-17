"""
Title: test_stat_cards.py — Move-quality classification rendering tests
Description:
    Regression tests for the analysis-page move-quality bars (issue #131).
    The vast worker and API store Capitalized classification strings
    ("Brilliant"/"Best"/"Great"/"Excellent"); the legacy in-app analysis
    path stored lowercase. The stat-card aggregation must count positive
    classes regardless of casing, and must surface the Excellent class.
    These are pure-function tests (no DB) so they run as SimpleTestCase.

Changelog:
    2026-05-17 (#131): Initial — positive-class casing + Excellent segment
"""

from django.test import SimpleTestCase

from games.services import GameAnalysisData, MoveRow
from games.stat_cards import build_lc0_card, build_sf_card

_PGN = (
    "[Event \"?\"]\n[Site \"?\"]\n[Date \"????.??.??\"]\n[Round \"?\"]\n"
    "[White \"White\"]\n[Black \"Black\"]\n[Result \"*\"]\n\n"
    "1. e4 e5 *"
)


def _data(**kwargs) -> GameAnalysisData:
    """Return a minimal GameAnalysisData with the given overrides."""
    defaults = dict(
        game_id="test-id",
        white="White",
        black="Black",
        result="*",
        pgn=_PGN,
        moves=[MoveRow(ply=1, san="e4", fen="")],
    )
    defaults.update(kwargs)
    return GameAnalysisData(**defaults)  # type: ignore[arg-type]


def _sf_data(classifications: list[str]) -> GameAnalysisData:
    """SF data with one white-side move (odd ply) per classification."""
    moves = [
        MoveRow(ply=1 + 2 * i, san="e4", fen="", classification=cls)
        for i, cls in enumerate(classifications)
    ]
    return _data(moves=moves, white_accuracy=85.0)


def _lc0_data(classifications: list[str]) -> GameAnalysisData:
    """Lc0 data with one white-side move (odd ply) per classification."""
    lc0_moves = [
        MoveRow(
            ply=1 + 2 * i, san="e4", fen="",
            wdl_win=600, wdl_draw=300, wdl_loss=100, classification=cls,
        )
        for i, cls in enumerate(classifications)
    ]
    return _data(
        lc0_moves=lc0_moves,
        lc0_white_win_prob=58.0,
        lc0_white_draw_prob=30.0,
        lc0_white_loss_prob=12.0,
    )


class PositiveClassCasingTest(SimpleTestCase):
    """Positive classes must render regardless of stored casing (#131)."""

    def test_sf_capitalized_positive_classes_render(self):
        """build_sf_card counts Capitalized Brilliant/Best/Great moves."""
        html = build_sf_card(_sf_data(["Brilliant", "Best", "Great"]))
        self.assertIn("dub-bril", html)
        self.assertIn("dub-best", html)
        self.assertIn("dub-great", html)

    def test_sf_lowercase_positive_classes_still_render(self):
        """build_sf_card still counts legacy lowercase brilliant/best/great."""
        html = build_sf_card(_sf_data(["brilliant", "best", "great"]))
        self.assertIn("dub-bril", html)
        self.assertIn("dub-best", html)
        self.assertIn("dub-great", html)

    def test_sf_excellent_class_renders(self):
        """build_sf_card surfaces the Excellent class as its own segment."""
        html = build_sf_card(_sf_data(["Excellent", "Excellent"]))
        self.assertIn("dub-exc", html)

    def test_lc0_capitalized_positive_classes_render(self):
        """build_lc0_card counts Capitalized Brilliant/Best/Great moves."""
        html = build_lc0_card(_lc0_data(["Brilliant", "Best", "Great"]))
        self.assertIn("dub-bril", html)
        self.assertIn("dub-best", html)
        self.assertIn("dub-great", html)

    def test_lc0_excellent_class_renders(self):
        """build_lc0_card surfaces the Excellent class as its own segment."""
        html = build_lc0_card(_lc0_data(["Excellent", "Excellent"]))
        self.assertIn("dub-exc", html)
