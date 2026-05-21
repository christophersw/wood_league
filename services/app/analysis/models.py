"""
Title: models.py — Game analysis database models
Description:
    Database models for chess game analysis including Stockfish engine analysis,
    LC0 neural engine analysis, move-level metrics, analysis job queue management,
    and worker heartbeat tracking for distributed analysis workers.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-18: Add AnalysisSchedule + AnalysisInstance models (issue #155).
    2026-05-18: Add RecurringAnalysisSchedule + AnalysisSchedule.recurring_rule (#155 B).
    2026-05-21: Add WDL columns + normalize_to_pawn_value (fresh-db reset, issue #188); restore arrow_score_1/2/3 (scope correction — Phase D).
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
    # #188 SF NormalizeToPawnValue captured at analyse time, for
    # reproducibility across SF builds. Nullable for older builds.
    normalize_to_pawn_value = models.IntegerField(null=True, blank=True)

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
    """Stockfish per-move analysis — raw worker output + app-derived fields (#161 F).

    Raw fields (worker → app, untouched): cp_eval, mate_in, arrow_uci_1/2/3,
    arrow_score_1/2/3, pv_san_1/2/3, wdl_(win|draw|loss)(_1|_2|_3)?, san, fen, ply.
    Derived fields (computed by ``derivation.stockfish``): cpl,
    move_win_delta, classification, best_move.
    """
    analysis = models.ForeignKey(
        GameAnalysis, on_delete=models.CASCADE, related_name="moves"
    )
    ply = models.IntegerField()
    san = models.CharField(max_length=32)
    fen = models.TextField()
    # Raw: white-frame post-move cp eval.
    cp_eval = models.FloatField()
    # Raw: signed mate distance; positive = White mates, NULL if not in mate.
    mate_in = models.IntegerField(null=True, blank=True)
    # Derived: mover-frame centipawn loss.
    cpl = models.FloatField(null=True, blank=True)
    # Derived: mover-frame Win% drop (#161 Phase E).
    move_win_delta = models.FloatField(null=True, blank=True)
    # Top-3 candidates (raw); ``arrow_uci_1`` renamed from ``arrow_uci`` in F.
    arrow_uci_1 = models.CharField(max_length=8, default="")
    arrow_uci_2 = models.CharField(max_length=8, null=True, blank=True)
    arrow_uci_3 = models.CharField(max_length=8, null=True, blank=True)
    arrow_score_1 = models.FloatField(null=True, blank=True)
    arrow_score_2 = models.FloatField(null=True, blank=True)
    arrow_score_3 = models.FloatField(null=True, blank=True)
    # Derived severity label.
    classification = models.CharField(max_length=16, null=True, blank=True)
    best_move = models.CharField(max_length=32, default="")
    pv_san_1 = models.TextField(null=True, blank=True)
    pv_san_2 = models.TextField(null=True, blank=True)
    pv_san_3 = models.TextField(null=True, blank=True)
    # ── #188 SF native WDL (raw + adj) ──────────────────────────────────
    # Raw played-move triple, mover frame, milli-units. Nullable for older
    # SF builds without UCI_ShowWDL.
    wdl_win = models.IntegerField(null=True, blank=True)
    wdl_draw = models.IntegerField(null=True, blank=True)
    wdl_loss = models.IntegerField(null=True, blank=True)
    # Raw per-candidate triples (top 3 MultiPV); fully nullable per line.
    wdl_win_1 = models.IntegerField(null=True, blank=True)
    wdl_draw_1 = models.IntegerField(null=True, blank=True)
    wdl_loss_1 = models.IntegerField(null=True, blank=True)
    wdl_win_2 = models.IntegerField(null=True, blank=True)
    wdl_draw_2 = models.IntegerField(null=True, blank=True)
    wdl_loss_2 = models.IntegerField(null=True, blank=True)
    wdl_win_3 = models.IntegerField(null=True, blank=True)
    wdl_draw_3 = models.IntegerField(null=True, blank=True)
    wdl_loss_3 = models.IntegerField(null=True, blank=True)
    # Derived: White-frame rescaled WDL triple. SF rescale is identity
    # (frame-mirror only); columns exist for chart symmetry with Lc0.
    # Populated by derivation.stockfish in the upcoming derivation rewrite.
    wdl_win_adj = models.IntegerField(null=True, blank=True)
    wdl_draw_adj = models.IntegerField(null=True, blank=True)
    wdl_loss_adj = models.IntegerField(null=True, blank=True)

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
    # WDL calibration metadata (#159)
    draw_rate_reference = models.FloatField(
        null=True, blank=True,
        help_text="Population draw-rate used to rescale WDL triples (0.001–0.999).",
    )
    wdl_calibration_elo = models.IntegerField(
        null=True, blank=True,
        help_text="Elo at which draw_rate_reference was looked up.",
    )
    contempt = models.IntegerField(
        null=True, blank=True,
        help_text="Lc0 contempt setting at time of analysis (signed integer; 0 = neutral).",
    )
    # Per-side game accuracy (#164). Lichess curve applied to mover-frame
    # ``wdl_mu`` series in derivation.lc0; ``None`` when the side contributed
    # no plies to the series (e.g. a 1-ply or 2-ply game).
    white_accuracy = models.FloatField(null=True, blank=True)
    black_accuracy = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "lc0_game_analysis"
        verbose_name = "Lc0 Game Analysis"
        verbose_name_plural = "Lc0 Game Analyses"

    def __str__(self):
        """Return a human-readable identifier for this Lc0 analysis."""
        return f"Lc0 analysis for {self.game_id}"

    @property
    def avg_accuracy(self):
        """Mean of white/black accuracy, or whichever single side has data.

        Mirrors ``GameAnalysis.avg_accuracy`` so templates can render an
        engine-agnostic "average game accuracy" without branching.
        """
        if self.white_accuracy is not None and self.black_accuracy is not None:
            return (self.white_accuracy + self.black_accuracy) / 2
        return self.white_accuracy or self.black_accuracy


class Lc0MoveAnalysis(models.Model):
    """Lc0 per-move analysis — raw worker output + app-derived fields (#161 F).

    Raw fields: ply, san, fen, played-move ``wdl_win/draw/loss`` triple, three
    candidate triples ``wdl_(win|draw|loss)_(1|2|3)``, ``arrow_uci_1/2/3``,
    ``pv_san_1/2/3``.
    Derived fields (from ``derivation.lc0.derive_lc0_game``):
    ``wdl_*_adj``, ``wdl_mu``, ``delta_mu``, ``delta_d``, ``base_severity``,
    ``draw_character``, ``best_move``.

    Phase F removed ``cp_equiv``, ``arrow_uci`` (renamed ``arrow_uci_1``),
    ``arrow_score_*``, and ``move_win_delta`` — none survive the raw contract.
    """
    analysis = models.ForeignKey(
        Lc0GameAnalysis, on_delete=models.CASCADE, related_name="moves"
    )
    ply = models.IntegerField()
    san = models.CharField(max_length=32)
    fen = models.TextField()
    # Raw played-move triple, mover frame, milli-units.
    wdl_win = models.IntegerField(null=True, blank=True)
    wdl_draw = models.IntegerField(null=True, blank=True)
    wdl_loss = models.IntegerField(null=True, blank=True)
    # Raw per-candidate triples (top 3 lines); fully nullable per-line.
    wdl_win_1 = models.IntegerField(null=True, blank=True)
    wdl_draw_1 = models.IntegerField(null=True, blank=True)
    wdl_loss_1 = models.IntegerField(null=True, blank=True)
    wdl_win_2 = models.IntegerField(null=True, blank=True)
    wdl_draw_2 = models.IntegerField(null=True, blank=True)
    wdl_loss_2 = models.IntegerField(null=True, blank=True)
    wdl_win_3 = models.IntegerField(null=True, blank=True)
    wdl_draw_3 = models.IntegerField(null=True, blank=True)
    wdl_loss_3 = models.IntegerField(null=True, blank=True)
    # Top-3 candidate UCIs (raw); ``arrow_uci_1`` renamed from ``arrow_uci`` in F.
    arrow_uci_1 = models.CharField(max_length=8, default="")
    arrow_uci_2 = models.CharField(max_length=8, null=True, blank=True)
    arrow_uci_3 = models.CharField(max_length=8, null=True, blank=True)
    # Derived: rescaled WDL triple in White's frame (#159 + #161 F).
    wdl_win_adj = models.IntegerField(null=True, blank=True)
    wdl_draw_adj = models.IntegerField(null=True, blank=True)
    wdl_loss_adj = models.IntegerField(null=True, blank=True)
    # Derived: expected-score fraction (White-frame) from rescaled WDL.
    wdl_mu = models.FloatField(null=True, blank=True)
    # Derived: per-move change in expected score / drawishness.
    delta_mu = models.FloatField(null=True, blank=True)
    delta_d = models.FloatField(null=True, blank=True)
    # Derived: severity label + optional draw-character overlay.
    base_severity = models.CharField(max_length=16, null=True, blank=True)
    draw_character = models.CharField(max_length=16, null=True, blank=True)
    best_move = models.CharField(max_length=32, default="")
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
    recurring_rule = models.ForeignKey(
        "RecurringAnalysisSchedule", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="materialized_schedules",
        help_text="Set when this row was materialized from a recurring "
                  "rule; null for one-offs.",
    )

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


class RecurringAnalysisSchedule(models.Model):
    """A crontab rule that the reconcile cron materializes into
    `pending` AnalysisSchedule rows (issue #155 Sub-project B).

    The rule never launches anything itself; Step 0 of
    reconcile_vast_analysis turns a due rule into one pending schedule.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.CharField(max_length=128)
    crontab = models.CharField(
        max_length=128,
        help_text="5-field cron expression, e.g. '0 2 * * 1' (Mon 02:00).",
    )
    timezone = models.CharField(
        max_length=64, default="UTC",
        help_text="IANA tz name the crontab is evaluated in.",
    )
    enabled = models.BooleanField(default=True, db_index=True)
    max_jobs = models.IntegerField(
        null=True, blank=True,
        help_text="Per-run job cap; null → settings.VAST_MAX_JOBS.",
    )
    last_materialized_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "recurring_analysis_schedules"
        ordering = ["name"]
        verbose_name = "Recurring Analysis Schedule"
        verbose_name_plural = "Recurring Analysis Schedules"

    def __str__(self):
        """Return a human-readable identifier for this rule."""
        return f"RecurringAnalysisSchedule #{self.pk} [{self.name}]"

    def clean(self):
        """Validate the crontab expression and the timezone.

        Raises:
            ValidationError: when ``crontab`` is not a valid 5-field cron
                expression, or ``timezone`` is not a known IANA zone.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from croniter import croniter
        from django.core.exceptions import ValidationError

        if not croniter.is_valid(self.crontab or ""):
            raise ValidationError({"crontab": "Invalid cron expression."})
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            raise ValidationError({"timezone": "Unknown timezone."})

    def effective_max_jobs(self) -> int:
        """Return the job cap to use: explicit max_jobs or the setting.

        Returns:
            int: ``self.max_jobs`` when set, else
                ``django.conf.settings.VAST_MAX_JOBS``.
        """
        from django.conf import settings as _s
        return self.max_jobs if self.max_jobs is not None else _s.VAST_MAX_JOBS


class NetworkCalibration(models.Model):
    """One-shot population draw-rate measurement for an lc0 network.

    Rows are keyed by (network_name, settings_hash). The hash binds the
    measurement to the exact sampler parameters that produced it — bumping any
    sampler setting (see ``analysis.calibration_hash``) yields a fresh hash and
    therefore a fresh row, never an in-place mutation of an existing one.

    Concurrent submissions from racing workers are idempotent at the DB layer
    via the unique_together constraint; the view layer translates the second
    insert into a 200 no-op via get_or_create.
    """
    network_name = models.CharField(max_length=64)
    settings_hash = models.CharField(max_length=64)
    draw_rate_reference = models.FloatField(
        help_text="Population draw rate measured by the sampler; in (0.001, 0.999).",
    )
    sample_size = models.IntegerField(
        help_text="Positions sampled before convergence or max_positions cap.",
    )
    sem = models.FloatField(
        help_text="Standard error of the mean achieved by the sampler.",
    )
    sampler_version = models.CharField(
        max_length=32,
        help_text="Echoes settings.WL_LC0_DRAW_RATE_SAMPLER_VERSION at measure time.",
    )
    measured_at = models.DateTimeField(auto_now_add=True)
    submitted_by_worker_id = models.CharField(max_length=64)

    class Meta:
        db_table = "network_calibration"
        unique_together = [("network_name", "settings_hash")]
        verbose_name = "Network Calibration"
        verbose_name_plural = "Network Calibrations"

    def __str__(self) -> str:
        """Return a human-readable identifier for this calibration."""
        return f"NetworkCalibration[{self.network_name} @ {self.settings_hash[:8]}]"
