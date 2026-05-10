"""
Title: test_models.py — SiteSettings singleton tests
Description: Verify SiteSettings.get_solo() returns the same row across calls
    and exposes auto_enqueue_stockfish / auto_enqueue_lc0 booleans.
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
"""
import pytest
from core.models import SiteSettings


@pytest.mark.django_db
def test_get_solo_returns_singleton():
    """Calling get_solo() twice returns the same DB row; no duplicates created."""
    a = SiteSettings.get_solo()
    b = SiteSettings.get_solo()
    assert a.pk == b.pk
    assert SiteSettings.objects.count() == 1


@pytest.mark.django_db
def test_default_toggles():
    """Verify default values: stockfish on, lc0 off."""
    s = SiteSettings.get_solo()
    assert s.auto_enqueue_stockfish is True
    assert s.auto_enqueue_lc0 is False
