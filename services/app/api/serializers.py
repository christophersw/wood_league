"""
Title: serializers.py — DRF serializers for the Analysis Worker API
Description:
    Validates and serializes requests and responses for worker API operations
    including job checkout, completion reporting, failure reporting, heartbeat
    updates, and status queries. Supports both Stockfish and Lc0 chess engines.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-08: Added JobSubmitSerializer; extended Lc0MoveSerializer with arrow/pv fields
    2026-05-10: Removed DISPATCH_CHOICES and dispatch_mode field from CheckoutRequestSerializer
    2026-05-17 (#128): Add batch_total, batch_processed, session_started_at to HeartbeatSerializer
    2026-05-17 (#141): JobSerializer resolves null lc0 nodes -> settings.LC0_NODES
    2026-05-19 (#159): JobSerializer exposes white_rating/black_rating for WDL calibration
    2026-05-19 (#159/D2): Lc0MoveSerializer carries rescaled WDL + severity fields;
        Lc0CompleteSerializer carries draw_rate_reference / wdl_calibration_elo / contempt
"""
from django.conf import settings
from rest_framework import serializers


ENGINE_CHOICES = ['stockfish', 'lc0']
CLASSIFICATION_CHOICES = [
    'Brilliant', 'Great', 'Best', 'Excellent',
    'Inaccuracy', 'Mistake', 'Blunder',
]

# Lc0-specific severity labels produced by classify_draw_aware / _base_severity
# in the worker's wdl_calibration module.  These intentionally omit 'Brilliant'
# and 'Great' (those are Stockfish-only classifications).
LC0_SEVERITY_CHOICES = [
    'Best', 'Excellent', 'Good', 'Inaccuracy', 'Mistake', 'Blunder',
]

# Optional draw-character labels; most moves will have draw_character=None.
LC0_DRAW_CHARACTER_CHOICES = [
    'Missed Win', 'Losing Blunder', 'Risky', 'Simplification',
]


class CheckoutRequestSerializer(serializers.Serializer):
    """Inbound: request to check out a batch of analysis jobs.

    ``network_name`` is required when the engine is ``lc0`` (issue #161 Phase B):
    the app pre-flights NetworkCalibration for that network before claiming and
    returns 409 ``NEEDS_CALIBRATION`` when no matching calibration row exists.
    Stockfish checkouts ignore the field.
    """

    engine = serializers.ChoiceField(choices=ENGINE_CHOICES)
    batch_size = serializers.IntegerField(min_value=1, max_value=10, default=1)
    worker_id = serializers.CharField(max_length=64)
    game_id = serializers.CharField(max_length=64, required=False)
    network_name = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default="",
    )


class JobSerializer(serializers.Serializer):
    """Outbound: what a worker receives when it checks out a job."""

    id = serializers.IntegerField()
    game_id = serializers.CharField(source='game.id')
    pgn = serializers.CharField(source='game.pgn', required=False, allow_blank=True)
    engine = serializers.CharField()
    depth = serializers.IntegerField()   # Stockfish depth
    nodes = serializers.SerializerMethodField()  # Lc0 nodes (resolved)
    worker_id = serializers.CharField()
    claimed_by_key_prefix = serializers.CharField()

    white_rating = serializers.IntegerField(
        source='game.white_rating', required=False, allow_null=True, default=None)
    black_rating = serializers.IntegerField(
        source='game.black_rating', required=False, allow_null=True, default=None)
    # Resolved per-network draw rate, attached transiently by claim_jobs for lc0
    # checkouts (#161 Phase B). None for stockfish jobs and for lc0 jobs that
    # were claimed without a network pre-flight (legacy/test paths).
    draw_rate_reference = serializers.FloatField(
        required=False, allow_null=True, default=None,
    )

    def get_nodes(self, obj) -> int | None:
        """Resolve the lc0 node budget the worker must use.

        For lc0, a NULL ``nodes`` means "use the LC0_NODES setting"
        (per AnalysisJob.nodes' help text). The worker must never
        receive null nodes: bulk-requeued jobs (requeue_all_analysis)
        leave nodes=NULL, and the worker would otherwise fall back to
        the Stockfish ``depth`` (20) and run ~20-node garbage (#141).
        Stockfish ignores nodes (it uses ``depth``), so its value is
        passed through unchanged.

        Args:
            obj: the claimed AnalysisJob (or attr-compatible stub).

        Returns:
            The explicit job nodes, or settings.LC0_NODES for an lc0
            job with no explicit value, or the raw value otherwise.
        """
        if obj.engine == 'lc0' and obj.nodes is None:
            return settings.LC0_NODES
        return obj.nodes


class StockfishMoveSerializer(serializers.Serializer):
    """One Stockfish move — *raw observables only* (#161 raw contract).

    Worker emits cp_eval (white-frame, post-move) and optionally mate_in plus
    the top-3 candidate UCIs / mover-frame Win% scores / PV SAN lists. Every
    derived field (cpl, classification, move_win_delta, best_move) is computed
    app-side by ``derivation.stockfish.derive_sf_game``.
    """

    ply = serializers.IntegerField(min_value=1)
    san = serializers.CharField(max_length=10)
    fen = serializers.CharField(max_length=100)
    cp_eval = serializers.IntegerField()
    # Signed mate distance; positive=White mates, null when no mate score.
    mate_in = serializers.IntegerField(required=False, allow_null=True, default=None)
    arrow_uci_1 = serializers.CharField(max_length=8, allow_blank=True)
    arrow_uci_2 = serializers.CharField(
        max_length=8, required=False, default=None, allow_null=True, allow_blank=True,
    )
    arrow_uci_3 = serializers.CharField(
        max_length=8, required=False, default=None, allow_null=True, allow_blank=True,
    )
    arrow_score_1 = serializers.FloatField(required=False, allow_null=True, default=None)
    arrow_score_2 = serializers.FloatField(required=False, allow_null=True, default=None)
    arrow_score_3 = serializers.FloatField(required=False, allow_null=True, default=None)
    pv_san_1 = serializers.CharField(required=False, allow_null=True, default=None)
    pv_san_2 = serializers.CharField(required=False, allow_null=True, default=None)
    pv_san_3 = serializers.CharField(required=False, allow_null=True, default=None)

    class Meta:
        # DRF doesn't enforce "no extra fields" by default — we layer that on
        # via the parent serializer's ``unknown=raise``-style behaviour below.
        pass


class StockfishCompleteSerializer(serializers.Serializer):
    """Request to complete a Stockfish analysis job — raw payload only (#161 G).

    Unknown top-level fields (e.g. legacy ``white_accuracy``, ``cpl`` on a move)
    are rejected so pre-#161 worker payloads fail loud rather than silently
    drop information. ``create()`` is not used directly; the view calls
    ``derive_sf_game`` and persists via ``complete_stockfish_job``.
    """

    worker_id = serializers.CharField(max_length=64)
    engine_depth = serializers.IntegerField(min_value=1, max_value=40)
    engine_name = serializers.CharField(max_length=64, required=False, default="")
    moves = StockfishMoveSerializer(many=True, max_length=500)

    # Strict shape: a pre-#161 payload carries derived aggregates we no longer
    # accept. List every alias the worker might still send so validation fails
    # loud rather than silently dropping the value.
    _FORBIDDEN_TOP_LEVEL = frozenset({
        "white_accuracy", "black_accuracy",
        "white_acpl", "black_acpl",
        "white_blunders", "white_mistakes", "white_inaccuracies",
        "black_blunders", "black_mistakes", "black_inaccuracies",
    })
    _FORBIDDEN_PER_MOVE = frozenset({
        "cpl", "classification", "best_move", "move_win_delta", "arrow_uci",
    })

    def validate(self, attrs):
        """Reject pre-#161 derived fields at the top level and per move.

        Args:
            attrs: Initial validated data; we cross-check against the raw
                request body to catch keys DRF silently dropped.

        Returns:
            The unchanged validated data.

        Raises:
            serializers.ValidationError: When the worker payload includes any
                field that should be derived app-side.
        """
        raw = self.initial_data if isinstance(self.initial_data, dict) else {}
        bad_top = self._FORBIDDEN_TOP_LEVEL & set(raw)
        if bad_top:
            raise serializers.ValidationError({
                key: "Field removed in #161 — derived app-side." for key in bad_top
            })
        for index, move in enumerate(raw.get("moves") or []):
            if not isinstance(move, dict):
                continue
            bad = self._FORBIDDEN_PER_MOVE & set(move)
            if bad:
                raise serializers.ValidationError({
                    f"moves[{index}].{key}": "Field removed in #161 — derived app-side."
                    for key in bad
                })
        return attrs


class Lc0MoveSerializer(serializers.Serializer):
    """One Lc0 move — *raw observables only* (#161 raw contract).

    Worker emits the played-move WDL triple (mover frame, milli-units) plus
    three candidate triples and three candidate UCIs / PV SAN lists. The
    played triple is invariant-checked: its sum must lie in [990, 1010] (lc0
    rounds the WDL probabilities and rare 999/1001 totals are normal). Every
    derived classification / calibration field is computed app-side by
    ``derivation.lc0.derive_lc0_game``.
    """

    ply = serializers.IntegerField(min_value=1)
    san = serializers.CharField(max_length=10)
    fen = serializers.CharField(max_length=100)
    # Played-move triple (mover frame, milli-units).
    wdl_win = serializers.IntegerField(min_value=0, max_value=1000)
    wdl_draw = serializers.IntegerField(min_value=0, max_value=1000)
    wdl_loss = serializers.IntegerField(min_value=0, max_value=1000)
    # Top-3 candidate UCIs; lines 2/3 nullable.
    arrow_uci_1 = serializers.CharField(max_length=8, allow_blank=True)
    arrow_uci_2 = serializers.CharField(
        max_length=8, required=False, default=None, allow_null=True, allow_blank=True,
    )
    arrow_uci_3 = serializers.CharField(
        max_length=8, required=False, default=None, allow_null=True, allow_blank=True,
    )
    # Per-candidate raw WDL triples (mover frame); fully nullable per line.
    wdl_win_1 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_draw_1 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_loss_1 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_win_2 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_draw_2 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_loss_2 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_win_3 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_draw_3 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_loss_3 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    pv_san_1 = serializers.CharField(required=False, allow_null=True, default=None)
    pv_san_2 = serializers.CharField(required=False, allow_null=True, default=None)
    pv_san_3 = serializers.CharField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        """Reject WDL triples whose milli-unit sum is wildly out of range.

        Args:
            attrs: Per-move validated fields.

        Returns:
            ``attrs`` unchanged when the played triple sums to within
            ``[990, 1010]``; otherwise raises so we never persist a bogus row.
        """
        total = attrs["wdl_win"] + attrs["wdl_draw"] + attrs["wdl_loss"]
        if not 990 <= total <= 1010:
            raise serializers.ValidationError(
                {"wdl_win": f"WDL triple sum {total} out of permitted [990, 1010]."}
            )
        return attrs


class Lc0CompleteSerializer(serializers.Serializer):
    """Request to complete an Lc0 analysis job — raw payload only (#161 G).

    Game-level shape: ``worker_id``, ``engine_nodes``, ``network_name``,
    ``draw_rate_reference`` (echoed from the calibration row Phase B attached
    to the job payload), and ``moves[]``. Pre-#161 derived game-level fields
    (``wdl_calibration_elo``, ``contempt``, ``*_blunders``, ``*_*_prob``) are
    explicitly forbidden so worker downgrades fail loud.
    """

    worker_id = serializers.CharField(max_length=64)
    engine_nodes = serializers.IntegerField(min_value=1)
    network_name = serializers.CharField(max_length=128)
    draw_rate_reference = serializers.FloatField(min_value=0.001, max_value=0.999)
    moves = Lc0MoveSerializer(many=True, max_length=500)

    _FORBIDDEN_TOP_LEVEL = frozenset({
        "wdl_calibration_elo", "contempt",
        "white_win_prob", "white_draw_prob", "white_loss_prob",
        "black_win_prob", "black_draw_prob", "black_loss_prob",
        "white_blunders", "white_mistakes", "white_inaccuracies",
        "black_blunders", "black_mistakes", "black_inaccuracies",
    })
    _FORBIDDEN_PER_MOVE = frozenset({
        "wdl_win_adj", "wdl_draw_adj", "wdl_loss_adj",
        "wdl_mu", "delta_mu", "delta_d",
        "base_severity", "draw_character",
        "cp_equiv", "move_win_delta", "best_move",
        "arrow_uci", "arrow_score_1", "arrow_score_2", "arrow_score_3",
    })

    def validate(self, attrs):
        """Reject pre-#161 derived fields at the top level and per move.

        Args:
            attrs: Already validated raw payload.

        Returns:
            ``attrs`` unchanged when no derived fields were submitted.

        Raises:
            serializers.ValidationError: If any pre-#161 derived field is
                present at the top level or inside any move dict.
        """
        raw = self.initial_data if isinstance(self.initial_data, dict) else {}
        bad_top = self._FORBIDDEN_TOP_LEVEL & set(raw)
        if bad_top:
            raise serializers.ValidationError({
                key: "Field removed in #161 — derived app-side." for key in bad_top
            })
        for index, move in enumerate(raw.get("moves") or []):
            if not isinstance(move, dict):
                continue
            bad = self._FORBIDDEN_PER_MOVE & set(move)
            if bad:
                raise serializers.ValidationError({
                    f"moves[{index}].{key}": "Field removed in #161 — derived app-side."
                    for key in bad
                })
        return attrs


class JobFailSerializer(serializers.Serializer):
    """Request to fail an analysis job."""

    worker_id = serializers.CharField(max_length=64)
    error = serializers.CharField(max_length=2000)


class HeartbeatSerializer(serializers.Serializer):
    """Worker heartbeat status update.

    Backward-compatible: legacy workers omit batch_total/batch_processed/
    session_started_at and receive defaults of None/0/None. New workers
    send all fields to report live batch progress.
    """

    worker_id = serializers.CharField(max_length=64)
    engine = serializers.ChoiceField(choices=ENGINE_CHOICES)
    status_message = serializers.CharField(max_length=256, required=False, default='')
    batch_total = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    batch_processed = serializers.IntegerField(required=False, default=0)
    session_started_at = serializers.DateTimeField(
        required=False, allow_null=True, default=None
    )


class JobSubmitSerializer(serializers.Serializer):
    """Request to record a RunPod job submission."""

    runpod_job_id = serializers.CharField(max_length=128)


class NetworkCalibrationSubmitSerializer(serializers.Serializer):
    """Inbound: a worker reporting a completed lc0 draw-rate measurement.

    The ``(network_name, settings_hash)`` pair is the unique key the app uses
    to deduplicate concurrent submissions. ``worker_id`` is recorded into
    NetworkCalibration.submitted_by_worker_id verbatim.
    """

    network_name = serializers.CharField(max_length=64)
    settings_hash = serializers.RegexField(
        regex=r"^[0-9a-f]{64}$",
        help_text="Lowercase hex sha256 of the canonical sampler settings.",
    )
    draw_rate_reference = serializers.FloatField(min_value=0.001, max_value=0.999)
    sample_size = serializers.IntegerField(min_value=1)
    sem = serializers.FloatField(min_value=0.0)
    sampler_version = serializers.CharField(max_length=32)
    worker_id = serializers.CharField(max_length=64)

    def validate_draw_rate_reference(self, value: float) -> float:
        """Reject the open-interval endpoints (DRF's min/max are inclusive)."""
        if value <= 0.001 or value >= 0.999:
            raise serializers.ValidationError(
                "draw_rate_reference must lie strictly within (0.001, 0.999)."
            )
        return value
