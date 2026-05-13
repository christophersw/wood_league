"""
Title: setup.py — ``wood-league-worker setup`` interactive wizard
Description:
    First-run configuration wizard.  Delegates prompts to
    :mod:`_setup_prompts` and asset downloads to :mod:`_downloads` so
    this orchestration module stays trivially small.

Changelog:
    2026-05-12: Extracted from cli.py (issue #43 follow-up).
    2026-05-12: Prompts and download helpers split into sibling
        ``_setup_prompts.py`` / ``_downloads.py`` modules.
"""
from __future__ import annotations

from local_worker._shared import console
from local_worker.commands._downloads import offer_download_bt4, offer_download_syzygy
from local_worker.commands._setup_prompts import (
    prompt_api_credentials,
    prompt_engine_paths,
    prompt_engine_settings,
)
from local_worker.config import Settings, load_settings, normalize_api_url, save_settings
from local_worker.detector import (
    detect_hardware,
    detect_lc0_backend,
    find_lc0,
    find_stockfish,
    suggest_stockfish_settings,
)


def _build_settings(
    api_url: str,
    api_key: str,
    sf_path: str,
    lc0_path: str,
    lc0_weights_path: str,
    backend: str,
    syzygy_path: str,
    tune: tuple[int, int, int, int],
) -> Settings:
    """Assemble the persisted :class:`Settings` from prompt results.

    Args:
        api_url: Raw API URL string from the prompt.
        api_key: Worker API key.
        sf_path: Stockfish binary path.
        lc0_path: Lc0 binary path.
        lc0_weights_path: BT4 (or other) weights file path.
        backend: Detected Lc0 backend name.
        syzygy_path: Syzygy tablebase directory path.
        tune: Tuple of ``(threads, hash_mb, sf_depth, lc0_nodes)``.

    Returns:
        Fully-populated :class:`Settings` ready to be saved.
    """
    threads, hash_mb, sf_depth, lc0_nodes = tune
    return Settings(
        api_url=normalize_api_url(api_url.rstrip("/")),
        api_key=api_key,
        stockfish_path=sf_path,
        lc0_path=lc0_path,
        lc0_weights_path=lc0_weights_path,
        lc0_backend=backend,
        syzygy_path=syzygy_path,
        stockfish_threads=threads,
        stockfish_hash_mb=hash_mb,
        stockfish_depth=sf_depth,
        lc0_nodes=lc0_nodes,
    )


def _detect_and_report(settings: Settings) -> tuple[str, str, dict, str]:
    """Run engine + hardware detection and print the summary to the console.

    Args:
        settings: Currently-persisted settings (used only for ``console``
            scope; the function doesn't mutate it).

    Returns:
        Tuple of (sf_path, lc0_path, suggested_sf_settings, lc0_backend).
    """
    console.print("\n[bold]Detecting engines…")
    sf_path = find_stockfish()
    lc0_path = find_lc0()
    hw = detect_hardware()
    backend = detect_lc0_backend()
    sf_settings = suggest_stockfish_settings(hw)

    console.print(f"  Stockfish: [green]{sf_path or 'not found'}")
    console.print(f"  Lc0:       [green]{lc0_path or 'not found'}")
    console.print(f"  Lc0 backend detected: [cyan]{backend}")
    console.print(f"  CPU cores: {hw.cpu_count}  RAM: {hw.ram_mb} MB")
    console.print(
        f"  Suggested Stockfish threads: {sf_settings['threads']}  hash: {sf_settings['hash_mb']} MB"
    )
    # Make name available for tests / unused-warning suppression.
    _ = settings
    return sf_path or "", lc0_path or "", sf_settings, backend


def setup() -> None:
    """Interactive first-time configuration wizard."""
    console.rule("[bold cyan]Wood League Worker — Setup")
    settings = load_settings()

    api_url, api_key = prompt_api_credentials(settings)
    sf_path, lc0_path, sf_settings, backend = _detect_and_report(settings)
    sf_path, lc0_path = prompt_engine_paths(sf_path, lc0_path, settings)

    lc0_weights_path = offer_download_bt4(settings.lc0_weights_path)
    syzygy_path = offer_download_syzygy(settings.syzygy_path)

    tune = prompt_engine_settings(sf_settings, settings)
    new_settings = _build_settings(
        api_url=api_url,
        api_key=api_key,
        sf_path=sf_path,
        lc0_path=lc0_path,
        lc0_weights_path=lc0_weights_path,
        backend=backend,
        syzygy_path=syzygy_path,
        tune=tune,
    )
    save_settings(new_settings)
    console.print("\n[bold green]Settings saved! Run `wood-league-worker run` to start.")
