"""
Tests for chart_data module.
"""
import pytest

from games.chart_data import winpct_payload, sf_cp_payload, lc0_wdl_payload
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_winpct_payload_overlays_sf_and_lc0(new_schema_game_factory):
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    payload = winpct_payload(data)
    assert payload["sf"] and payload["lc0"]
    sf0 = payload["sf"][0]
    # #188: both engines read Win% from stored White-frame WDL — no sigmoid.
    m0 = data.sf_moves[0]
    expected_sf = (m0.wdl_win_adj + m0.wdl_draw_adj / 2) / 1000.0 * 100.0
    assert sf0["winpct"] == pytest.approx(expected_sf, abs=0.01)
    assert payload["lc0"][0]["winpct"] == pytest.approx(data.lc0_moves[0].wdl_mu * 100, abs=0.01)


def test_winpct_payload_skips_sf_moves_without_wdl(new_schema_game_factory):
    """SF moves lacking a WDL triple drop from the chart (missing-WDL fallback)."""
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    data.sf_moves[0].wdl_win_adj = None
    payload = winpct_payload(data)
    assert all(row["ply"] != data.sf_moves[0].ply for row in payload["sf"])


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
