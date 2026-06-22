"""Verify the server app imports cleanly with new metrics."""
import sys
import os
sys.path.insert(0, r"F:\workstation\projects\agent-audit")

# Clear cached modules
for mod in list(sys.modules):
    if 'agent_audit' in mod:
        del sys.modules[mod]
    if 'prometheus_fastapi_instrumentator' in mod:
        del sys.modules[mod]

# Test that the full server module imports without errors
print("Testing imports...")
from agent_audit.server.metrics import generate, inc, set_gauge, record_event, shutdown
print("  metrics.py: OK")

from agent_audit.server.middlewares import setup_prometheus
print("  middlewares.py setup_prometheus: OK")

# Test the generate function returns valid Prometheus text
output = generate()
assert isinstance(output, str), "generate() must return str"
assert len(output) > 0, "generate() must return non-empty text"
assert "HELP" in output, "output must contain HELP lines"
assert "TYPE" in output, "output must contain TYPE lines"
print(f"  generate() -> {len(output)} bytes of valid Prometheus text: OK")

# Test that all expected metric families are in the output
required = [
    "audit_events_total",
    "audit_policy_decisions_total",
    "audit_verify_checks_total",
    "audit_http_requests_total",
    "audit_sessions_active",
    "audit_storage_bytes",
    "audit_uptime_seconds",
    "audit_event_log_duration_seconds",
    "audit_request_latency_seconds",
    "audit_info",
]
for name in required:
    assert name in output, f"Missing metric: {name}"
print(f"  All {len(required)} metric families present: OK")

# Test FastAPI app with setup_prometheus
print("Testing FastAPI integration...")
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
setup_prometheus(app)

@app.get("/test")
def _test_handler():
    return {"ok": True}

client = TestClient(app)
resp = client.get("/test")
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
assert resp.json() == {"ok": True}
print(f"  FastAPI + setup_prometheus: Status {resp.status_code} OK")

print("\nAll checks passed!")
