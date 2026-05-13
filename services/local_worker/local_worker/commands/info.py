"""
Title: info.py — Read-only ``version`` and ``status`` commands
Description:
    Implements the two read-only commands that report worker metadata
    without starting an analysis session.

Changelog:
    2026-05-12: Extracted from cli.py (issue #43 follow-up).
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

import httpx
import typer
from rich.table import Table

from local_worker._shared import console
from local_worker.config import load_settings


def version() -> None:
    """Print the installed wood-league-worker version."""
    try:
        console.print(_pkg_version("wood-league-worker"))
    except PackageNotFoundError:
        console.print(
            "[yellow]wood-league-worker is not installed as a distribution (running from source)."
        )


def status() -> None:
    """Show queue counts from the API."""
    settings = load_settings()
    if not settings.is_configured():
        console.print("[red]Not configured. Run `wood-league-worker setup` first.")
        raise typer.Exit(1)

    try:
        resp = httpx.get(
            f"{settings.api_url}/api/v1/jobs/status/",
            headers={"X-Api-Key": settings.api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        console.print(f"[red]Failed to fetch status: {exc}")
        raise typer.Exit(1) from exc

    table = Table(title="Queue Status")
    table.add_column("Engine", style="cyan")
    table.add_column("Status", style="white")
    table.add_column("Count", justify="right", style="bold")

    for row in data.get("queue", []):
        table.add_row(row["engine"], row["status"], str(row["count"]))

    console.print(table)
