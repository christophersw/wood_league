"""
Title: models.py — Site-wide singleton settings
Description: Holds toggles that apply to the whole installation, currently the
    auto-enqueue flags for new Chess.com games per analysis engine.
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
"""
from __future__ import annotations

from django.db import models


class SiteSettings(models.Model):
    """Singleton row of site-wide configuration. Always pk=1."""

    auto_enqueue_stockfish = models.BooleanField(
        default=True,
        help_text="Auto-enqueue Stockfish AnalysisJob for newly ingested games.",
    )
    auto_enqueue_lc0 = models.BooleanField(
        default=False,
        help_text="Auto-enqueue Lc0 AnalysisJob for newly ingested games.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "site_settings"
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"

    def __str__(self) -> str:
        """Return a stable label for the singleton row."""
        return "Site settings"

    @classmethod
    def get_solo(cls) -> "SiteSettings":
        """Return the singleton row, creating it on first access.

        Args:
            None

        Returns:
            SiteSettings: The single persistent row (pk=1).

        Side effects:
            Creates the row if it does not yet exist.
        """
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
