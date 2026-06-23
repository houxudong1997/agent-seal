#!/usr/bin/env python3
"""Performance benchmark: JSONL vs SQLite at scale."""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_seal.storage import SQLiteTrail
from agent_seal.trail import AuditTrail


def bench(name, fn, iterations=1):
    start = time.perf_counter()
    result = None
    for _ in range(iterations):
        result = fn()
    elapsed = time.perf_counter() - start
    ops_per_sec = iterations / elapsed if elapsed > 0 else float("inf")
    print(f"  {name:30s} {elapsed:8.3f}s  ({ops_per_sec:8.0f} ops/s)")
    return result


def main():
    N = 10000
    print(f"agent-seal benchmark — {N:,} events\n")

    # ── JSONL ──
    tmp = tempfile.mkdtemp()
    trail = AuditTrail(tmp)

    def write_jsonl():
        for i in range(N):
            trail.log(f"sess-{i % 20}", "decision", "bot", "v1", f"input {i}", f"output {i}")

    bench("JSONL write", write_jsonl)

    bench("JSONL verify", lambda: trail.verify())

    bench("JSONL search", lambda: trail.search(session_id="sess-5", limit=50))

    bench("JSONL stats", lambda: trail.stats())

    # ── SQLite ──
    db = os.path.join(tmp, "bench.db")
    sq = SQLiteTrail(db)

    def write_sqlite():
        for i in range(N):
            sq.log(f"sess-{i % 20}", "decision", "bot", "v1", f"input {i}", f"output {i}")

    bench("SQLite write", write_sqlite)

    bench("SQLite verify", lambda: sq.verify())

    bench("SQLite search", lambda: sq.search(session_id="sess-5", limit=50))

    bench("SQLite stats", lambda: sq.stats())

    print(f"\nDone. {N:,} events each.")

    import shutil

    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
