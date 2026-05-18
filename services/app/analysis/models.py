"""
Title: models.py — Game analysis database models
Description:
    Database models for chess game analysis including Stockfish engine analysis,
    LC0 neural engine analysis, move-level metrics, analysis job queue management,
    and worker heartbeat tracking for distributed analysis workers.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-18: Add AnalysisSchedule + AnalysisInstance models (issue #155).
"""
from django.db import models


class GameAnalysis(models.Model):
    """Stores Stockfish engine analysis metrics for a complete game."""
    game = models.OneToOneField(
        "games.Game", on_delete=models.CASCADE, related_name="analysis"
    )
    analyzed_at = models.DateTimeField(null=True, blank=True)
    engine_depth = models.IntegerField(null=True, blank=True)
    summary_cp = models.FloatField(default=0.0)
    white_accuracy = models.FloatField(null=True, blank=True)
    black_accuracy = models.FloatField(null=True, blank=True)
    white_acpl = models.FloatField(null=True, blank=True)
    black_acpl = models.FloatField(null=True, blank=True)
    white_blunders = models.IntegerField(null=True, blank=True)
    white_mistakes = models.IntegerField(null=True, blank=True)
    white_inaccuracies = models.IntegerField(null=True, blank=True)
    black_blunders = models.IntegerField(null=True, blank=True)
    black_mistakes = models.IntegerField(null=True, blank=True)
    black_inaccuracies = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "game_analysis"
        verbose_name = "Game Analysis"
        verbose_name_plural = "Game Analyses"

    def __str__(self):
        """Return a human-readable identifier for this analysis."""
        return f"Analysis for {self.game_id}"

    @property
    def avg_accuracy(self):
        """Calculate average accuracy across both players, or return single value if only one exists."""
        if self.white_accuracy is not None and self.black_accuracy is not None:
            return (self.white_accuracy + self.black_accuracy) / 2
        return self.white_accuracy or self.black_accuracy

    @property
    def avg_acpl(self):
        """Calculate average centipawn loss across both players, or return single value if only one exists."""
        if self.white_acpl is not None and self.black_acpl is not None:
            return (self.white_acpl + self.black_acpl) / 2
        return self.white_acpl or self.black_acpl


class MoveAnalysis(models.Model):
    """Stores Stockfish engine evaluation and classification for individual moves."""
    analysis = models.ForeignKey(
        GameAnalysis, on_delete=models.CASCADE, related_name="moves"
    )
    ply = models.IntegerField()
    san = models.CharField(max_length=32)
    fen = models.TextField()
    cp_eval = models.FloatField()
    cpl = models.FloatField(null=True, blank=True)
    best_move = models.CharField(max_length=32, default="")
    arrow_uci = models.CharField(max_length=8, default="")
    arrow_uci_2 = models.CharField(max_length=8, null=True, blank=True)
    arrow_uci_3 = models.CharField(max_length=8, null=True, blank=True)
    arrow_score_1 = models.FloatField(null=True, blank=True)
    arrow_score_2 = models.FloatField(null=True, blank=True)
    arrow_score_3 = models.FloatField(null=True, blank=True)
    classification = models.CharField(max_length=16, null=True, blank=True)
    pv_san_1 = models.TextField(null=True, blank=True)
    pv_san_2 = models.TextField(null=True, blank=True)
    pv_san_3 = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "move_analysis"
        ordering = ["ply"]
        indexes = [models.Index(fields=["analysis"])]
        verbose_name = "Move Analysis"
        verbose_name_plural = "Move Analyses"

    def __str__(self):
        """Return a human-readable identifier for this move analysis."""
        return f"Ply {self.ply} ({self.san}) in analysis {self.analysis_id}"

    @property
    def is_white_move(self):
        """Check if this move is played by White (odd plies are White moves)."""
        return self.ply % 2 == 1

    @property
    def move_number(self):
        """Calculate the move number (1-indexed) from the ply count."""
        return (self.ply + 1) // 2


class Lc0GameAnalysis(models.Model):
    """Stores Lc0 neural network engine analysis with win/draw/loss probabilities."""
    game = models.OneToOneField(
        "games.Game", on_delete=models.CASCADE, related_name="lc0_analysis"
    )
    analyzed_at = models.DateTimeField(null=True, blank=True)
    engine_nodes = models.IntegerField(null=True, blank=True)
    network_name = models.CharField(max_length=120, null=True, blank=True)
    white_win_prob = models.FloatField(null=True, blank=True)
    white_draw_prob = models.FloatField(null=True, blank=True)
    white_loss_prob = models.FloatField(null=True, blank=True)
    black_win_prob = models.FloatField(null=True, blank=True)
    black_draw_prob = models.FloatField(null=True, blank=True)
    black_loss_prob = models.FloatField(null=True, blank=True)
    white_blunders = models.IntegerField(null=True, blank=True)
    white_mistakes = models.IntegerField(null=True, blank=True)
    white_inaccuracies = models.IntegerField(null=True, blank=True)
    black_blunders = models.IntegerField(null=True, blank=True)
    black_mistakes = models.IntegerField(null=True, blank=True)
    black_inaccuracies = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "lc0_game_analysis"
        verbose_name = "Lc0 Game Analysis"
        verbose_name_plural = "Lc0 Game Analyses"

    def __str__(self):
        """Return a human-readable identifier for this Lc0 analysis."""
        return f"Lc0 analysis for {self.game_id}"


class Lc0MoveAnalysis(models.Model):
    """Stores Lc0 engine evaluation and win/draw/loss metrics for individual moves."""
    analysis = models.ForeignKey(
        Lc0GameAnalysis, on_delete=models.CASCADE, related_name="moves"
    )
    ply = models.IntegerField()
    san = models.CharField(max_length=32)
    fen = models.TextField()
    wdl_win = models.IntegerField(null=True, blank=True)
    wdl_draw = models.IntegerField(null=True, blank=True)
    wdl_loss = models.IntegerField(null=True, blank=True)
    cp_equiv = models.FloatField(null=True, blank=True)
    best_move = models.CharField(max_length=32, default="")
    arrow_uci = models.CharField(max_length=8, default="")
    arrow_uci_2 = models.CharField(max_length=8, null=True, blank=True)
    arrow_uci_3 = models.CharField(max_length=8, null=True, blank=True)
    arrow_score_1 = models.FloatField(null=True, blank=True)
    arrow_score_2 = models.FloatField(null=True, blank=True)
    arrow_score_3 = models.FloatField(null=True, blank=True)
    move_win_delta = models.FloatField(null=True, blank=True)
    classification = models.CharField(max_length=16, null=True, blank=True)
    pv_san_1 = models.TextField(null=True, blank=True)
    pv_san_2 = models.TextField(null=True, blank=True)
    pv_san_3 = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "lc0_move_analysis"
        ordering = ["ply"]
        indexes = [models.Index(fields=["analysis"])]
        verbose_name = "Lc0 Move Analysis"
        verbose_name_plural = "Lc0 Move Analyses"

    def __str__(self):
        """Return a human-readable identifier for this Lc0 move analysis."""
        return f"Lc0 ply {self.ply} ({self.san}) in analysis {self.analysis_id}"

    @property
    def is_white_move(self):
        """Check if this move is played by White (odd plies are White moves)."""
        return self.ply % 2 == 1

    @property
    def move_number(self):
        """Calculate the move number (1-indexed) from the ply count."""
        return (self.ply + 1) // 2


class AnalysisJob(models.Model):
    """Tracks asynchronous analysis jobs for games, including status and engine configuration."""
    STATUS_PENDING = "pending"
    STATUS_SUBMITTED = "submitted"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]
    PRIORITY_HIGH = 100
    PRIORITY_NORMAL = 0
    PRIORITY_LOW = -100
    game = models.ForeignKey(
        "games.Game", on_delete=models.CASCADE, related_name="analysis_jobs"
    )
    status = models.CharField(
        max_length=16, default=STATUS_PENDING, choices=STATUS_CHOICES, db_index=True
    )
    priority = models.IntegerField(default=0)
    engine = models.CharField(max_length=16, default="stockfish", db_index=True)
    depth = models.IntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=64, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    last_error = models.TextField(
        null=True, blank=True,
        help_text="Most recent RunPod submission error, if any. Job stays pending for retry.",
    )
    last_error_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    duration_seconds = models.FloatField(null=True, blank=True)
    runpod_job_id = models.CharField(max_length=64, null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    claimed_by_key_prefix = models.CharField(
        max_length=8, null=True, blank=True,
        help_text='8-char API key prefix of the worker that claimed this job',
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    nodes = models.IntegerField(
        null=True, blank=True,
        help_text='Lc0 MCTS node budget for this job; null means use LC0_NODES setting',
    )

    class Meta:
        db_table = "analysis_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "engine"]),
            models.Index(fields=["status", "priority"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["game", "engine"],
                condition=models.Q(status__in=["pending", "running", "submitted"]),
                name="analysis_jobs_active_engine_unique",
            ),
        ]
        verbose_name = "Analysis Job"
        verbose_name_plural = "Analysis Jobs"

    def __str__(self):
        """Return a human-readable identifier for this analysis job."""
        return f"{self.engine} job [{self.status}] for {self.game_id}"


class WorkerHeartbeat(models.Model):
    """Monitors health and status of remote analysis workers."""
    worker_id = models.CharField(max_length=64, primary_key=True)
    last_seen = models.DateTimeField(auto_now=True)
    engine = models.CharField(max_length=16, null=True, blank=True)
    status_message = models.CharField(max_length=256, null=True, blank=True)
    status = models.CharField(max_length=16, default="idle")
    current_game_id = models.CharField(max_length=64, null=True, blank=True)
    jobs_completed = models.IntegerField(default=0)
    jobs_failed = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    cpu_model = models.CharField(max_length=256, null=True, blank=True)
    cpu_cores = models.IntegerField(null=True, blank=True)
    memory_mb = models.IntegerField(null=True, blank=True)
    stockfish_binary = models.CharField(max_length=512, null=True, blank=True)
    batch_total = models.IntegerField(
        null=True, blank=True,
        help_text="Worker max_jobs run cap (M in N/M). Null = unlimited.",
    )
    batch_processed = models.IntegerField(
        default=0,
        help_text="Jobs completed so far this worker session (N in N/M).",
    )
    session_started_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Wall-clock start of the current worker run/session.",
    )

    class Meta:
        db_table = "worker_heartbeats"
        verbose_name = "Worker Heartbeat"
        verbose_name_plural = "Worker Heartbeats"

    def __str__(self):
        """Return a human-readable identifier for this worker heartbeat."""
        return f"Worker {self.worker_id} [{self.status}]"


class AnalysisSchedule(models.Model):
    """An opaque request to run one capped analysis batch (issue #155).

    This row IS the manual trigger: an admin (or any app-side actor)
    inserts a pending row; the reconcile cron picks it up. The cron does
    not care how it was created.
    """

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16, default=STATUS_PENDING,
        choices=STATUS_CHOICES, db_index=True,
    )
    max_jobs = models.IntegerField(
        null=True, blank=True,
        help_text="Per-run job cap; null → settings.VAST_MAX_JOBS.",
    )
    note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "analysis_schedules"
        ordering = ["created_at"]
        verbose_name = "Analysis Schedule"
        verbose_name_plural = "Analysis Schedules"

    def __str__(self):
        """Return a human-readable identifier for this schedule."""
        return f"AnalysisSchedule #{self.pk} [{self.status}]"

    def effective_max_jobs(self) -> int:
        """Return the job cap to use: explicit max_jobs or the setting.

        Returns:
            int: ``self.max_jobs`` when set, else
                ``django.conf.settings.VAST_MAX_JOBS``.
        """
        from django.conf import settings as _s
        return self.max_jobs if self.max_jobs is not None else _s.VAST_MAX_JOBS


class AnalysisInstance(models.Model):
    """A vast.ai instance launched for one AnalysisSchedule (issue #155).

    Live truth + crash-safe teardown backstop. The reconcile cron
    re-derives everything from this table each tick.
    """

    STATUS_LAUNCHING = "launching"
    STATUS_RUNNING = "running"
    STATUS_DESTROYED = "destroyed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_LAUNCHING, "Launching"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DESTROYED, "Destroyed"),
        (STATUS_FAILED, "Failed"),
    ]
    _LIVE_STATES = (STATUS_LAUNCHING, STATUS_RUNNING)

    schedule = models.ForeignKey(
        AnalysisSchedule, on_delete=models.CASCADE,
        related_name="instances",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16, default=STATUS_LAUNCHING,
        choices=STATUS_CHOICES, db_index=True,
    )
    vast_instance_id = models.CharField(
        max_length=32, null=True, blank=True,
        help_text="vast 'new_contract' id; null until create succeeds.",
    )
    launched_at = models.DateTimeField(null=True, blank=True)
    hard_deadline = models.DateTimeField(null=True, blank=True)
    destroyed_at = models.DateTimeField(null=True, blank=True)
    offer_dph = models.FloatField(
        null=True, blank=True,
        help_text="$/hr actually accepted, for cost visibility.",
    )
    launch_worker_ids = models.JSONField(
        default=list, blank=True,
        help_text="WorkerHeartbeat.worker_id set known at launch "
                  "(for drained-by-stale-heartbeat correlation).",
    )
    worker_id = models.CharField(
        max_length=64, null=True, blank=True,
        help_text="The WorkerHeartbeat bound to this instance once a "
                  "post-launch worker appears; null until correlated.",
    )

    class Meta:
        db_table = "analysis_instances"
        ordering = ["-created_at"]
        verbose_name = "Analysis Instance"
        verbose_name_plural = "Analysis Instances"

    def __str__(self):
        """Return a human-readable identifier for this instance."""
        return f"AnalysisInstance #{self.pk} [{self.status}]"

    @property
    def is_live(self) -> bool:
        """True when this instance is launching or running (non-terminal)."""
        return self.status in self._LIVE_STATES
