"""
Title: test_time_control_format.py
Description: Tests for the human-readable time-control formatter.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest

from games.time_control_format import format_time_control


@pytest.mark.parametrize("base,inc,expected", [
    (86400, 0, "1 day per move"),
    (172800, 0, "2 days per move"),
    (259200, None, "3 days per move"),
    (900, 10, "15+10 min"),
    (600, 5, "10+5 min"),
    (180, 0, "3 min"),
    (60, 0, "1 min"),
    (30, 0, "30+0 sec"),
    (30, 2, "30+2 sec"),
])
def test_format_time_control_known_shapes(base, inc, expected):
    assert format_time_control(base, inc) == expected


def test_format_time_control_falls_back_to_raw():
    assert format_time_control(None, None, raw="weird/123") == "weird/123"


def test_format_time_control_none_no_raw_returns_empty():
    assert format_time_control(None, None) == ""
