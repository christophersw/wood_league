"""
Title: cache_merge_cmd.py — cache-merge CLI command implementation
Description:
    Typer command that exposes ``cache_merge.merge_deltas`` as an offline
    operator tool. Merges per-instance eval-cache deltas into a canonical
    SQLite file, prunes to a size cap, and reports the final row count.
Changelog:
    2026-05-16: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
from __future__ import annotations

from pathlib import Path

import typer

from local_worker.cache_merge import merge_deltas


def cache_merge(
    canonical: Path = typer.Option(..., help="Canonical eval-cache SQLite path"),
    delta: list[Path] = typer.Option(
        ..., "--delta", help="Per-instance delta SQLite path (repeatable)"
    ),
    max_mb: int = typer.Option(500, help="Canonical size cap in MB"),
) -> None:
    """Merge per-instance eval-cache deltas into the canonical (offline).

    Server-side, manual, between-campaigns. Unions each --delta into
    --canonical (last-writer-wins on primary-key collision), prunes to
    --max-mb, and vacuums.
    """
    rows = merge_deltas(canonical, list(delta), max_bytes=max_mb * 1024 * 1024)
    typer.echo(f"merged: canonical now has {rows} rows")
