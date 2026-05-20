"""
Title: test_opening_notation.py
Description: Tests for truncated PGN move-list rendering.
Changelog:
    2026-05-20: Initial creation (#162).
"""
from games.opening_notation import opening_notation


PGN_5PLY = """[Event "test"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 *"""
PGN_10PLY = """[Event "test"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 *"""
PGN_30PLY = """[Event "test"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 11. Nbd2 Bb7 12. Bc2 Re8 13. Nf1 Bf8 14. Ng3 g6 15. a4 c5 *"""


def test_opening_notation_empty():
    assert opening_notation("") == ""


def test_opening_notation_short_returns_all():
    assert opening_notation(PGN_5PLY) == "1. e4 e5 2. Nf3 Nc6 3. Bb5"


def test_opening_notation_exactly_max_no_ellipsis():
    assert opening_notation(PGN_10PLY, max_plies=10) == \
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7"


def test_opening_notation_truncates_with_ellipsis():
    out = opening_notation(PGN_30PLY, max_plies=10)
    assert out.endswith("…")
    assert out.startswith("1. e4 e5 2. Nf3 Nc6")
    assert " 6." not in out


def test_opening_notation_handles_malformed_pgn():
    assert opening_notation("not a pgn at all") == ""
