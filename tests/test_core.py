"""Tests for the new core architecture."""

import tempfile

from agent_seal.core.chain import SessionChain
from agent_seal.core.storage import AuditEngine, JSONLStore, SQLiteStore
from agent_seal.policy.engine import PolicyEngine, Verdict


class TestSessionChain:
    def test_append_and_verify(self):
        chain = SessionChain("sess-1")
        chain.append("decision", "bot", "v1", "in", "out")
        chain.append("tool_call", "bot", "v1", "in", "result")
        assert chain.verify()

    def test_tampered_chain_fails(self):
        chain = SessionChain("sess-1")
        chain.append("decision", "bot", "v1", "in", "out")
        # Tamper
        chain.events[0].output_snapshot = "CORRUPTED"
        try:
            chain.verify()
            assert False
        except ValueError:
            pass

    def test_to_dicts_roundtrip(self):
        chain = SessionChain("sess-1")
        chain.append("a", "b", "v1", "in", "out")
        data = chain.to_dicts()
        chain2 = SessionChain.from_dicts("sess-1", data)
        assert chain2.verify()
        assert len(chain2.events) == 1


class TestJSONLStore:
    def test_store_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            store = JSONLStore(d)
            chain = SessionChain("sess-1")
            e = chain.append("decision", "bot", "v1", "in", "out")
            store.write(e)
            data = store.read_session("sess-1")
            assert len(data) == 1
            assert data[0]["event_type"] == "decision"

    def test_verify(self):
        with tempfile.TemporaryDirectory() as d:
            store = JSONLStore(d)
            chain = SessionChain("sess-1")
            store.write(chain.append("test", "bot", "v1", "in", "out"))
            assert store.verify_session("sess-1")

    def test_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            store = JSONLStore(d)
            store.write(SessionChain("a").append("t", "b", "v1", "i", "o"))
            store.write(SessionChain("b").append("t", "b", "v1", "i", "o"))
            assert store.sessions() == ["a", "b"]


class TestSQLiteStore:
    def test_store_and_read(self):
        store = SQLiteStore(":memory:")
        chain = SessionChain("sess-1")
        store.write(chain.append("decision", "bot", "v1", "in", "out"))
        assert store.stats()["total_events"] == 1

    def test_verify(self):
        store = SQLiteStore(":memory:")
        chain = SessionChain("sess-1")
        store.write(chain.append("test", "bot", "v1", "in", "out"))
        assert store.verify_session("sess-1")


class TestAuditEngine:
    def test_jsonl_backend(self):
        with tempfile.TemporaryDirectory() as d:
            engine = AuditEngine(f"jsonl://{d}")
            engine.log("sess-1", "decision", "bot", "v1", "in", "out")
            assert engine.verify("sess-1")

    def test_sqlite_backend(self):
        engine = AuditEngine("sqlite://:memory:")
        engine.log("sess-1", "decision", "bot", "v1", "in", "out")
        engine.log("sess-1", "tool_call", "bot", "v1", "in", "result")
        assert engine.stats()["total_events"] == 2
        assert engine.verify("sess-1")


class TestPolicyEngine:
    def test_yaml_rules_loaded(self):
        engine = PolicyEngine()
        assert len(engine.rules) >= 5

    def test_block_rm_rf(self):
        engine = PolicyEngine()
        r = engine.evaluate("tool_call", "CALL: shell.run('rm -rf /tmp/data')")
        assert r.blocked

    def test_warn_internal_ip(self):
        engine = PolicyEngine()
        r = engine.evaluate("tool_call", "CALL: http.get('http://192.168.1.1/api')")
        assert r.verdict == Verdict.WARN

    def test_allow_safe(self):
        engine = PolicyEngine()
        r = engine.evaluate("tool_call", "CALL: db.query('SELECT * FROM users')")
        assert r.verdict == Verdict.ALLOW

    def test_api_key_leak_blocked(self):
        engine = PolicyEngine()
        r = engine.evaluate("decision", "Here is my key: sk-abc123def456ghi789jklmno")
        assert r.blocked
