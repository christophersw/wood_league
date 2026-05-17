"""O4: shared eval cache must tolerate concurrent writers and never
unlink a DB other processes may hold open."""
import threading
from pathlib import Path

import chess
import chess.engine

from local_worker.analysis.eval_cache import EvalCache, CachedPv


def _entry() -> list[CachedPv]:
    return [CachedPv(wdl_white=chess.engine.Wdl(wins=1000, draws=0, losses=0),
                      pv_uci=["e2e4"])]


def test_busy_timeout_pragma_set(tmp_path: Path):
    c = EvalCache(tmp_path / "ec.sqlite")
    assert c._conn is not None
    cur = c._conn.execute("PRAGMA busy_timeout")
    assert int(cur.fetchone()[0]) >= 3000
    c.close()


def test_concurrent_writers_no_exception(tmp_path: Path):
    db = tmp_path / "ec.sqlite"
    errors: list[BaseException] = []

    def worker(seed: int) -> None:
        try:
            cache = EvalCache(db)
            for i in range(50):
                z = seed * 1000 + i
                cache.put(z, "net", 1, 1, _entry())
                cache.get(z, "net", 1, 1)
            cache.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], f"concurrent writers raised: {errors!r}"


def test_corrupt_db_disables_not_unlinks(tmp_path: Path):
    db = tmp_path / "ec.sqlite"
    db.write_bytes(b"this is not a sqlite database, it is garbage" * 10)
    inode_before = db.stat().st_ino

    cache = EvalCache(db)  # must NOT raise, must NOT unlink

    assert db.exists(), "corrupt DB was unlinked — forbidden under multi-proc"
    assert db.stat().st_ino == inode_before, "DB file was replaced"
    assert cache.enabled is False, "corrupt DB should disable the cache"
    # Disabled cache: get/put are silent no-ops, never raise.
    assert cache.get(1, "n", 1, 1) is None
    cache.put(1, "n", 1, 1, _entry())
    cache.close()
