"""
Title: tests.py — Unit tests for the games app
Description:
    Tests for game analysis data assembly (services), board frame generation
    (board_builder), and live view helper functions (views). Does not test
    database models. Legacy stat_cards tests removed in Task 15 (#186).

Changelog:
    2026-05-21 (#186): Task 15 — removed ViewHelperTest, AccColorTest, BarRowTest,
                       QualityRowTest, RerunButtonTest, BuildSfCardTest,
                       BuildLc0CardTest, BuildStatCardsHtmlTest (stat_cards deleted)
    2026-05-05 (#16): Added engine-line continuation tests for stored PV SAN usage
    2026-05-04 (#16): Initial test suite for the game analysis page rewrite
"""

import json
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from games.board_builder import _build_tier_map, build_board_frames
from games.services import GameAnalysisData, MoveRow
from games.views import (
    _continuation_san_moves_from_row,
    _parse_pv_san_moves,
    engine_line_partial,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_PGN = (
    "[Event \"?\"]\n[Site \"?\"]\n[Date \"????.??.??\"]\n[Round \"?\"]\n"
    "[White \"White\"]\n[Black \"Black\"]\n[Result \"*\"]\n\n"
    "1. e4 e5 2. Nf3 Nc6 *"
)

MOVE_E4 = MoveRow(ply=1, san="e4",
                  fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                  cp_eval=30, arrow_uci="e2e4", classification="best")
MOVE_E5 = MoveRow(ply=2, san="e5",
                  fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
                  cp_eval=-20, classification="best")
MOVE_NF3 = MoveRow(ply=3, san="Nf3",
                   fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
                   cp_eval=35, arrow_uci="g1f3", classification="best")
MOVE_NC6 = MoveRow(ply=4, san="Nc6",
                   fen="r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
                   cp_eval=-25, classification="best")


def _minimal_data(**kwargs) -> GameAnalysisData:
    """Return a minimal GameAnalysisData for testing."""
    defaults = dict(
        game_id="test-id",
        white="White",
        black="Black",
        result="*",
        pgn=MINIMAL_PGN,
        moves=[MOVE_E4, MOVE_E5, MOVE_NF3, MOVE_NC6],
    )
    defaults.update(kwargs)
    return GameAnalysisData(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GameAnalysisData properties
# ---------------------------------------------------------------------------

class GameAnalysisDataPropertiesTest(TestCase):
    """Tests for GameAnalysisData computed properties."""

    def test_has_sf_true_with_accuracy(self):
        """has_sf returns True when white_accuracy is set."""
        data = _minimal_data(white_accuracy=85.0)
        self.assertTrue(data.has_sf)

    def test_has_sf_true_with_acpl(self):
        """has_sf returns True when white_acpl is set."""
        data = _minimal_data(white_acpl=40.0)
        self.assertTrue(data.has_sf)

    def test_has_sf_false_with_no_stats(self):
        """has_sf returns False with no accuracy or acpl data."""
        data = _minimal_data()
        self.assertFalse(data.has_sf)

    def test_has_lc0_true_with_moves(self):
        """has_lc0 returns True when lc0_moves is non-empty."""
        lc0_move = MoveRow(ply=1, san="e4", fen="", wdl_win=600, wdl_draw=300, wdl_loss=100)
        data = _minimal_data(lc0_moves=[lc0_move])
        self.assertTrue(data.has_lc0)

    def test_has_lc0_false_with_empty_list(self):
        """has_lc0 returns False when lc0_moves is empty list."""
        data = _minimal_data(lc0_moves=[])
        self.assertFalse(data.has_lc0)

    def test_has_lc0_false_with_none(self):
        """has_lc0 returns False when lc0_moves is None."""
        data = _minimal_data(lc0_moves=None)
        self.assertFalse(data.has_lc0)

    def test_white_label_with_rating(self):
        """white_label includes rating when available."""
        data = _minimal_data(white_rating=1500)
        self.assertEqual(data.white_label, "White (1500)")

    def test_black_label_without_rating(self):
        """black_label returns plain name when no rating."""
        data = _minimal_data()
        self.assertEqual(data.black_label, "Black")


# ---------------------------------------------------------------------------
# _build_tier_map
# ---------------------------------------------------------------------------

class BuildTierMapTest(TestCase):
    """Tests for the _build_tier_map helper function."""

    def test_returns_empty_dict_for_empty_input(self):
        """_build_tier_map returns empty dict when no moves given."""
        result = _build_tier_map({}, use_cp_equiv=False)
        self.assertEqual(result, {})

    def test_includes_ply_with_arrow(self):
        """_build_tier_map includes entries for plies that have an arrow_uci."""
        row = MoveRow(ply=1, san="e4", fen="", arrow_uci="e2e4", arrow_cp_1=30.0)
        result = _build_tier_map({1: row}, use_cp_equiv=False)
        self.assertIn(1, result)
        self.assertEqual(result[1][0]["uci"], "e2e4")

    def test_excludes_ply_without_arrow(self):
        """_build_tier_map omits plies where arrow_uci is empty."""
        row = MoveRow(ply=1, san="e4", fen="", arrow_uci="")
        result = _build_tier_map({1: row}, use_cp_equiv=False)
        self.assertNotIn(1, result)

    def test_uses_cp_equiv_as_primary_fallback(self):
        """_build_tier_map backfills the first score from cp_equiv when needed."""
        row = MoveRow(ply=1, san="e4", fen="", arrow_uci="e2e4", cp_equiv=150.0)
        result = _build_tier_map({1: row}, use_cp_equiv=True)
        self.assertEqual(result[1][0]["score"], 150.0)

    def test_preserves_secondary_scores_for_lc0(self):
        """_build_tier_map keeps tier-two and tier-three scores for Lc0 arrows."""
        row = MoveRow(
            ply=1,
            san="e4",
            fen="",
            arrow_uci="e2e4",
            arrow_uci_2="d2d4",
            arrow_uci_3="g1f3",
            cp_equiv=150.0,
            arrow_cp_2=110.0,
            arrow_cp_3=80.0,
        )
        result = _build_tier_map({1: row}, use_cp_equiv=True)
        self.assertEqual(result[1][0]["score"], 150.0)
        self.assertEqual(result[1][1]["score"], 110.0)
        self.assertEqual(result[1][2]["score"], 80.0)


# ---------------------------------------------------------------------------
# Engine line continuation helpers
# ---------------------------------------------------------------------------

class EngineLineContinuationHelperTest(TestCase):
    """Tests for stored engine-line continuation helpers."""

    def test_parse_pv_san_moves_reads_json_list(self):
        """_parse_pv_san_moves parses a JSON-encoded SAN list."""
        result = _parse_pv_san_moves('["e4", "e5", "Nf3"]')
        self.assertEqual(result, ["e4", "e5", "Nf3"])

    def test_continuation_helper_skips_clicked_move_when_present(self):
        """_continuation_san_moves_from_row omits the already-played clicked move."""
        row = MoveRow(
            ply=1,
            san="e4",
            fen=MOVE_E4.fen,
            arrow_uci="e2e4",
            pv_san_1='["e4", "e5", "Nf3", "Nc6"]',
        )

        result = _continuation_san_moves_from_row(row, 1, "e4")

        self.assertEqual(result, ["e5", "Nf3", "Nc6"])


# ---------------------------------------------------------------------------
# build_board_frames
# ---------------------------------------------------------------------------

class BuildBoardFramesTest(TestCase):
    """Tests for the build_board_frames function."""

    def test_returns_dict_with_expected_keys(self):
        """build_board_frames returns a dict with all required keys."""
        data = _minimal_data()
        result = build_board_frames(data, size=480, orientation="white")
        for key in ["frames", "arrows_by_ply", "san_list", "total_frames",
                    "top_player", "bottom_player", "has_sf", "has_lc0", "overlay_geometry"]:
            self.assertIn(key, result)

    def test_frame_count_equals_moves_plus_one(self):
        """build_board_frames produces one frame per move plus one for the start position."""
        data = _minimal_data()
        result = build_board_frames(data, size=480, orientation="white")
        self.assertEqual(result["total_frames"], len(data.moves) + 1)

    def test_san_list_matches_moves(self):
        """build_board_frames san_list contains move SAN strings in order."""
        data = _minimal_data()
        result = build_board_frames(data, size=480, orientation="white")
        self.assertEqual(len(result["san_list"]), len(data.moves))
        self.assertEqual(result["san_list"][0], "e4")

    def test_black_orientation_swaps_players(self):
        """build_board_frames places Black at bottom when orientation='black'."""
        data = _minimal_data()
        result = build_board_frames(data, size=480, orientation="black")
        self.assertEqual(result["bottom_player"], data.black)
        self.assertEqual(result["top_player"], data.white)

    def test_frames_are_svg_strings(self):
        """build_board_frames frames are SVG strings."""
        data = _minimal_data()
        result = build_board_frames(data, size=480, orientation="white")
        self.assertTrue(result["frames"][0].startswith("<svg"))

    def test_returns_clickable_arrow_metadata(self):
        """build_board_frames returns per-ply overlay metadata for suggested moves."""
        move_with_tiers = MoveRow(
            ply=1,
            san="e4",
            fen=MOVE_E4.fen,
            cp_eval=30,
            arrow_uci="e2e4",
            arrow_uci_2="d2d4",
            arrow_uci_3="g1f3",
            arrow_cp_1=60.0,
            arrow_cp_2=35.0,
            arrow_cp_3=10.0,
            classification="best",
        )
        data = _minimal_data(moves=[move_with_tiers, MOVE_E5, MOVE_NF3, MOVE_NC6], white_accuracy=85.0)

        result = build_board_frames(data, size=480, orientation="white")

        self.assertIn(1, result["arrows_by_ply"])
        self.assertEqual(len(result["arrows_by_ply"][1]), 3)
        first_arrow = result["arrows_by_ply"][1][0]
        self.assertEqual(first_arrow["move_uci"], "e2e4")
        self.assertEqual(first_arrow["engine"], "sf")
        self.assertEqual(first_arrow["tier"], 1)
        self.assertEqual(first_arrow["request_ply"], 0)
        self.assertIn("delta_text", first_arrow)
        self.assertIn("opacity", first_arrow)
        self.assertIn("stroke_width", first_arrow)
        self.assertEqual(first_arrow["stroke_width"], 11.5)

    def test_arrow_sizes_are_uniform_across_tiers(self):
        """build_board_frames keeps rendered arrow widths uniform across move ranks."""
        move_with_tiers = MoveRow(
            ply=1,
            san="e4",
            fen=MOVE_E4.fen,
            cp_eval=30,
            arrow_uci="e2e4",
            arrow_uci_2="d2d4",
            arrow_uci_3="g1f3",
            arrow_cp_1=60.0,
            arrow_cp_2=35.0,
            arrow_cp_3=10.0,
            classification="best",
        )
        data = _minimal_data(moves=[move_with_tiers, MOVE_E5, MOVE_NF3, MOVE_NC6], white_accuracy=85.0)

        result = build_board_frames(data, size=480, orientation="white")
        stroke_widths = {arrow["stroke_width"] for arrow in result["arrows_by_ply"][1]}

        self.assertEqual(stroke_widths, {11.5})

    def test_overlay_geometry_matches_board_size(self):
        """build_board_frames exposes board-overlay geometry for the client renderer."""
        data = _minimal_data()
        result = build_board_frames(data, size=480, orientation="white")
        geometry = result["overlay_geometry"]
        self.assertEqual(geometry["viewbox_size"], 390.0)
        self.assertEqual(geometry["board_margin"], 15.0)
        self.assertEqual(geometry["square_size"], 45.0)

    def test_move_classification_colors_lastmove_squares(self):
        """build_board_frames tints played-move squares with the move classification color."""
        data = _minimal_data(white_accuracy=85.0)
        result = build_board_frames(data, size=480, orientation="white")

        self.assertIn("#4A6E8A", result["frames"][1])

    def test_returns_only_start_frame_for_pgn_with_no_moves(self):
        """build_board_frames returns only the start-position frame when PGN has no moves."""
        no_moves_pgn = "[Event \"?\"]\n[White \"W\"]\n[Black \"B\"]\n[Result \"*\"]\n\n*"
        data = _minimal_data(pgn=no_moves_pgn, moves=[])
        result = build_board_frames(data, size=480, orientation="white")
        self.assertEqual(len(result["frames"]), 1)
        self.assertEqual(result["san_list"], [])


# ---------------------------------------------------------------------------
# engine_line_partial
# ---------------------------------------------------------------------------

class EngineLinePartialTest(TestCase):
    """Tests for engine_line_partial continuation rendering."""

    def setUp(self):
        """Create a request factory for direct view calls."""
        self.factory = RequestFactory()

    def test_uses_all_stored_pv_moves_for_continuation(self):
        """engine_line_partial renders all stored continuation SAN moves for the selected tier."""
        pv_move = MoveRow(
            ply=1,
            san="e4",
            fen=MOVE_E4.fen,
            cp_eval=30,
            arrow_uci="e2e4",
            pv_san_1='["e4", "e5", "Nf3", "Nc6"]',
            classification="best",
        )
        data = _minimal_data(
            moves=[pv_move, MOVE_E5, MOVE_NF3, MOVE_NC6],
            white_accuracy=85.0,
        )
        request = self.factory.get(
            "/_partials/games/test-slug/engine-line/",
            {"ply": "0", "move_uci": "e2e4", "engine": "sf", "tier": "1", "orientation": "white", "delta_label": "+30"},
        )

        def fake_render(_request, _template, context):
            return HttpResponse(json.dumps(context), content_type="application/json")

        with patch("games.views.get_object_or_404", return_value=object()), \
             patch("games.views.get_game_analysis", return_value=data), \
             patch("games.views.render", side_effect=fake_render):
            response = engine_line_partial(request, "test-slug")

        payload = json.loads(response.content)
        san_list = json.loads(payload["san_list_json"])
        frames = json.loads(payload["frames_json"])

        self.assertEqual(san_list, ["e5", "Nf3", "Nc6"])
        self.assertEqual(len(frames), 4)
        self.assertTrue(all("#4A6E8A" in frame for frame in frames))
        self.assertEqual(payload["context_label"], "Best SF (ply 1) +30")


