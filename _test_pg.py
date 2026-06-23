"""Quick test: run just the first benchmark scenario with PostgreSQL."""
import sys, os, time, tempfile, shutil, statistics
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent_seal.core.chain import ChainEvent, SessionChain
from agent_seal.core.storage import PostgreSQLStore

N = 100  # small test
RUNS = 3
WARMUP = 1

_chains = {}
def _make_event(session_id, seq):
    chain = _chains.get(session_id)
    if chain is None:
        chain = SessionChain(session_id)
        _chains[session_id] = chain
    return chain.append(
        event_type="decision", agent_id="bench-agent", prompt_version="v1.0",
        input_snapshot=f"Test item {seq}", output_snapshot=f"Result {seq}",
        metadata={"seq": seq},
    )

dsn = "postgresql://audit:***@localhost:5432/agent_seal"
print(f"Connecting to PostgreSQL...")

try:
    store = PostgreSQLStore(dsn)
    print(f"Connected. Writing {N} events...")
    t0 = time.perf_counter()
    for i in range(N):
        store.write(_make_event(f"sess-{i%10}", i))
    dt = time.perf_counter() - t0
    print(f"Wrote {N} events in {dt*1000:.1f}ms ({N/dt:.0f}/s)")

    print(f"Reading sessions...")
    sessions = store.sessions()
    print(f"Found {len(sessions)} sessions: {sessions[:5]}...")

    for sid in sessions[:3]:
        data = store.read_session(sid)
        print(f"  Session {sid}: {len(data)} events")

    print(f"Verifying session {sessions[0]}...")
    t0 = time.perf_counter()
    ok = store.verify_session(sessions[0])
    print(f"  Verify: {'OK' if ok else 'FAIL'} in {(time.perf_counter()-t0)*1000:.1f}ms")

    print("Cleaning up...")
    conn = store._pool.getconn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM events")
        conn.commit()
    store._pool.putconn(conn)
    store.close()
    print("Done!")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
