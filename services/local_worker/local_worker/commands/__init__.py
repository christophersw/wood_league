"""
Title: commands package marker
Description:
    Sub-package containing the Typer subcommand implementations for
    ``wood-league-worker``. Each module here exposes either a Typer
    callback (registered with ``app.command``) or a sub-app
    (registered with ``app.add_typer``) from
    :mod:`local_worker.cli`.

Changelog:
    2026-05-12: Initial creation. Issue #43 follow-up — split out of
        the monolithic ``cli.py`` to satisfy the Halstead-effort gate.
"""
