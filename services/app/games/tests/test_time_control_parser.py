"""
Title: test_time_control_parser.py — Tests for chess.com time_control parsing.
Description:
    Verifies parse_time_control covers live formats (with/without increment),
    daily formats (1/N seconds), and gracefully returns (None, None) for
    unknown input.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from games.time_control_parser import parse_time_control


def test_live_no_increment():
    assert parse_time_control("180") == (180, 0)


def test_live_explicit_zero_increment():
    assert parse_time_control("180+0") == (180, 0)


def test_live_with_increment():
    assert parse_time_control("600+5") == (600, 5)


def test_live_long_with_increment():
    assert parse_time_control("1800+30") == (1800, 30)


def test_daily_three_days():
    assert parse_time_control("1/259200") == (259200, None)


def test_daily_one_week():
    assert parse_time_control("1/604800") == (604800, None)


def test_unknown_returns_nones():
    assert parse_time_control("garbage") == (None, None)


def test_empty_returns_nones():
    assert parse_time_control("") == (None, None)
