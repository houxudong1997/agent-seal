#!/usr/bin/env python3
"""
PostgreSQL-only benchmark for agent-audit v1.0.
Runs all 6 Appendix A scenarios against PostgreSQLStore.
Produces Markdown-compatible output for inclusion in benchmark-v1.0.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
import zipfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("AGENT_AUDIT_DB_URL", "postgresql://audit:***@127.0.0.1:5432/agent_audit")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_audit.core.chain import ChainEvent, SessionChain
from agent_audit.core.storage import PostgreSQLStore

# Config
QUICK = "--quick" in sys.argv
SCALE = 10 if QUICK else 1
N_SINGLE_WRITE = 10_000 // SCALE
N_BATCH_SIZE = 100
N_BATCH_ITER = 500 // SCALE
N_SESSION_QUERY = 1_000 // SCALE
N_GLOBAL_VERIFY = 100_000 // SCALE
N_SEARCH = 50_000 // SCALE
N_EVIDENCE = 10_000 // SCALE
WARMUP = 2
RUNS = 5

DSN = "postgresql://audit:***@127.0.0.1:5432/agent_audit"

_chains: dict[str, SessionChain] = {}

def _make_event(session_id: str, seq: int) -> ChainEvent:
    chain = _chains.get(session_id)
    if chain is None:
        chain = SessionChain(session_id)
        _chains[session_id] = chain
    return chain.append(
        event_type="decision",
        agent_id="bench-agent",
        prompt_version="v1.0",
        input_snapshot=f"User asks about item {seq}: What is the compliance status of product SKU-{seq:06d}?",
        output_snapshot=f"Product SKU-{seq:06d} is COMPLIANT with EU AI Act Art.12, SOC2, HIPAA. Audit trail verified.",
        metadata={"benchmark": True, "seq": seq, "model": "gpt-4", "tokens": 42},
    )

def _reset_chains():
    _chains.clear()

def _clean_pg_table():
    """Delete all benchmark data from the events table."""
    import psycopg2
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM events")
        conn.commit()
    finally:
        conn.close()

def format_time(s: float) -> str:
    if s < 0.001:
        return f"{s * 1_000_000:.1f}us"
    elif s < 1:
        return f"{s * 1000:.1f}ms"
    else:
        return f"{s:.3f}s"

def format_rate(r: float) -> str:
    if r >= 1000:
        return f"{r / 1000:.1f}k/s"
    else:
        return f"{r:.0f}/s"

def status_icon(mean_s: float, target_s: float, higher_better: bool = False) -> str:
    """Compare measured vs target, return PASS / ⚠️ / ❌."""
    if higher_better:
        if mean_s >= target_s * 0.9:
            return "PASS"
        elif mean_s >= target_s * 0.5:
            return "WARN"
        else:
            return "FAIL"
    else:
        if mean_s <= target_s * 1.1:
            return "PASS"
        elif mean_s <= target_s * 2:
            return "WARN"
        else:
            return "FAIL"

# ── Scenarios ──────────────────────────────────────────────────

def sc1_single_write() -> tuple[float, float, float]:
    """Single event write throughput."""
    _reset_chains()
    events = [_make_event(f"sess-{i % 50}", i) for i in range(N_SINGLE_WRITE)]

    # warmup — clean table between iterations to avoid duplicate keys
    for _ in range(WARMUP):
        _clean_pg_table()
        s = PostgreSQLStore(DSN)
        try:
            for i in range(min(100, N_SINGLE_WRITE)):
                s.write(events[i])
        finally:
            s.close()

    durations = []
    for _ in range(RUNS):
        _clean_pg_table()
        s = PostgreSQLStore(DSN)
        try:
            t0 = time.perf_counter()
            for ev in events:
                s.write(ev)
            durations.append(time.perf_counter() - t0)
        finally:
            s.close()

    mean = statistics.mean(durations)
    std = statistics.stdev(durations) if len(durations) > 1 else 0.0
    ops_per_sec = N_SINGLE_WRITE / mean
    return mean, std, ops_per_sec

def sc2_batch_write() -> tuple[float, float, float]:
    """Batch write (sequential 100-event batches)."""
    _reset_chains()
    total = N_BATCH_ITER * N_BATCH_SIZE
    events = [_make_event(f"sess-{i % 50}", i) for i in range(total)]

    for _ in range(WARMUP):
        _clean_pg_table()
        s = PostgreSQLStore(DSN)
        try:
            for i in range(min(200, total)):
                s.write(events[i])
        finally:
            s.close()

    durations = []
    for _ in range(RUNS):
        _clean_pg_table()
        s = PostgreSQLStore(DSN)
        try:
            t0 = time.perf_counter()
            for batch_start in range(0, len(events), N_BATCH_SIZE):
                batch = events[batch_start : batch_start + N_BATCH_SIZE]
                for ev in batch:
                    s.write(ev)
            durations.append(time.perf_counter() - t0)
        finally:
            s.close()

    mean = statistics.mean(durations)
    std = statistics.stdev(durations) if len(durations) > 1 else 0.0
    ops_per_sec = total / mean
    return mean, std, ops_per_sec

def sc3_session_query() -> tuple[float, float, int]:
    """Session query — read N events from one session."""
    _reset_chains()
    sid = "bench-s3"
    _clean_pg_table()
    s = PostgreSQLStore(DSN)
    try:
        for i in range(N_SESSION_QUERY):
            s.write(_make_event(sid, i))
    finally:
        s.close()

    durations = []
    for _ in range(RUNS):
        s = PostgreSQLStore(DSN)
        try:
            t0 = time.perf_counter()
            data = s.read_session(sid)
            durations.append(time.perf_counter() - t0)
        finally:
            s.close()

    mean = statistics.mean(durations)
    std = statistics.stdev(durations) if len(durations) > 1 else 0.0
    return mean, std, len(data)

def sc4_global_verify() -> tuple[float, float, int]:
    """Global verification — verify all sessions."""
    _reset_chains()
    _clean_pg_table()
    s = PostgreSQLStore(DSN)
    try:
        num_sessions = 100
        events_per = N_GLOBAL_VERIFY // num_sessions
        for sid_idx in range(num_sessions):
            sid = f"bench-s4-{sid_idx:03d}"
            for i in range(events_per):
                s.write(_make_event(sid, i))
    finally:
        s.close()

    durations = []
    for _ in range(RUNS):
        s = PostgreSQLStore(DSN)
        try:
            t0 = time.perf_counter()
            for sid in s.sessions():
                s.verify_session(sid)
            durations.append(time.perf_counter() - t0)
        finally:
            s.close()

    mean = statistics.mean(durations)
    std = statistics.stdev(durations) if len(durations) > 1 else 0.0
    return mean, std, num_sessions

def sc5_event_search() -> tuple[float, float, int]:
    """Event search — filter by text in input_snapshot."""
    _reset_chains()
    _clean_pg_table()
    s = PostgreSQLStore(DSN)
    try:
        num_sessions = 10
        events_per = N_SEARCH // num_sessions
        for sid_idx in range(num_sessions):
            sid = f"bench-s5-{sid_idx:03d}"
            for i in range(events_per):
                s.write(_make_event(sid, i))
    finally:
        s.close()

    search_term = "SKU-000042"
    durations = []
    for _ in range(RUNS):
        s = PostgreSQLStore(DSN)
        try:
            t0 = time.perf_counter()
            results = []
            for sid in s.sessions():
                data = s.read_session(sid)
                for ev in data:
                    if search_term in ev.get("input_snapshot", ""):
                        results.append(ev)
            durations.append(time.perf_counter() - t0)
        finally:
            s.close()

    mean = statistics.mean(durations)
    std = statistics.stdev(durations) if len(durations) > 1 else 0.0
    return mean, std, len(results)

def sc6_evidence_export() -> tuple[float, float, int]:
    """Evidence export — create signed ZIP bundle."""
    _reset_chains()
    _clean_pg_table()
    s = PostgreSQLStore(DSN)
    try:
        num_sessions = 50
        events_per = N_EVIDENCE // num_sessions
        for sid_idx in range(num_sessions):
            sid = f"bench-s6-{sid_idx:03d}"
            for i in range(events_per):
                s.write(_make_event(sid, i))
    finally:
        s.close()

    durations = []
    for run_idx in range(RUNS):
        s = PostgreSQLStore(DSN)
        try:
            t0 = time.perf_counter()
            all_events = []
            for sid in s.sessions():
                all_events.extend(s.read_session(sid))

            bundle = {
                "bundle_id": hashlib.sha256(str(time.time()).encode()).hexdigest()[:16],
                "created_at": datetime.now(UTC).isoformat(),
                "total_events": len(all_events),
                "sessions": len(s.sessions()),
                "events": all_events,
            }
            bundle_hash = hashlib.sha256(
                json.dumps(
                    {"count": len(all_events), "session_ids": s.sessions()}, sort_keys=True
                ).encode()
            ).hexdigest()
            bundle["sha256"] = bundle_hash

            import tempfile as _tmp
            tmpdir = _tmp.mkdtemp(prefix="bench_s6_")
            zip_path = os.path.join(tmpdir, f"evidence_{run_idx}.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("metadata.json",
                    json.dumps({"bundle_id": bundle["bundle_id"], "total_events": bundle["total_events"],
                               "sha256": bundle_hash}, indent=2))
                zf.writestr("events.json", json.dumps(all_events))
            os.unlink(zip_path)
            durations.append(time.perf_counter() - t0)
        finally:
            s.close()

    mean = statistics.mean(durations)
    std = statistics.stdev(durations) if len(durations) > 1 else 0.0
    return mean, std, bundle["total_events"]


# ── Runner ─────────────────────────────────────────────────────

scenarios = [
    ("1. Single event write", sc1_single_write, "ops/s",
     5000.0, True,  # target: 5,000/s (higher is better)
     ),
    ("2. Batch write (100/batch)", sc2_batch_write, "ops/s",
     20000.0, True,  # target: 20,000/s
     ),
    ("3. Session query (1K events)", sc3_session_query, "time",
     0.005, False,  # target: 5ms
     ),
    ("4. Global verification (100K)", sc4_global_verify, "time",
     0.300, False,  # target: 300ms
     ),
    ("5. Event search (full-text)", sc5_event_search, "time",
     0.020, False,  # target: 20ms
     ),
    ("6. Evidence export (10K)", sc6_evidence_export, "time",
     0.500, False,  # target: 500ms
     ),
]

print("=" * 72)
print("  agent-audit v1.0 — PostgreSQL Performance Benchmark")
print("=" * 72)
print(f"  Mode: {'QUICK (1/10 scale)' if QUICK else 'FULL SCALE'}")
print(f"  DSN: {DSN}")
print(f"  Python: {sys.version.split()[0]}")
print("=" * 72)

results = {}
for sc_name, sc_fn, mtype, target, higher_better in scenarios:
    print(f"\n{'─' * 72}")
    print(f"  {sc_name}")
    print(f"{'─' * 72}")
    sys.stdout.flush()
    
    try:
        mean, std, extra = sc_fn()
        if mtype == "ops/s":
            rate = extra
            print(f"  PostgreSQL  {format_time(mean):>10s} ± {format_time(std):>8s}   {format_rate(rate):>10s}")
            icon = status_icon(rate, target, higher_better=True)
            print(f"  Target: {format_rate(target)}/s  Status: {icon}")
            results[sc_name] = {"mean_s": mean, "std_s": std, "ops_per_sec": rate, "icon": icon}
        else:
            print(f"  PostgreSQL  {format_time(mean):>10s} ± {format_time(std):>8s}")
            icon = status_icon(mean, target, higher_better=False)
            print(f"  Target: {format_time(target)}  Status: {icon}")
            results[sc_name] = {"mean_s": mean, "std_s": std, "icon": icon}
    except Exception as e:
        print(f"  PostgreSQL  ERROR: {e}")
        results[sc_name] = {"error": str(e), "icon": "ERROR"}
    
    # Clean PG table between scenarios
    _clean_pg_table()
    sys.stdout.flush()

# ── Summary ────────────────────────────────────────────────────
print(f"\n{'=' * 72}")
print("  POSTGRESQL SUMMARY vs v1.0 TARGETS")
print(f"{'=' * 72}")
print(f"  {'Scenario':<38s} {'Target':>12s} {'PostgreSQL':>14s} {'Status':>8s}")
print(f"  {'─' * 38} {'─' * 12} {'─' * 14} {'─' * 8}")

target_display = {
    "1. Single event write": "5,000/s",
    "2. Batch write (100/batch)": "20,000/s",
    "3. Session query (1K events)": "5ms",
    "4. Global verification (100K)": "300ms",
    "5. Event search (full-text)": "20ms",
    "6. Evidence export (10K)": "500ms",
}

for sc_name, _fn, mtype, _tgt, _hb in scenarios:
    r = results.get(sc_name, {})
    tgt_display = target_display.get(sc_name, "N/A")
    icon = r.get("icon", "?")
    if "error" in r:
        print(f"  {sc_name:<38s} {tgt_display:>12s} {'ERROR':>14s} {icon:>8s}")
    elif mtype == "ops/s":
        print(f"  {sc_name:<38s} {tgt_display:>12s} {format_rate(r['ops_per_sec']):>14s} {icon:>8s}")
    else:
        print(f"  {sc_name:<38s} {tgt_display:>12s} {format_time(r['mean_s']):>14s} {icon:>8s}")

print(f"{'=' * 72}")

# Count pass/warn/fail
passes = sum(1 for r in results.values() if r.get("icon") == "PASS")
warns = sum(1 for r in results.values() if r.get("icon") == "WARN")
fails = sum(1 for r in results.values() if r.get("icon") == "FAIL")
errors = sum(1 for r in results.values() if r.get("icon") == "ERROR")
print(f"  PASS: {passes}  WARN: {warns}  FAIL: {fails}  ERROR: {errors}")
print(f"{'=' * 72}")

# Print machine-readable JSON at the end for parsing
print("\n--- RESULTS_JSON ---")
print(json.dumps(results, indent=2))
print("--- END_RESULTS_JSON ---")
