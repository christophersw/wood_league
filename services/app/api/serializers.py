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
    """Inbound: request to check out a batch of analysis jobs."""

    engine = serializers.ChoiceField(choices=ENGINE_CHOICES)
    batch_size = serializers.IntegerField(min_value=1, max_value=10, default=1)
    worker_id = serializers.CharField(max_length=64)
    game_id = serializers.CharField(max_length=64, required=False)


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
    """Individual move analysis from Stockfish, including MultiPV candidate data."""

    ply = serializers.IntegerField(min_value=1)
    san = serializers.CharField(max_length=10)
    fen = serializers.CharField(max_length=100)
    cp_eval = serializers.IntegerField()
    cpl = serializers.IntegerField(min_value=0)
    best_move = serializers.CharField(max_length=10)
    classification = serializers.ChoiceField(choices=CLASSIFICATION_CHOICES)
    arrow_uci = serializers.CharField(max_length=8, allow_blank=True)
    arrow_uci_2 = serializers.CharField(max_length=8, allow_blank=True)
    arrow_uci_3 = serializers.CharField(max_length=8, allow_blank=True)
    arrow_score_1 = serializers.FloatField(allow_null=True)
    arrow_score_2 = serializers.FloatField(allow_null=True)
    arrow_score_3 = serializers.FloatField(allow_null=True)
    pv_san_1 = serializers.CharField(allow_null=True)
    pv_san_2 = serializers.CharField(allow_null=True)
    pv_san_3 = serializers.CharField(allow_null=True)


class StockfishCompleteSerializer(serializers.Serializer):
    """Request to complete a Stockfish analysis job."""

    worker_id = serializers.CharField(max_length=64)
    engine_depth = serializers.IntegerField(min_value=1, max_value=40)
    white_accuracy = serializers.FloatField(min_value=0, max_value=100)
    black_accuracy = serializers.FloatField(min_value=0, max_value=100)
    white_acpl = serializers.FloatField(min_value=0)
    black_acpl = serializers.FloatField(min_value=0)
    white_blunders = serializers.IntegerField(min_value=0)
    white_mistakes = serializers.IntegerField(min_value=0)
    white_inaccuracies = serializers.IntegerField(min_value=0)
    black_blunders = serializers.IntegerField(min_value=0)
    black_mistakes = serializers.IntegerField(min_value=0)
    black_inaccuracies = serializers.IntegerField(min_value=0)
    moves = StockfishMoveSerializer(many=True, max_length=500)


class Lc0MoveSerializer(serializers.Serializer):
    """Individual move analysis from Lc0, including WDL calibration fields.

    Raw WDL triple (wdl_win/draw/loss) is the lc0 engine output in milli-units
    (0-1000, summing to 1000).  The rescaled triple (_adj suffix) is the
    population-adjusted WDL after applying the draw-rate reference correction
    from wdl_calibration.  wdl_mu is the expected-score fraction derived from
    the rescaled triple, and delta_mu/delta_d are the move-level changes in mu
    and draw fraction versus the position before the move.

    base_severity is one of LC0_SEVERITY_CHOICES (always set).
    draw_character is one of LC0_DRAW_CHARACTER_CHOICES or None (most moves).
    The old ``classification`` field has been removed — it was replaced by
    base_severity + draw_character in #159.
    """

    ply = serializers.IntegerField(min_value=1)
    san = serializers.CharField(max_length=10)
    fen = serializers.CharField(max_length=100)
    # Raw lc0 WDL triple (engine output, milli-units, sum=1000)
    wdl_win = serializers.IntegerField(min_value=0, max_value=1000)
    wdl_draw = serializers.IntegerField(min_value=0, max_value=1000)
    wdl_loss = serializers.IntegerField(min_value=0, max_value=1000)
    # Rescaled WDL triple after draw-rate reference correction
    wdl_win_adj = serializers.IntegerField(min_value=0, max_value=1000)
    wdl_draw_adj = serializers.IntegerField(min_value=0, max_value=1000)
    wdl_loss_adj = serializers.IntegerField(min_value=0, max_value=1000)
    # wdl_mu = (W + 0.5*D) / total from rescaled triple; nullable for edge cases
    wdl_mu = serializers.FloatField(required=False, allow_null=True, default=None)
    # delta_mu = change in expected score versus position before move (signed)
    delta_mu = serializers.FloatField()
    # delta_d = change in draw fraction (signed; negative means draw fraction fell)
    delta_d = serializers.FloatField()
    cp_equiv = serializers.IntegerField(required=False, allow_null=True)
    best_move = serializers.CharField(max_length=10)
    # CharField rejects empty strings by default — the worker legitimately
    # sends "" for PV slots that have no candidate (e.g. mate-in-1 with
    # only one legal continuation), and the DB column is nullable/blank.
    # Without allow_blank=True these submissions would fail validation
    # mid-game and the whole job would be retried (issue #59).
    arrow_uci = serializers.CharField(
        max_length=8, required=False, default='', allow_blank=True,
    )
    move_win_delta = serializers.FloatField()
    # base_severity from classify_draw_aware/_base_severity (always set)
    base_severity = serializers.ChoiceField(choices=LC0_SEVERITY_CHOICES)
    # draw_character from classify_draw_aware (None for most moves)
    draw_character = serializers.ChoiceField(
        choices=LC0_DRAW_CHARACTER_CHOICES,
        required=False,
        allow_null=True,
        default=None,
    )
    arrow_uci_2 = serializers.CharField(
        max_length=8, required=False, default='', allow_blank=True,
    )
    arrow_uci_3 = serializers.CharField(
        max_length=8, required=False, default='', allow_blank=True,
    )
    arrow_score_1 = serializers.FloatField(required=False, allow_null=True, default=None)
    arrow_score_2 = serializers.FloatField(required=False, allow_null=True, default=None)
    arrow_score_3 = serializers.FloatField(required=False, allow_null=True, default=None)
    pv_san_1 = serializers.CharField(required=False, allow_null=True, default=None)
    pv_san_2 = serializers.CharField(required=False, allow_null=True, default=None)
    pv_san_3 = serializers.CharField(required=False, allow_null=True, default=None)


class Lc0CompleteSerializer(serializers.Serializer):
    """Request to complete an Lc0 analysis job, including WDL calibration metadata.

    New fields vs. the pre-#159 shape:
    - draw_rate_reference: population draw-rate used to rescale WDL triples (0.001–0.999)
    - wdl_calibration_elo: the Elo at which draw_rate_reference was looked up (>= 0)
    - contempt: lc0 contempt setting at time of analysis (signed integer; 0 = neutral)
    """

    worker_id = serializers.CharField(max_length=64)
    engine_nodes = serializers.IntegerField(min_value=1)
    network_name = serializers.CharField(max_length=128, required=False, default='')
    # WDL calibration metadata
    draw_rate_reference = serializers.FloatField(min_value=0.001, max_value=0.999)
    wdl_calibration_elo = serializers.IntegerField(min_value=0)
    contempt = serializers.IntegerField()
    white_win_prob = serializers.FloatField(min_value=0, max_value=1)
    white_draw_prob = serializers.FloatField(min_value=0, max_value=1)
    white_loss_prob = serializers.FloatField(min_value=0, max_value=1)
    black_win_prob = serializers.FloatField(min_value=0, max_value=1)
    black_draw_prob = serializers.FloatField(min_value=0, max_value=1)
    black_loss_prob = serializers.FloatField(min_value=0, max_value=1)
    white_blunders = serializers.IntegerField(min_value=0)
    white_mistakes = serializers.IntegerField(min_value=0)
    white_inaccuracies = serializers.IntegerField(min_value=0)
    black_blunders = serializers.IntegerField(min_value=0)
    black_mistakes = serializers.IntegerField(min_value=0)
    black_inaccuracies = serializers.IntegerField(min_value=0)
    moves = Lc0MoveSerializer(many=True, max_length=500)


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
