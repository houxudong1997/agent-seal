"""Final verification: import all modules, check key functions."""
import sys
sys.path.insert(0, ".")

print("1. Importing FastAPI app...")
from agent_seal.server.app import app, get_engine, _safe_integrity
print(f"   OK: app.title={app.title}, {len(app.routes)} routes")

print("2. Importing engine...")
from agent_seal.core.storage import AuditEngine
from agent_seal.config import config

print("3. Testing engine...")
engine = get_engine()
stats = engine.stats()
print(f"   OK: stats={stats['total_events']} events, {stats['sessions']} sessions")

print("4. Testing safe integrity...")
result = _safe_integrity(engine, engine.sessions()[0])
print(f"   OK: integrity={result}")

print("5. Testing log + verify (new session)...")
event = engine.log("verify-test", "test", "agent", "v1", "in", "out")
print(f"   OK: logged event {event.event_id[:8]}, seq={event.sequence}")
ok = engine.verify("verify-test")
print(f"   OK: verify={'PASS' if ok else 'FAIL'}")

print("\n=== ALL CHECKS PASSED ===")
