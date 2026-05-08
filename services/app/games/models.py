"""Database models for chess games and participant tracking."""

from django.db import models


class Game(models.Model):
    """A chess game record with metadata from Chess.com, PGN, and analysis."""
    # Chess.com game ID is a string — keep as the primary key to avoid any
    # mapping complexity; use slug as the URL identifier everywhere.
    id = models.CharField(max_length=64, primary_key=True)
    slug = models.SlugField(max_length=80, null=True, blank=True, unique=True, db_index=True)
    played_at = models.DateTimeField(db_index=True)
    time_control = models.CharField(max_length=32)
    white_username = models.CharField(max_length=120, null=True, blank=True)
    black_username = models.CharField(max_length=120, null=True, blank=True)
    white_rating = models.IntegerField(null=True, blank=True)
    black_rating = models.IntegerField(null=True, blank=True)
    result_pgn = models.CharField(max_length=16, null=True, blank=True)
    winner_username = models.CharField(max_length=120, null=True, blank=True)
    eco_code = models.CharField(max_length=8, default="")
    opening_name = models.CharField(max_length=120, default="")
    lichess_opening = models.CharField(max_length=200, null=True, blank=True)
    pgn = models.TextField(default="")

    class Meta:
        db_table = "games"
        ordering = ["-played_at"]
        verbose_name = "Game"
        verbose_name_plural = "Games"

    def __str__(self):
        """Return human-readable game summary."""
        return f"{self.white_username} vs {self.black_username} ({self.played_at:%Y-%m-%d})"

    @property
    def display_result(self):
        """Return formatted result description (e.g., 'White won', 'Draw')."""
        if self.result_pgn == "1-0":
            return f"{self.white_username} won"
        if self.result_pgn == "0-1":
            return f"{self.black_username} won"
        if self.result_pgn == "1/2-1/2":
            return "Draw"
        return self.result_pgn or "Unknown"


class GameParticipant(models.Model):
    """Tracks player participation in a game with performance metrics."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="participants")
    player = models.ForeignKey("players.Player", on_delete=models.CASCADE, related_name="participations")
    color = models.CharField(max_length=8)
    opponent_username = models.CharField(max_length=120)
    player_rating = models.IntegerField(null=True, blank=True)
    opponent_rating = models.IntegerField(null=True, blank=True)
    result = models.CharField(max_length=32)
    quality_score = models.FloatField(null=True, blank=True)
    blunder_count = models.IntegerField(null=True, blank=True)
    mistake_count = models.IntegerField(null=True, blank=True)
    inaccuracy_count = models.IntegerField(null=True, blank=True)
    acpl = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "game_participants"
        unique_together = [("game", "player")]
        indexes = [
            models.Index(fields=["game"]),
            models.Index(fields=["player"]),
        ]
        verbose_name = "Game Participant"
        verbose_name_plural = "Game Participants"

    def __str__(self):
        """Return human-readable participation description."""
        return f"{self.player} ({self.color}) in {self.game_id}"
