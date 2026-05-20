"""
Title: calibrate_draw_rate_cmd.py — `wlworker calibrate-draw-rate` CLI command
Description:
    Phase A of issue #161. Thin wrapper that launches an lc0 engine, runs the
    existing draw-rate sampler (``analysis.lc0_draw_rate.measure_draw_rate``),
    and POSTs the result to the app's
    ``POST /api/v1/network_calibrations/`` endpoint as a single
    ``WorkerClient.submit_network_calibration`` call.

    All sampler inputs (``--sem-target``, ``--nodes``, ``--max-positions``,
    ``--sampler-version``) and the matching ``--settings-hash`` are supplied
    explicitly by the operator (Phase B will derive them from the app's 409
    response automatically). The endpoint is idempotent on
    ``(network_name, settings_hash)`` — a second writer arriving simultaneously
    sees ``created=False`` and the CLI exits 0.

Changelog:
    2026-05-19 (#161/A): Initial creation.
"""
from __future__ import annotations

from typing import Any

import chess.engine
import typer

from local_worker.analysis.lc0 import _configure_engine
from local_worker.analysis.lc0_draw_rate import measure_draw_rate
from local_worker.worker_client import WorkerClient


def launch_lc0_engine(
    *,
    lc0_path: str,
    weights_path: str,
    syzygy_path: str,
    backend: str,
) -> chess.engine.SimpleEngine:
    """Launch + configure lc0 without the worker-cached draw-rate side-effect.

    Args:
        lc0_path: Absolute path to the lc0 binary.
        weights_path: Network weights file path, or empty for default.
        syzygy_path: Syzygy tablebase directory, or empty.
        backend: lc0 backend identifier (``cuda-auto``, ``metal``, ``cpu``).

    Returns:
        A configured, ready-to-analyse SimpleEngine. Caller owns ``.quit()``.
    """
    engine = chess.engine.SimpleEngine.popen_uci(lc0_path)
    try:
        _configure_engine(
            engine,
            lc0_path=lc0_path,
            weights_path=weights_path,
            syzygy_path=syzygy_path,
            backend=backend,
            auto_tune=True,
        )
    except BaseException:
        try:
            engine.quit()
        except Exception:  # noqa: BLE001 — best-effort teardown
            pass
        raise
    return engine


def _submit(
    *,
    api_base: str,
    api_key: str,
    network: str,
    settings_hash: str,
    sampler_version: str,
    worker_id: str,
    result: Any,
) -> dict:
    """Send the measurement to the app and return the parsed response.

    Args:
        api_base: App base URL (no trailing slash required).
        api_key: Worker API key (X-Api-Key header value).
        network: Resolved lc0 network name.
        settings_hash: Pre-computed canonical sampler settings hash.
        sampler_version: Echoes the app's sampler version tag.
        worker_id: This worker's identifier (recorded on the row).
        result: A ``DrawRateResult``-shaped object (network, draw_rate_reference,
            n_samples, stderr attributes).

    Returns:
        Parsed JSON body returned by the endpoint.
    """
    client = WorkerClient(base_url=api_base, api_key=api_key)
    return client.submit_network_calibration(
        network_name=network,
        settings_hash=settings_hash,
        draw_rate_reference=result.draw_rate_reference,
        sample_size=result.n_samples,
        sem=result.stderr,
        sampler_version=sampler_version,
        worker_id=worker_id,
    )


def calibrate_draw_rate(
    network: str = typer.Option(..., "--network", help="Resolved lc0 network name."),
    sem_target: float = typer.Option(..., "--sem-target", help="Sampler SEM target."),
    nodes: int = typer.Option(..., "--nodes", help="Nodes per sampled position."),
    max_positions: int = typer.Option(
        ..., "--max-positions", help="Hard cap on positions sampled."
    ),
    sampler_version: str = typer.Option(..., "--sampler-version"),
    settings_hash: str = typer.Option(
        ..., "--settings-hash",
        help="Lowercase hex sha256 of canonical sampler settings (from the app).",
    ),
    api_base: str = typer.Option(..., "--api-base", help="App base URL."),
    api_key: str = typer.Option(..., "--api-key", help="Worker API key."),
    worker_id: str = typer.Option(..., "--worker-id"),
    lc0_path: str = typer.Option("lc0", "--lc0-path"),
    weights_path: str = typer.Option("", "--weights-path"),
    syzygy_path: str = typer.Option("", "--syzygy-path"),
    backend: str = typer.Option("cuda-auto", "--backend"),
) -> None:
    """Measure ``network``'s population draw rate and submit it to the app.

    The endpoint is idempotent on ``(network, settings_hash)``; a no-op response
    indicates another worker already submitted a matching calibration.
    """
    engine = launch_lc0_engine(
        lc0_path=lc0_path, weights_path=weights_path,
        syzygy_path=syzygy_path, backend=backend,
    )
    try:
        result = measure_draw_rate(
            engine,
            network=network,
            sem_target=sem_target,
            max_samples=max_positions,
            nodes=nodes,
        )
    finally:
        try:
            engine.quit()
        except Exception:  # noqa: BLE001
            pass

    response = _submit(
        api_base=api_base, api_key=api_key, network=network,
        settings_hash=settings_hash, sampler_version=sampler_version,
        worker_id=worker_id, result=result,
    )
    if response.get("created"):
        typer.echo(
            f"calibrate-draw-rate: stored {network} "
            f"draw_rate_reference={result.draw_rate_reference:.4f} "
            f"n={result.n_samples} sem={result.stderr:.4f}"
        )
    else:
        typer.echo(
            f"calibrate-draw-rate: already calibrated (no-op) for {network} "
            f"@ {settings_hash[:8]}"
        )
