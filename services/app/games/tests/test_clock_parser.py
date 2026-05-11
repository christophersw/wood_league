"""
Title: test_clock_parser.py — Tests for chess.com PGN %clk parsing.
Description:
    Verifies parse_move_times for live games (clock-delta math) and daily
    games (deciseconds-as-seconds scaling), plus edge cases like empty
    PGNs, malformed input, and clock anomalies that produce negative
    deltas.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from games.clock_parser import MoveTime, parse_move_times


_LIVE_PGN_3_PLUS_0 = """[Event "Live Chess"]
[TimeControl "180"]

1. e4 {[%clk 0:03:00]} 1... c5 {[%clk 0:02:58]} 2. Nf3 {[%clk 0:02:55]} 2... d6 {[%clk 0:02:50]} 1-0
"""


def test_live_3_plus_0_time_spent_per_ply():
    """3-minute game with no increment: time spent on each move = previous clk - current clk."""
    result = parse_move_times(
        _LIVE_PGN_3_PLUS_0, time_class="blitz",
        time_control_base_s=180, time_control_increment_s=0,
    )
    assert len(result) == 4
    # Move 1 (White): started with 180s, played e4 with 180s left -> spent 0s
    assert result[0] == MoveTime(ply=1, time_spent_ms=0, clock_after_ms=180_000)
    # Move 2 (Black): started with 180s, played c5 with 178s left -> spent 2s
    assert result[1] == MoveTime(ply=2, time_spent_ms=2_000, clock_after_ms=178_000)
    # Move 3 (White): previous White clk was 180s, now 175s -> spent 5s
    assert result[2] == MoveTime(ply=3, time_spent_ms=5_000, clock_after_ms=175_000)
    # Move 4 (Black): previous Black clk was 178s, now 170s -> spent 8s
    assert result[3] == MoveTime(ply=4, time_spent_ms=8_000, clock_after_ms=170_000)


_LIVE_PGN_5_PLUS_3 = """[Event "Live Chess"]
[TimeControl "300+3"]

1. e4 {[%clk 0:05:01]} 1... e5 {[%clk 0:05:03]} 1-0
"""


def test_live_with_increment_added_back():
    """Increment is added to previous-clk before subtracting current-clk.

    For 5+3 starting clock: each side starts with 300s. After move 1, the
    %clk reflects (300 - time_spent + 3). White's 0:05:01 = 301s means
    time_spent = 300 + 3 - 301 = 2s. Black's 0:05:03 = 303s means
    time_spent = 300 + 3 - 303 = 0s.
    """
    result = parse_move_times(
        _LIVE_PGN_5_PLUS_3, time_class="rapid",
        time_control_base_s=300, time_control_increment_s=3,
    )
    assert result[0] == MoveTime(ply=1, time_spent_ms=2_000, clock_after_ms=301_000)
    assert result[1] == MoveTime(ply=2, time_spent_ms=0, clock_after_ms=303_000)


_LIVE_PGN_ANOMALY = """[Event "Live Chess"]
[TimeControl "180"]

1. e4 {[%clk 0:03:01]} 1-0
"""


def test_live_clock_anomaly_clamps_to_zero():
    """If %clk > previous clk + increment (server hiccup / reconnect), clamp to 0.

    White starts with 180s, no increment, plays e4 with 181s left.
    Naive math gives -1s; we clamp to 0 rather than reporting impossible times.
    """
    result = parse_move_times(
        _LIVE_PGN_ANOMALY, time_class="bullet",
        time_control_base_s=180, time_control_increment_s=0,
    )
    assert result[0].time_spent_ms == 0
