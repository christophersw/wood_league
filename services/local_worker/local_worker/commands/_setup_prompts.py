"""
Title: _setup_prompts.py — Interactive prompt helpers for the setup wizard
Description:
    Questionary-driven prompts collecting API credentials, engine paths,
    and engine tuning parameters during ``wood-league-worker setup``.
    Lives in its own module to keep ``commands/setup.py`` under the
    Halstead-effort quality gate.

Changelog:
    2026-05-12: Extracted from commands/setup.py (issue #43 follow-up).
"""
from __future__ import annotations

from typing import Optional

import questionary
import typer

from local_worker._shared import console
from local_worker.config import Settings


def prompt_api_credentials(settings: Settings) -> tuple[str, str]:
    """Prompt for API URL and key.

    Args:
        settings: Current settings to use as defaults.

    Returns:
        Tuple of (api_url, api_key). Exits if cancelled.
    """
    api_url = questionary.text(
        "API URL (e.g. https://your-app.railway.app):",
        default=settings.api_url or "",
    ).ask()
    if not api_url:
        console.print("[red]Setup cancelled.")
        raise typer.Exit(1)

    api_key = questionary.password("Worker API key:").ask()
    if not api_key:
        console.print("[red]Setup cancelled.")
        raise typer.Exit(1)

    return api_url, api_key


def prompt_engine_paths(
    detected_sf: Optional[str],
    detected_lc0: Optional[str],
    settings: Settings,
) -> tuple[str, str]:
    """Prompt for engine paths.

    Args:
        detected_sf: Auto-detected Stockfish path or None.
        detected_lc0: Auto-detected Lc0 path or None.
        settings: Current settings to use as defaults.

    Returns:
        Tuple of (sf_path, lc0_path).
    """
    if detected_sf:
        sf_path = questionary.text("Stockfish path:", default=detected_sf).ask() or detected_sf
    else:
        sf_path = questionary.text("Stockfish path (leave blank to skip):").ask() or ""

    if detected_lc0:
        lc0_path = questionary.text("Lc0 path:", default=detected_lc0).ask() or detected_lc0
    else:
        lc0_path = questionary.text("Lc0 path (leave blank to skip):").ask() or ""

    return sf_path, lc0_path


def prompt_engine_settings(
    sf_settings: dict, settings: Settings
) -> tuple[int, int, int, int]:
    """Prompt for engine tuning parameters.

    Args:
        sf_settings: Suggested Stockfish settings from hardware detection.
        settings: Current settings to use as defaults.

    Returns:
        Tuple of (threads, hash_mb, sf_depth, lc0_nodes).
    """
    threads = int(
        questionary.text("Stockfish threads:", default=str(sf_settings["threads"])).ask()
        or sf_settings["threads"]
    )
    hash_mb = int(
        questionary.text("Stockfish hash MB:", default=str(sf_settings["hash_mb"])).ask()
        or sf_settings["hash_mb"]
    )
    sf_depth = int(
        questionary.text("Stockfish depth:", default=str(settings.stockfish_depth)).ask()
        or settings.stockfish_depth
    )
    lc0_nodes = int(
        questionary.text("Lc0 nodes per move:", default=str(settings.lc0_nodes)).ask()
        or settings.lc0_nodes
    )
    return threads, hash_mb, sf_depth, lc0_nodes


__all__ = [
    "prompt_api_credentials",
    "prompt_engine_paths",
    "prompt_engine_settings",
]
