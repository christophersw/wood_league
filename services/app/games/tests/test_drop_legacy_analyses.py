"""
Title: test_drop_legacy_analyses.py — Tests for drop_legacy_analyses command
Description:
    Tests the drop_legacy_analyses management command, verifying dry-run
    reporting and --apply deletion of legacy SF and LC0 analyses.

Changelog:
    2026-05-21 (#186): Initial tests for drop_legacy_analyses.
"""
import io
from django.core.management import call_command
import pytest

pytestmark = pytest.mark.django_db


def test_dry_run_reports_counts_without_deleting(legacy_sf_game_factory, new_schema_game_factory):
    """Dry-run (default) reports counts without actually deleting."""
    legacy = legacy_sf_game_factory()
    fresh = new_schema_game_factory()
    out = io.StringIO()
    call_command("drop_legacy_analyses", stdout=out)
    text = out.getvalue()
    assert "DRY RUN" in text
    assert "SF analyses to drop: 1" in text
    # Nothing was actually deleted.
    legacy.refresh_from_db()
    assert hasattr(legacy, "analysis")
    fresh.refresh_from_db()
    assert hasattr(fresh, "analysis")


def test_apply_deletes_legacy_only(legacy_sf_game_factory, new_schema_game_factory):
    """--apply flag deletes legacy analyses while preserving new-schema ones."""
    legacy = legacy_sf_game_factory()
    fresh = new_schema_game_factory()
    call_command("drop_legacy_analyses", "--apply")
    legacy.refresh_from_db()
    fresh.refresh_from_db()
    from analysis.models import GameAnalysis
    assert not GameAnalysis.objects.filter(game=legacy).exists()
    assert GameAnalysis.objects.filter(game=fresh).exists()
