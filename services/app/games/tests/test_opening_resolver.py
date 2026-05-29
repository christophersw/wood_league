"""
Title: test_opening_resolver.py
Description: Tests resolve_opening_id walks the PGN through the OpeningBook
    and returns the deepest matching opening id.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest

from games.opening_resolver import resolve_opening_id


@pytest.fixture
def patched_lookup(monkeypatch):
    """Patch lookup_opening_entry to a scripted sequence.

    Each call corresponds to one board position; returning None on the
    deeper boards mirrors a real walk that exits the book.

    resolve_opening_id delegates to games.opening_book_context.book_context,
    so the lookup is patched on that module (where the walk actually runs).
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


def test_resolve_returns_deepest_hit(patched_lookup):
    patched_lookup([
        (1, "B00", "King's Pawn"),       # start
        (1, "B00", "King's Pawn"),       # after 1. e4
        (7, "C40", "King's Knight"),     # after 1...e5
        None,                            # after 2. Nf3 — exits book
    ])
    pgn = """[Event "t"]\n\n1. e4 e5 2. Nf3 Nc6 *"""
    assert resolve_opening_id(pgn) == 7


def test_resolve_no_hits(patched_lookup):
    patched_lookup([None])
    assert resolve_opening_id("[Event \"t\"]\n\n1. a3 *") is None


def test_resolve_empty_pgn():
    assert resolve_opening_id("") is None


def test_resolve_malformed_pgn(patched_lookup):
    patched_lookup([])
    assert resolve_opening_id("garbage not pgn") is None
