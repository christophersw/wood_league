"""
Title: models.py — Player database models
Description:
    Defines the Player model representing club members with username, display
    name, real name, and email fields. Includes display name sorting and
    validation for unique usernames and emails.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.db import models


class Player(models.Model):
    """Club member player profile with username, display name, email, and real name."""
    username = models.CharField(max_length=80, unique=True, db_index=True)
    display_name = models.CharField(max_length=120)
    name = models.CharField(max_length=120, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True, unique=True, db_index=True)

    class Meta:
        db_table = "players"
        ordering = ["display_name"]
        verbose_name = "Player"
        verbose_name_plural = "Players"

    def __str__(self) -> str:
        """Return the player's display name or username."""
        return self.display_name or self.username
