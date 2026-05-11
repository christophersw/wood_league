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


# Real PGN fragment from chess.com API (game 948193485, daily 1/604800).
# Each API %clk value × 10 gives the actual inter-move delay in seconds.
_DAILY_API_PGN = """[Event "Let's Play!"]
[TimeControl "1/604800"]

1. e4 {[%clk 0:00:00.5]} 1... c6 {[%clk 0:30:05.2]} 2. d4 {[%clk 0:05:21.7]} 1-0
"""


def test_daily_clk_treated_as_deciseconds_scaled():
    """In the API daily PGN, %clk seconds × 10 = real inter-move delay seconds.

    Move 1 e4: %clk 0:00:00.5 = 0.5s api -> 5000ms real spent.
    Move 2 c6: %clk 0:30:05.2 = 1805.2s api -> 18,052,000ms real spent.
    Move 3 d4: %clk 0:05:21.7 = 321.7s api -> 3,217,000ms real spent.
    """
    result = parse_move_times(_DAILY_API_PGN, time_class="daily")
    assert len(result) == 3
    assert result[0] == MoveTime(ply=1, time_spent_ms=5_000, clock_after_ms=None)
    assert result[1] == MoveTime(ply=2, time_spent_ms=18_052_000, clock_after_ms=None)
    assert result[2] == MoveTime(ply=3, time_spent_ms=3_217_000, clock_after_ms=None)


def test_empty_pgn_returns_empty_list():
    assert parse_move_times("", time_class="blitz", time_control_base_s=180) == []


def test_pgn_without_clk_returns_empty_list():
    """Pre-2020 daily games carry no %clk annotations; caller handles game-level only."""
    old_pgn = """[Event "Old Game"]
[TimeControl "1/86400"]

1. e4 e5 2. Nf3 Nc6 1-0
"""
    assert parse_move_times(old_pgn, time_class="daily") == []


def test_live_missing_base_treats_as_zero():
    """Defensive: if base is missing (unparseable time_control), every spent_ms is 0.

    Not ideal but doesn't crash. The parser is best-effort; the caller decides
    whether to suppress writes for these rows.
    """
    pgn = """[Event "?"]
[TimeControl "?"]

1. e4 {[%clk 0:03:00]} 1-0
"""
    # base_s defaults to None -> 0; current clk 180_000 -> spent (0+0)-180_000 = -180_000 -> clamped 0
    result = parse_move_times(pgn, time_class="blitz")
    assert result[0].time_spent_ms == 0
    assert result[0].clock_after_ms == 180_000
