"""Tests for the policy engine (new YAML-based architecture)."""

from agent_seal.policy.engine import PolicyEngine, Verdict


def test_block_rm_rf():
    engine = PolicyEngine()
    r = engine.evaluate("tool_call", "CALL: shell.run('rm -rf /tmp/cache')")
    assert r.blocked
    assert "block-shell-write" in r.triggered


def test_allow_safe_shell():
    engine = PolicyEngine()
    r = engine.evaluate("tool_call", "CALL: shell.run('ls -la /tmp')")
    assert r.verdict == Verdict.ALLOW


def test_block_drop_table():
    engine = PolicyEngine()
    r = engine.evaluate("tool_call", "CALL: db.execute('DROP TABLE users')")
    assert r.blocked
    assert "block-sql-destruction" in r.triggered


def test_allow_select():
    engine = PolicyEngine()
    r = engine.evaluate("tool_call", "CALL: db.execute('SELECT COUNT(*) FROM users')")
    assert r.verdict == Verdict.ALLOW


def test_delete_without_where_blocked():
    engine = PolicyEngine()
    r = engine.evaluate("tool_call", "CALL: db.execute('DELETE FROM logs')")
    assert r.blocked


def test_amount_threshold_approval():
    engine = PolicyEngine()
    r = engine.evaluate("decision", "Approved: refund $1,500 for order #12345")
    assert r.verdict == Verdict.APPROVAL
    assert "approval-high-amount" in r.triggered


def test_amount_below_threshold_allowed():
    engine = PolicyEngine()
    r = engine.evaluate("decision", "Approved: refund $45 for order #12345")
    assert r.verdict == Verdict.ALLOW


def test_rate_limit():
    engine = PolicyEngine()
    for i in range(61):
        r = engine.evaluate("tool_call", f"CALL: api.post('/task/{i}')")
    assert r.verdict == Verdict.DENY
    assert "rate-limit-tool-calls" in r.triggered


def test_api_key_leak_blocked():
    engine = PolicyEngine()
    r = engine.evaluate("decision", "API key: sk-abc123def456ghi789jklmnopqrstuvwx")
    assert r.blocked
    assert "block-api-key-leak" in r.triggered
