"""Database models for club members in the players app."""

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
