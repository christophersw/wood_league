"""
Title: test_chart_data.py — Tests for the chart_data module
Description:
    Verifies that chart_data payload builders produce correctly shaped dicts
    for the SF CP and LC0 WDL charts.

Changelog:
    2026-05-21 (#186): Initial.
    2026-05-27 (#216): Add test_lc0_wdl_payload_includes_classification.
    2026-05-27 (#216): Task 8 — remove winpct_payload tests (chart retired).
"""
import pytest

from games.chart_data import sf_cp_payload, lc0_wdl_payload
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


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


def test_lc0_wdl_payload_includes_classification(new_schema_game_factory):
    """Each ply entry carries a `classification` string from base_severity, lowercased."""
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    payload = lc0_wdl_payload(data)
    assert payload
    for row in payload:
        assert isinstance(row["classification"], str)
    # Pin the .lower() normalisation against a known fixture value (ply 1 = "best").
    assert payload[0]["classification"] == "best"
