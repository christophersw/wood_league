"""
Title: submit_log.py — ``wood-league-worker submit-log`` command
Description:
    Explicit upload of the current ``worker.log`` to the Wood League
    server. Used by club members who want to volunteer a log without
    waiting for a crash to trigger the auto-uploader.

Changelog:
    2026-05-13 (#52): Initial creation. Replaces GlitchTip telemetry.
"""
from __future__ import annotations

import typer

from local_worker._shared import console
from local_worker.log_upload import upload_log


def submit_log(
    note: str = typer.Argument(
        '',
        help='Short description of what went wrong (optional).',
    ),
) -> None:
    """Upload the most recent ``worker.log`` to the Wood League server."""
    upload_id = upload_log('manual', note=note)
    if upload_id <= 0:
        console.print('[red]Log upload failed. See worker.log for details.')
        raise typer.Exit(1)
    console.print(f'[green]Uploaded log (id={upload_id}).')


__all__ = ['submit_log']
