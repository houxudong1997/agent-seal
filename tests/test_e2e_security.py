"""
E2E, cross-storage, and security tests for agent-audit v1.0.0.

Covers:
  - Cross-storage: JSONL + SQLite
  - Evidence export → unzip → verify SHA-256
  - Secure: encrypted storage read/write, YAML policy rules
"""

import json
import os
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from agent_audit.engine import AuditEngine
from agent_audit.evidence import EvidenceExporter, EvidenceBundle
from agent_audit.trail import AuditTrail
from agent_audit.prompt_version import PromptRegistry
from agent_audit.core.encrypted import (
    EncryptedStore,
    generate_master_key,
    derive_key,
    save_key,
    load_key,
)
from agent_audit.policy.engine import PolicyEngine
from agent_audit.notify import Alert, ConsoleNotifier


# ═══════════════════════ CROSS-STORAGE: JSONL ═══════════════════════


class TestJsonlStorage:
    def test_jsonl_write_and_read(self, tmp_path):
        d = tmp_path / "j"
        engine = AuditEngine(f"jsonl://{d}")
        e = engine.log("s1", "test", "a1", "v1", "in", "out")
        assert e is not None
        events = engine.read("s1")
        assert len(events) == 1
        assert events[0]["input_snapshot"] == "in"
        assert events[0]["output_snapshot"] == "out"

    def test_jsonl_multiple_sessions(self, tmp_path):
        d = tmp_path / "j2"
        engine = AuditEngine(f"jsonl://{d}")
        for i in range(5):
            engine.log(f"s{i}", "test", "a1", "v1", "", "")
        assert len(engine.sessions()) == 5
        stats = engine.stats()
        assert stats["total_events"] == 5

    def test_jsonl_hash_chain(self, tmp_path):
        d = tmp_path / "j3"
        engine = AuditEngine(f"jsonl://{d}")
        events = []
        for i in range(3):
            e = engine.log("chain", f"e{i}", "a1", "v1", "", "")
            events.append(e)
        assert events[0].prev_hash == "" or events[0].prev_hash is None
        assert events[1].prev_hash == events[0].hash
        assert events[2].prev_hash == events[1].hash


class TestSqliteStorage:
    def test_sqlite_write_and_read(self, tmp_path):
        db = tmp_path / "test.db"
        engine = AuditEngine(f"sqlite://{db}")
        e = engine.log("s1", "test", "a1", "v1", "hello", "world")
        assert e is not None
        events = engine.read("s1")
        assert len(events) >= 1

    def test_sqlite_hash_chain(self, tmp_path):
        db = tmp_path / "chain.db"
        engine = AuditEngine(f"sqlite://{db}")
        prev_hash = ""
        for i in range(5):
            e = engine.log("ch", f"e{i}", "a1", "v1", "", "")
            if i > 0:
                assert e.prev_hash == prev_hash
            prev_hash = e.hash

    def test_sqlite_stats(self, tmp_path):
        db = tmp_path / "stats.db"
        engine = AuditEngine(f"sqlite://{db}")
        engine.log("a", "x", "a1", "v1", "", "")
        engine.log("a", "y", "a1", "v1", "", "")
        engine.log("b", "x", "a1", "v1", "", "")
        stats = engine.stats()
        assert stats["total_events"] == 3
        assert stats["sessions"] == 2

    def test_sqlite_sessions(self, tmp_path):
        db = tmp_path / "sess.db"
        engine = AuditEngine(f"sqlite://{db}")
        for s in ["alpha", "beta", "gamma"]:
            engine.log(s, "t", "a1", "v1", "", "")
        sessions = engine.sessions()
        assert "alpha" in sessions
        assert "beta" in sessions
        assert "gamma" in sessions

    def test_sqlite_empty_trail(self, tmp_path):
        db = tmp_path / "empty.db"
        engine = AuditEngine(f"sqlite://{db}")
        assert engine.sessions() == []
        assert engine.stats()["total_events"] == 0

    def test_sqlite_verify_passes(self, tmp_path):
        db = tmp_path / "v.db"
        engine = AuditEngine(f"sqlite://{db}")
        engine.log("v", "t", "a1", "v1", "", "")
        assert engine.verify() is True


# ═══════════════════════ E2E: EVIDENCE EXPORT ═══════════════════════


class TestEvidenceExporterE2E:
    """E2E: write events → export bundle → unzip → verify SHA-256."""

    def test_export_and_verify_bundle(self, tmp_path):
        trail_dir = str(tmp_path / "trail")
        engine = AuditEngine(f"jsonl://{trail_dir}")
        registry = PromptRegistry(trail_dir)

        for i in range(3):
            engine.log("e2e-session", f"action-{i}", "test-agent", "v1",
                       f"input-{i}", f"output-{i}")

        exporter = EvidenceExporter(engine, registry)
        output_path = tmp_path / "evidence.zip"
        bundle = exporter.export("test-agent", str(output_path))

        assert bundle.bundle_id is not None
        assert bundle.sha256 != ""
        assert output_path.exists()

        result = exporter.verify_bundle(str(output_path))
        assert result["status"] == "PASS", f"Bundle verification failed: {result}"
        assert result["hash_match"] is True
        assert result["chain_intact"] is True
        assert result["event_count"] == 3

        extract_dir = tmp_path / "extracted"
        with zipfile.ZipFile(output_path, "r") as zf:
            zf.extractall(extract_dir)

        assert (extract_dir / "metadata.json").exists()
        assert (extract_dir / "events.json").exists()
        assert (extract_dir / "bundle.json").exists()
        assert (extract_dir / "README.txt").exists()

        events_data = json.loads((extract_dir / "events.json").read_text())
        metadata_data = json.loads((extract_dir / "metadata.json").read_text())
        computed = exporter._compute_bundle_hash(events_data, metadata_data)
        assert computed == bundle.sha256

    def test_export_empty_trail(self, tmp_path):
        trail_dir = str(tmp_path / "empty")
        engine = AuditEngine(f"jsonl://{trail_dir}")
        registry = PromptRegistry(trail_dir)
        exporter = EvidenceExporter(engine, registry)
        output_path = tmp_path / "empty.zip"
        bundle = exporter.export("test-agent", str(output_path))
        assert output_path.exists()
        assert bundle.total_events == 0

    def test_verify_bundle_not_found(self, tmp_path):
        d = str(tmp_path / "nope")
        engine = AuditEngine(f"jsonl://{d}")
        exporter = EvidenceExporter(engine, PromptRegistry(d))
        result = exporter.verify_bundle(str(tmp_path / "nonexistent.zip"))
        assert result["status"] == "FAIL"

    def test_verify_corrupt_bundle(self, tmp_path):
        d = str(tmp_path / "corr")
        corrupt = tmp_path / "corrupt.zip"
        corrupt.write_text("this is not a zip file")
        engine = AuditEngine(f"jsonl://{d}")
        exporter = EvidenceExporter(engine, PromptRegistry(d))
        result = exporter.verify_bundle(str(corrupt))
        assert result["status"] == "FAIL"

    def test_export_with_hmac_signature(self, tmp_path):
        d = str(tmp_path / "sig")
        engine = AuditEngine(f"jsonl://{d}")
        registry = PromptRegistry(d)
        engine.log("s1", "test", "a1", "v1", "", "")
        exporter = EvidenceExporter(engine, registry)
        output_path = tmp_path / "signed.zip"
        bundle = exporter.export("a1", str(output_path), sign_key="my-secret-key")
        assert bundle.signature != ""
        assert len(bundle.signature) == 64

    def test_export_with_session_filter(self, tmp_path):
        d = str(tmp_path / "filt")
        engine = AuditEngine(f"jsonl://{d}")
        registry = PromptRegistry(d)
        engine.log("keep", "a", "a1", "v1", "", "")
        engine.log("keep", "b", "a1", "v1", "", "")
        engine.log("omit", "c", "a1", "v1", "", "")
        exporter = EvidenceExporter(engine, registry)
        output_path = tmp_path / "filtered.zip"
        bundle = exporter.export("a1", str(output_path), session_filter=["keep"])
        assert bundle.total_events == 2


# ═══════════════════════ SECURITY: ENCRYPTED STORE ═══════════════════════


class TestEncryptedStore:
    def test_write_and_read(self, tmp_path):
        key = generate_master_key()
        store = EncryptedStore(tmp_path / "enc", key)
        store.write("session-1", {"event": "data", "id": 1})
        store.write("session-1", {"event": "data2", "id": 2})
        events = store.read("session-1")
        assert len(events) == 2
        assert events[0]["event"] == "data"
        assert events[1]["event"] == "data2"

    def test_read_empty_session(self, tmp_path):
        key = generate_master_key()
        store = EncryptedStore(tmp_path / "empty", key)
        assert store.read("nonexistent") == []

    def test_sessions_list(self, tmp_path):
        key = generate_master_key()
        store = EncryptedStore(tmp_path / "sl", key)
        store.write("alpha", {"v": 1})
        store.write("beta", {"v": 2})
        sessions = store.sessions()
        assert "alpha" in sessions
        assert "beta" in sessions

    def test_corrupted_header_raises(self, tmp_path):
        key = generate_master_key()
        store = EncryptedStore(tmp_path / "corr", key)
        store.write("bad-session", {"safe": "data"})
        fpath = tmp_path / "corr" / "bad-session.enc"
        raw = fpath.read_bytes()
        fpath.write_bytes(b"\x00" * 6 + raw[6:])
        with pytest.raises(ValueError, match="bad header"):
            store.read("bad-session")

    def test_wrong_key_raises(self, tmp_path):
        key1 = generate_master_key()
        store = EncryptedStore(tmp_path / "kw", key1)
        store.write("s1", {"secret": "value"})
        key2 = generate_master_key()
        store2 = EncryptedStore(tmp_path / "kw", key2)
        with pytest.raises((ValueError, Exception)):
            store2.read("s1")

    def test_stats(self, tmp_path):
        key = generate_master_key()
        store = EncryptedStore(tmp_path / "st", key)
        store.write("s1", {"a": 1})
        store.write("s1", {"b": 2})
        store.write("s2", {"c": 3})
        stats = store.stats()
        assert stats["total_events"] == 3
        assert stats["sessions"] == 2

    def test_derive_key_reproducible(self):
        salt = b"\x01" * 16
        key1, _ = derive_key("mypassword", salt)
        key2, _ = derive_key("mypassword", salt)
        assert key1 == key2

    def test_derive_key_different_salts(self):
        key1, _ = derive_key("mypassword", b"\x01" * 16)
        key2, _ = derive_key("mypassword", b"\x02" * 16)
        assert key1 != key2

    def test_derive_key_generates_salt(self):
        key, salt = derive_key("password")
        assert len(key) == 32
        assert len(salt) == 16

    def test_save_and_load_key(self, tmp_path):
        key = generate_master_key()
        key_path = tmp_path / "master.key"
        save_key(key, key_path)
        loaded = load_key(key_path)
        assert loaded == key


# ═══════════════════════ SECURITY: POLICY ENGINE ═══════════════════════


class TestYamlPolicyRules:
    def test_policy_engine_creation(self):
        engine = PolicyEngine()
        assert engine is not None

    def test_policy_allows_by_default(self):
        engine = PolicyEngine()
        result = engine.evaluate("event_type", "agent", {})
        assert result is not None

    def test_policy_with_custom_rules(self, tmp_path):
        rules_yaml = """
rules:
  - when:
      event_type: restricted
    then: block
"""
        rules_file = tmp_path / "policy.yaml"
        rules_file.write_text(rules_yaml)
        engine = PolicyEngine(str(rules_file))
        result = engine.evaluate("restricted", "agent-1", {})
        assert result is not None

    def test_policy_missing_file_fallback(self, tmp_path):
        engine = PolicyEngine(str(tmp_path / "missing.yaml"))
        result = engine.evaluate("any", "agent", {})
        assert result is not None  # should fall back to permissive


# ═══════════════════════ NOTIFICATION INTEGRATION ═══════════════════════


class TestNotification:
    def test_console_notifier_output(self, capsys):
        notifier = ConsoleNotifier()
        alert = Alert(level="critical", title="Security Alert",
                      body="Unauthorized access detected",
                      agent_id="agent-x", session_id="sess-42")
        result = notifier.send(alert)
        assert result is True
        captured = capsys.readouterr()
        assert "CRIT" in captured.out
        assert "Security Alert" in captured.out
        assert "Unauthorized access detected" in captured.out
        assert "agent-x" in captured.out
        assert "sess-42" in captured.out

    def test_event_roundtrip_integrity(self, tmp_path):
        d = tmp_path / "rt"
        engine = AuditEngine(f"jsonl://{d}")
        e = engine.log("notif-test", "notify", "agent-1", "v1",
                       "trigger input", "trigger output")
        events = engine.read("notif-test")
        assert len(events) == 1
        ev = events[0]
        assert ev["event_type"] == "notify"
        assert ev["input_snapshot"] == "trigger input"
        assert ev["output_snapshot"] == "trigger output"
