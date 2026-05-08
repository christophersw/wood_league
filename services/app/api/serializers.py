"""Serializers for the Analysis Worker API.

Handles validation and serialization of requests and responses for job
checkout, completion, failure, and heartbeat operations.
"""
from rest_framework import serializers


ENGINE_CHOICES = ['stockfish', 'lc0']
CLASSIFICATION_CHOICES = [
    'Brilliant', 'Great', 'Best', 'Excellent',
    'Inaccuracy', 'Mistake', 'Blunder',
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
    nodes = serializers.IntegerField(allow_null=True)  # Lc0 nodes
    worker_id = serializers.CharField()
    claimed_by_key_prefix = serializers.CharField()


class StockfishMoveSerializer(serializers.Serializer):
    """Individual move analysis from Stockfish."""

    ply = serializers.IntegerField(min_value=1)
    san = serializers.CharField(max_length=10)
    fen = serializers.CharField(max_length=100)
    cp_eval = serializers.IntegerField()
    cpl = serializers.IntegerField(min_value=0)
    best_move = serializers.CharField(max_length=10)
    classification = serializers.ChoiceField(choices=CLASSIFICATION_CHOICES)


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
    """Individual move analysis from Lc0."""

    ply = serializers.IntegerField(min_value=1)
    san = serializers.CharField(max_length=10)
    fen = serializers.CharField(max_length=100)
    wdl_win = serializers.IntegerField(min_value=0, max_value=1000)
    wdl_draw = serializers.IntegerField(min_value=0, max_value=1000)
    wdl_loss = serializers.IntegerField(min_value=0, max_value=1000)
    cp_equiv = serializers.IntegerField(required=False, allow_null=True)
    best_move = serializers.CharField(max_length=10)
    arrow_uci = serializers.CharField(max_length=10, required=False, default='')
    move_win_delta = serializers.FloatField()
    classification = serializers.ChoiceField(choices=CLASSIFICATION_CHOICES)


class Lc0CompleteSerializer(serializers.Serializer):
    """Request to complete an Lc0 analysis job."""

    worker_id = serializers.CharField(max_length=64)
    engine_nodes = serializers.IntegerField(min_value=1)
    network_name = serializers.CharField(max_length=128, required=False, default='')
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
    """Worker heartbeat status update."""

    worker_id = serializers.CharField(max_length=64)
    engine = serializers.ChoiceField(choices=ENGINE_CHOICES)
    status_message = serializers.CharField(max_length=256, required=False, default='')
