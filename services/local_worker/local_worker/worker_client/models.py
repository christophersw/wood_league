"""
Title: models.py — WorkerClient data models
Description:
    Dataclasses representing the objects returned by the Django analysis
    worker API. These are the deserialized form of the JSON responses.

Changelog:
    2026-05-08: Created
    2026-05-10: Copied from packages/shared to make local_worker self-contained for PyPI
    2026-05-19 (#159): Job gains white_rating/black_rating for D1 Elo passthrough.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class Job:
    """A claimed analysis job returned by the checkout endpoint."""

    id: int
    game_id: str
    pgn: str
    engine: str
    depth: int
    nodes: int | None
    white_rating: Optional[int] = None
    black_rating: Optional[int] = None
    # Per-network calibrated draw rate; populated by the app for lc0 jobs once
    # the network has a NetworkCalibration row (#161 Phase B). None for
    # stockfish jobs and pre-#161 lc0 deployments.
    draw_rate_reference: Optional[float] = None
