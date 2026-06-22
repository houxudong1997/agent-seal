"""Verify ORM models and migration consistency."""

import sys

sys.path.insert(0, ".")

from agent_audit.models import Base

# 1. Import models
print("Models imported OK")

# 2. Check metadata tables
tables = sorted(Base.metadata.tables.keys())
print(f"Tables registered: {tables}")
assert "events" in tables, "MISSING: events"
assert "sessions" in tables, "MISSING: sessions"
assert "llm_calls" in tables, "MISSING: llm_calls"
assert "prompt_versions" in tables, "MISSING: prompt_versions"
assert "policy_decisions" in tables, "MISSING: policy_decisions"

# 3. Check Event columns match architecture
evt = Base.metadata.tables["events"]
evt_cols = set(evt.columns.keys())
expected_evt = {
    "id",
    "event_id",
    "session_id",
    "sequence",
    "timestamp",
    "event_type",
    "agent_id",
    "prompt_version",
    "input_snapshot",
    "output_snapshot",
    "metadata",
    "prev_hash",
    "hash",
    "signature",
    "sign_key_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "pii_redacted",
    "source_ip",
    "user_agent",
}
diff = evt_cols ^ expected_evt
assert not diff, f"Event column mismatch: {diff}"

# 4. Check LLMCall columns
llm = Base.metadata.tables["llm_calls"]
llm_cols = set(llm.columns.keys())
expected_llm = {
    "id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "provider",
    "model",
    "request_tokens",
    "response_tokens",
    "total_tokens",
    "latency_ms",
    "cost_usd",
    "request_body",
    "response_body",
    "session_id",
    "agent_id",
    "event_id",
    "timestamp",
}
diff = llm_cols ^ expected_llm
assert not diff, f"LLMCall column mismatch: {diff}"

# 5. Check Session columns
sess = Base.metadata.tables["sessions"]
sess_cols = set(sess.columns.keys())
expected_sess = {
    "id",
    "session_id",
    "agent_id",
    "status",
    "event_count",
    "started_at",
    "ended_at",
    "last_hash",
    "chain_verified",
    "metadata",
    "created_at",
    "updated_at",
}
diff = sess_cols ^ expected_sess
assert not diff, f"Session column mismatch: {diff}"

# 6. Index count check
evt_indexes = [i.name for i in evt.indexes]
print(f"Event indexes ({len(evt_indexes)}): {evt_indexes}")
assert len(evt_indexes) >= 6, f"Expected >= 6 indexes, got {len(evt_indexes)}"

llm_indexes = [i.name for i in llm.indexes]
print(f"LLMCall indexes ({len(llm_indexes)}): {llm_indexes}")
assert len(llm_indexes) >= 5, f"Expected >= 5 indexes, got {len(llm_indexes)}"

sess_indexes = [i.name for i in sess.indexes]
print(f"Session indexes ({len(sess_indexes)}): {sess_indexes}")
assert len(sess_indexes) >= 4, f"Expected >= 4 indexes, got {len(sess_indexes)}"

# 7. Verify migration file can be parsed
import ast

with open("alembic/versions/0001_initial_schema.py") as f:
    tree = ast.parse(f.read())
print("Migration 0001_initial_schema.py — valid Python AST")

print("\nALL CHECKS PASSED")
