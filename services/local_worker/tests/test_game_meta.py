"""
Title: test_game_meta.py — Tests for PGN header extraction
Description:
    Verifies parse_game_meta handles full headers, missing tags, PGN
    placeholders, malformed input, and event truncation.

Changelog:
    2026-05-11: Initial creation.
"""
from local_worker.game_meta import GameMeta, parse_game_meta


_FULL_PGN = """[Event "Wood League Round 3"]
[Site "Online"]
[Date "2026.05.04"]
[White "Chris"]
[Black "Sean"]
[Result "1-0"]

1. e4 e5 1-0
"""


def test_full_headers_round_trip():
    meta = parse_game_meta(_FULL_PGN)
    assert meta == GameMeta(
        matchup="Chris vs. Sean",
        date="2026-05-04",
        event="Wood League Round 3",
    )


def test_missing_players_yields_empty_matchup():
    pgn = '[White "Chris"]\n[Date "2026.05.04"]\n\n*\n'
    meta = parse_game_meta(pgn)
    assert meta.matchup == ""
    assert meta.date == "2026-05-04"


def test_placeholder_values_are_dropped():
    pgn = (
        '[Event "?"]\n'
        '[Date "????.??.??"]\n'
        '[White "Unknown"]\n'
        '[Black "Sean"]\n\n*\n'
    )
    meta = parse_game_meta(pgn)
    assert meta.matchup == ""  # White was placeholder
    assert meta.date == ""
    assert meta.event == ""


def test_malformed_date_passes_through():
    pgn = '[White "Chris"]\n[Black "Sean"]\n[Date "spring 2026"]\n\n*\n'
    meta = parse_game_meta(pgn)
    assert meta.date == "spring 2026"


def test_empty_pgn_returns_empty_meta():
    assert parse_game_meta("") == GameMeta("", "", "")


def test_unparseable_pgn_returns_empty_meta():
    assert parse_game_meta("not a pgn at all").matchup == ""


def test_long_event_is_truncated():
    long_name = "A" * 50
    pgn = f'[Event "{long_name}"]\n[White "C"]\n[Black "S"]\n\n*\n'
    meta = parse_game_meta(pgn)
    assert len(meta.event) <= 30
    assert meta.event.endswith("…")
