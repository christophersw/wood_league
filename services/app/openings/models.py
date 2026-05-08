"""
Title: models.py — Database models for chess openings
Description:
    Defines the OpeningBook model representing chess openings by ECO code,
    name, PGN, and final EPD (endgame position description) for lookup.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.db import models


class OpeningBook(models.Model):
    """Chess opening stored as ECO code, name, PGN, and final EPD position."""
    eco = models.CharField(max_length=8, db_index=True)
    name = models.CharField(max_length=200, db_index=True)
    pgn = models.TextField()
    epd = models.CharField(max_length=100, unique=True, db_index=True)

    class Meta:
        db_table = "opening_book"
        ordering = ["eco", "name"]
        verbose_name = "Opening"
        verbose_name_plural = "Openings"

    def __str__(self) -> str:
        """Return a readable string representation of the opening."""
        return f"{self.eco} — {self.name}"
