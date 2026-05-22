"""
Title: test_models.py — SiteSettings singleton tests
Description: Verify SiteSettings.get_solo() returns the same row across calls.
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
    2026-05-22: Replace test_default_toggles with guard for removed fields (#201).
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
def test_auto_enqueue_fields_removed():
    """The auto-enqueue toggles are env-only now (#201); the model must not
    expose them as fields."""
    field_names = {f.name for f in SiteSettings._meta.get_fields()}
    assert "auto_enqueue_stockfish" not in field_names
    assert "auto_enqueue_lc0" not in field_names
