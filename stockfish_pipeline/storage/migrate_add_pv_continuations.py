"""
Title: migrate_add_pv_continuations.py — Database migration for PV continuation columns
Description:
    Adds pv_san_1, pv_san_2, pv_san_3 Text columns to the move_analysis table
    to store full principal variation continuations from Stockfish analysis.
    Handles both PostgreSQL (with IF NOT EXISTS) and SQLite (with try/except).

Changelog:
    2026-05-05 (#1): Initial creation for PV continuation storage migration
"""

from __future__ import annotations

import logging
from sqlalchemy import text as sa_text
from sqlalchemy.exc import OperationalError

log = logging.getLogger(__name__)


def migrate_add_pv_continuations(engine) -> None:
    """
    Add pv_san_1, pv_san_2, pv_san_3 nullable Text columns to move_analysis table.

    For PostgreSQL: uses IF NOT EXISTS to safely add columns.
    For SQLite: uses try/except since SQLite doesn't support IF NOT EXISTS.

    Args:
        engine: SQLAlchemy engine connected to the target database

    Side effects:
        Alters the move_analysis table schema by adding three columns if they
        don't already exist. Logs the operation status.
    """
    is_postgresql = engine.dialect.name == "postgresql"

    column_definitions = [
        "pv_san_1",
        "pv_san_2",
        "pv_san_3",
    ]

    with engine.begin() as connection:
        if is_postgresql:
            for column_name in column_definitions:
                sql = f"""
                    ALTER TABLE move_analysis
                    ADD COLUMN IF NOT EXISTS {column_name} TEXT
                """
                try:
                    connection.execute(sa_text(sql))
                    log.info(f"Added column {column_name} to move_analysis (PostgreSQL)")
                except OperationalError as exc:
                    log.warning(
                        f"Failed to add column {column_name} to move_analysis: {exc}"
                    )
        else:
            # SQLite: no IF NOT EXISTS support for ALTER TABLE, use try/except
            for column_name in column_definitions:
                sql = f"ALTER TABLE move_analysis ADD COLUMN {column_name} TEXT"
                try:
                    connection.execute(sa_text(sql))
                    log.info(f"Added column {column_name} to move_analysis (SQLite)")
                except OperationalError as exc:
                    # Column likely already exists
                    if "duplicate column" in str(exc).lower():
                        log.info(
                            f"Column {column_name} already exists in move_analysis (SQLite)"
                        )
                    else:
                        log.warning(
                            f"Failed to add column {column_name} to move_analysis: {exc}"
                        )


def main() -> None:
    """
    CLI entry point for running the migration.

    Loads database configuration from environment and applies the migration.
    Exit code 0 on success, 1 on failure.
    """
    import sys
    from stockfish_pipeline.storage.database import ENGINE

    try:
        migrate_add_pv_continuations(ENGINE)
        log.info("Migration completed successfully")
        sys.exit(0)
    except Exception as exc:
        log.error(f"Migration failed: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    main()
