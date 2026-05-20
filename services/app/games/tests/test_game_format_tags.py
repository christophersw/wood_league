"""
Title: test_game_format_tags.py — Template-tag unit tests
Description: Asserts the formatter and band-class tags emit the right
    strings without rendering a full template.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest

from games.templatetags.game_format import (
    accuracy_band_class,
    club_accuracy_chips,
    opening_notation_filter,
    time_control_human,
)


class FakeGame:
    """Stand-in for a Game model with the attributes the tags read."""

    def __init__(self, **kw):
        self.time_control_base_s = kw.get("base")
        self.time_control_increment_s = kw.get("inc")
        self.time_control = kw.get("raw", "")
        self.pgn = kw.get("pgn", "")


def test_time_control_human():
    """time_control_human should format base+increment in minutes."""
    g = FakeGame(base=900, inc=10)
    assert time_control_human(g) == "15+10 min"


def test_opening_notation_filter_default_max_10():
    """opening_notation_filter should truncate to first 10 plies by default."""
    pgn = "[Event \"t\"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 *"
    assert opening_notation_filter(pgn) == "1. e4 e5 2. Nf3 Nc6 3. Bb5"


@pytest.mark.parametrize("acc,expected", [
    (95, "wc-chip wc-chip--band-strong"),
    (85, "wc-chip wc-chip--band-good"),
    (75, "wc-chip wc-chip--band-fair"),
    (65, "wc-chip wc-chip--band-weak"),
    (40, "wc-chip wc-chip--band-poor"),
    (None, "wc-chip wc-chip--band-unknown"),
])
def test_accuracy_band_class(acc, expected):
    """accuracy_band_class should map accuracy values to correct chip classes."""
    assert accuracy_band_class(acc) == expected


def test_club_accuracy_chips_only_club_members():
    """club_accuracy_chips should return chips only for club-member sides."""
    chips = club_accuracy_chips(
        white_username="chris", black_username="strangerbot",
        club_usernames={"chris": "Chris"},
        sf_white=87, sf_black=70, lc0_white=78, lc0_black=None,
    )
    assert len(chips) == 1
    assert chips[0]["display_name"] == "Chris"
    assert chips[0]["sf"] == 87
    assert chips[0]["lc0"] == 78
    assert "wc-chip--band-good" in chips[0]["band_class"]


def test_club_accuracy_chips_omits_missing_engine():
    """club_accuracy_chips should pass None for engines with no data."""
    chips = club_accuracy_chips(
        white_username="chris", black_username="alice",
        club_usernames={"chris": "Chris", "alice": "Alice"},
        sf_white=87, sf_black=None, lc0_white=None, lc0_black=80,
    )
    assert len(chips) == 2
    chris, alice = chips
    assert chris["sf"] == 87 and chris["lc0"] is None
    assert alice["sf"] is None and alice["lc0"] == 80
