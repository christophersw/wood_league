"""
Title: models.py — WorkerClient data models
Description:
    Dataclasses representing the objects returned by the Django analysis
    worker API. These are the deserialized form of the JSON responses.

Changelog:
    2026-05-08: Created
    2026-05-10: Copied from packages/shared to make local_worker self-contained for PyPI
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Job:
    """A claimed analysis job returned by the checkout endpoint."""

    id: int
    game_id: str
    pgn: str
    engine: str
    depth: int
    nodes: int | None
