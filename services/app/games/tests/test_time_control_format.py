"""
Title: test_time_control_format.py
Description: Tests for the human-readable time-control formatter.
Changelog:
    2026-05-20: Initial creation (#162).
    2026-05-29: Add tests for format_time_control_label (#226).
"""
import pytest

from games.time_control_format import format_time_control, format_time_control_label


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


# ---------------------------------------------------------------------------
# format_time_control_label tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("time_class,base,inc,expected", [
    ("rapid",  600,    5,    "Rapid · 10+5 min"),
    ("daily",  259200, None, "Daily · 3 days per move"),
    ("",       180,    0,    "3 min"),
    ("blitz",  None,   None, ""),
])
def test_format_time_control_label_known_shapes(time_class, base, inc, expected):
    """format_time_control_label composes a title-cased prefix with the body."""
    assert format_time_control_label(time_class, base, inc) == expected


def test_format_time_control_label_none_class():
    """None time_class behaves the same as empty string — bare body returned."""
    assert format_time_control_label(None, 600, 0) == "10 min"


def test_format_time_control_label_raw_fallback():
    """When base is None but raw is provided, raw is used as body with prefix."""
    assert format_time_control_label("rapid", None, None, raw="10+5") == "Rapid · 10+5"
