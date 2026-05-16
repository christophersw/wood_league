"""
Title: test_cache_merge_cli.py — tests for the cache-merge CLI command
Description:
    Verifies the ``cache-merge`` Typer command wires operator args
    through to ``cache_merge.merge_deltas`` and reports the result.
Changelog:
    2026-05-15: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from local_worker.cli import app
from local_worker.analysis.eval_cache import EvalCache


def test_cache_merge_command(tmp_path: Path):
    canonical = tmp_path / "canonical.sqlite"
    delta = tmp_path / "d1.sqlite"
    EvalCache(canonical).close()
    EvalCache(delta).close()
    conn = sqlite3.connect(delta)
    conn.execute(
        "INSERT INTO eval_cache "
        "(zobrist, network, nodes, multipv, payload, created_at, last_used_at) "
        "VALUES (1,'BT4',100,3,'{\"v\":2,\"pvs\":[]}',1,1)"
    )
    conn.commit()
    conn.close()

    result = CliRunner().invoke(
        app,
        ["cache-merge", "--canonical", str(canonical),
         "--delta", str(delta), "--max-mb", "50"],
    )
    assert result.exit_code == 0, result.output
    assert "merged" in result.output.lower()
    out = sqlite3.connect(canonical)
    assert out.execute("SELECT COUNT(*) FROM eval_cache").fetchone()[0] == 1
    out.close()
