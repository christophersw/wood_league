"""
Title: test_opening_book_context.py
Description: Tests for book_context — verifies the PGN walk returns the
    deepest matched opening entry plus leading book-ply count.
Changelog:
    2026-05-29: Initial creation (#226).
"""
import pytest

from games.opening_book_context import BookContext, book_context


@pytest.fixture
def patched_lookup(monkeypatch):
    """Patch openings.services.lookup_opening_entry to a scripted call sequence.

    Each call corresponds to one board position (start position, then after
    each half-move). Returning None mirrors a real walk that exits the book.

    Returns:
        Callable: A factory accepting a sequence of return values to install.
    """
    calls = {"n": 0}

    def factory(seq):
        def fake(_board):
            i = calls["n"]
            calls["n"] += 1
            return seq[i] if i < len(seq) else None
        monkeypatch.setattr(
            "games.opening_book_context.lookup_opening_entry", fake
        )
        return calls

    return factory


def test_book_context_empty_pgn():
    """Empty PGN yields the zero-book sentinel BookContext."""
    result = book_context("")
    assert result == BookContext(opening_id=None, eco="", name="", book_ply_count=0)


def test_book_context_unparseable_pgn(patched_lookup):
    """Garbage PGN yields book_ply_count == 0 without raising.

    chess.pgn.read_game does not raise on garbage — it returns a game
    object with no moves. We patch lookup_opening_entry so no DB is needed,
    and verify the walk produces a zero-book result.
    """
    # The start position lookup returns None — nothing matches, no plies counted.
    patched_lookup([None])
    result = book_context("garbage not pgn")
    assert result.book_ply_count == 0
    assert result.opening_id is None


def test_book_context_returns_deepest_hit(patched_lookup):
    """Walk stops at the first miss; deepest prior hit is returned with correct ply."""
    # Start pos hit (ignored from count), then hits at ply 1 and 2, miss at ply 3.
    patched_lookup([
        (1, "B00", "King's Pawn"),    # start position
        (1, "B00", "King's Pawn"),    # after 1. e4 (ply 1)
        (7, "C40", "King's Knight"),  # after 1...e5 (ply 2) — deepest
        None,                          # after 2. Nf3 (ply 3) — exits book
    ])
    pgn = '[Event "t"]\n\n1. e4 e5 2. Nf3 Nc6 *'
    result = book_context(pgn)
    assert result.opening_id == 7
    assert result.eco == "C40"
    assert "Knight" in result.name
    assert result.book_ply_count == 2


def test_book_context_no_hits(patched_lookup):
    """When even the start position has no book entry, return the zero sentinel."""
    patched_lookup([None])
    result = book_context('[Event "t"]\n\n1. a3 *')
    assert result == BookContext(opening_id=None, eco="", name="", book_ply_count=0)


def test_book_context_all_moves_in_book(patched_lookup):
    """When every position matches, book_ply_count equals the move count."""
    patched_lookup([
        (1, "B00", "King's Pawn"),    # start
        (2, "B01", "King's Pawn"),    # ply 1
        (3, "C40", "King's Knight"),  # ply 2
        (4, "C41", "Philidor"),       # ply 3
        (5, "C42", "Russian"),        # ply 4
    ])
    pgn = '[Event "t"]\n\n1. e4 e5 2. Nf3 Nc6 *'
    result = book_context(pgn)
    assert result.opening_id == 5
    assert result.book_ply_count == 4
