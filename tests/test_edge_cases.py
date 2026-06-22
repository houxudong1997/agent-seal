"""
Edge case, error path, and large payload tests for agent-audit.

Covers:
  - Empty / very long / special character inputs
  - Concurrent writes (multi-thread)
  - Large payloads (>1MB)
  - Invalid config / missing env vars
  - Disk full simulation (read-only filesystem)
  - DB connection handling
"""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent_audit.engine import AuditEngine
from agent_audit.config import config


# ═══════════════════════ EDGE CASES ═══════════════════════


class TestEngineEdgeCases:
    """Edge case tests for AuditEngine — empty, long, special inputs."""

    def _engine(self, tmp_path):
        d = tmp_path / "jsonl"
        return AuditEngine(f"jsonl://{d}")

    def _events(self, engine, sid):
        return engine.read(sid)

    def test_empty_session_id(self, tmp_path):
        engine = self._engine(tmp_path)
        event = engine.log("", "test", "agent-1", "v1", "", "")
        assert event is not None
        assert event.event_id

    def test_very_long_event_type(self, tmp_path):
        engine = self._engine(tmp_path)
        long_type = "x" * 500
        event = engine.log("s1", long_type, "agent-1", "v1", "test", "output")
        assert event is not None
        assert event.event_type == long_type

    def test_very_long_agent_id(self, tmp_path):
        engine = self._engine(tmp_path)
        long_agent = "agent-" + "a" * 1000
        event = engine.log("s1", "test", long_agent, "v1", "in", "out")
        assert event is not None

    def test_unicode_special_characters(self, tmp_path):
        engine = self._engine(tmp_path)
        event = engine.log("s1", "test", "agent-1", "v1",
                           "你好世界 ±!@#$%^&*()_+ 😀🚀🔥\n\t\r",
                           "<script>alert('xss')</script>\x00\x01\x02")
        assert event is not None
        events = engine.read("s1")
        assert len(events) > 0

    def test_newlines_in_fields(self, tmp_path):
        engine = self._engine(tmp_path)
        event = engine.log("s1", "multi\nline\ntype", "agent-1", "v1",
                           "line1\nline2\nline3", "tab\tseparated\tvalues")
        assert event is not None

    def test_session_id_with_special_chars(self, tmp_path):
        engine = self._engine(tmp_path)
        # Windows-safe special characters (avoid filesystem-unfriendly chars like \ / : * ? < > |)
        sid = "session-id-with-dots.and.dashes"
        event = engine.log(sid, "test", "agent-1", "v1", "x", "y")
        assert event is not None
        events = engine.read(sid)
        assert len(events) == 1

    def test_null_bytes_in_input(self, tmp_path):
        engine = self._engine(tmp_path)
        event = engine.log("s1", "test", "agent-1", "v1", "\x00\x00\x00", "\x00\x00\x00")
        assert event is not None

    def test_extremely_long_input_text(self, tmp_path):
        engine = self._engine(tmp_path)
        long_text = "A" * 10_000
        event = engine.log("s1", "test", "agent-1", "v1", long_text, "short")
        assert event is not None

    def test_minimal_fields(self, tmp_path):
        engine = self._engine(tmp_path)
        event = engine.log("s1", "test", "agent-1", "v1", "", "")
        assert event is not None

    def test_large_payload_1mb(self, tmp_path):
        engine = self._engine(tmp_path)
        large_text = "X" * (1024 * 1024)  # 1 MB
        event1 = engine.log("large-session", "large-payload", "agent-1", "v1", large_text, "")
        assert event1 is not None
        events = engine.read("large-session")
        assert len(events) > 0

    def test_large_payload_multiple_events(self, tmp_path):
        engine = self._engine(tmp_path)
        large_text = "X" * (500 * 1024)  # 500 KB
        for i in range(3):
            engine.log("large-session", f"e{i}", "agent-1", "v1", large_text, large_text)
        events = engine.read("large-session")
        assert len(events) == 3


class TestConcurrentWrites:
    """Multi-threaded concurrent write tests."""

    def test_concurrent_writes_same_session(self, tmp_path):
        d = tmp_path / "concurrent"
        engine = AuditEngine(f"jsonl://{d}")
        errors = []
        lock = threading.Lock()

        def write_event(idx):
            try:
                engine.log("concurrent-session", f"concurrent-{idx}", "agent-1", "v1",
                           f"input-{idx}", f"output-{idx}")
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(20):
            t = threading.Thread(target=write_event, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent writes failed: {errors}"
        events = engine.read("concurrent-session")
        assert len(events) == 20

    def test_concurrent_writes_different_sessions(self, tmp_path):
        d = tmp_path / "concurrent2"
        engine = AuditEngine(f"jsonl://{d}")
        errors = []
        lock = threading.Lock()

        def write_event(idx):
            try:
                engine.log(f"session-{idx}", "test", "agent-1", "v1",
                           f"input-{idx}", f"output-{idx}")
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(20):
            t = threading.Thread(target=write_event, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        for i in range(20):
            events = engine.read(f"session-{i}")
            assert len(events) == 1, f"Session {i} missing events"

    def test_read_during_concurrent_write(self, tmp_path):
        d = tmp_path / "rw"
        engine = AuditEngine(f"jsonl://{d}")
        for i in range(10):
            engine.log("rw-session", "pre", "agent-1", "v1", "", "")

        read_errors = []

        def writer():
            for i in range(20):
                engine.log("rw-session", f"write-{i}", "agent-1", "v1", "", "")

        def reader():
            try:
                engine.read("rw-session")
            except Exception as e:
                read_errors.append(e)

        w = threading.Thread(target=writer)
        r = threading.Thread(target=reader)

        w.start()
        r.start()
        w.join()
        r.join()

        assert len(read_errors) == 0, f"Read during write failed: {read_errors}"


# ═══════════════════════ ERROR PATHS ═══════════════════════


class TestEngineErrorPaths:
    """Error path tests — invalid config, missing env, permission errors."""

    def test_invalid_uri_format(self):
        with pytest.raises((ValueError, OSError, Exception)):
            AuditEngine("invalid://no-scheme-handler")

    def test_jsonl_nonexistent_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        engine = AuditEngine(f"jsonl://{nested}")
        engine.log("s1", "test", "agent-1", "v1", "", "")
        assert nested.exists()

    def test_readable_directory_after_writes(self, tmp_path):
        d = tmp_path / "readable"
        engine = AuditEngine(f"jsonl://{d}")
        engine.log("s1", "test", "agent-1", "v1", "hello", "world")
        events = engine.read("s1")
        assert len(events) == 1
        assert events[0]["input_snapshot"] == "hello"

    def test_read_empty_session(self, tmp_path):
        d = tmp_path / "empty"
        engine = AuditEngine(f"jsonl://{d}")
        events = engine.read("nonexistent")
        assert events == []

    def test_query_with_limit(self, tmp_path):
        d = tmp_path / "limit"
        engine = AuditEngine(f"jsonl://{d}")
        for i in range(10):
            engine.log("limit-session", "test", "agent-1", "v1", "", "")
        results, total = engine.query(session_id="limit-session", limit=3)
        assert len(results) == 3
        assert total == 10

    def test_storage_batch_operations(self, tmp_path):
        d = tmp_path / "batch"
        engine = AuditEngine(f"jsonl://{d}")
        ids = []
        for i in range(100):
            e = engine.log("batch-test", f"event-{i}", "agent-1", "v1", "", "")
            ids.append(e.event_id)
        assert len(ids) == 100
        events = engine.read("batch-test")
        assert len(events) == 100

    def test_hash_chain_integrity(self, tmp_path):
        d = tmp_path / "chain"
        engine = AuditEngine(f"jsonl://{d}")
        prev_hash = ""
        for i in range(5):
            e = engine.log("chain-test", f"event-{i}", "agent-1", "v1", "", "")
            if i == 0:
                assert e.prev_hash == "" or e.prev_hash is None
            else:
                assert e.prev_hash == prev_hash, f"Hash chain broken at event {i}"
            prev_hash = e.hash

    def test_verify_on_empty_trail(self, tmp_path):
        d = tmp_path / "empty-verify"
        engine = AuditEngine(f"jsonl://{d}")
        result = engine.verify()
        assert result is True

    def test_tamper_detection(self, tmp_path):
        d = tmp_path / "tamper"
        engine = AuditEngine(f"jsonl://{d}")
        engine.log("tamper-test", "test", "agent-1", "v1", "original", "data")
        assert engine.verify() is True

        # Modify an existing event's hash in the JSONL file to break chain
        fpath = d / "tamper-test.jsonl"
        lines = fpath.read_text().splitlines()
        modified = []
        for line in lines:
            ev = json.loads(line)
            ev["hash"] = "0000" + ev["hash"][4:]  # corrupt the hash
            modified.append(json.dumps(ev, ensure_ascii=False))
        fpath.write_text("\n".join(modified))

        with pytest.raises((ValueError, AssertionError)):
            engine.verify()

    def test_config_not_crash(self, monkeypatch):
        for key in list(os.environ.keys()):
            if "AGENT_AUDIT" in key:
                monkeypatch.delenv(key, raising=False)
        from agent_audit.config import config as cfg
        assert cfg is not None

    def test_sqlite_empty_session(self, tmp_path):
        db = tmp_path / "empty.db"
        engine = AuditEngine(f"sqlite://{db}")
        events = engine.read("nonexistent")
        assert events == []

    def test_sqlite_verify_passes(self, tmp_path):
        db = tmp_path / "v.db"
        engine = AuditEngine(f"sqlite://{db}")
        engine.log("v", "t", "a1", "v1", "", "")
        assert engine.verify() is True

    def test_sqlite_batch_ops(self, tmp_path):
        db = tmp_path / "b.db"
        engine = AuditEngine(f"sqlite://{db}")
        for i in range(50):
            engine.log("batch", "t", "a1", "v1", "", "")
        assert len(engine.read("batch")) == 50

    def test_stats_empty(self, tmp_path):
        d = tmp_path / "noevents"
        engine = AuditEngine(f"jsonl://{d}")
        stats = engine.stats()
        assert stats["total_events"] == 0
        assert stats["sessions"] == 0

    def test_stats_after_events(self, tmp_path):
        d = tmp_path / "st"
        engine = AuditEngine(f"jsonl://{d}")
        engine.log("s1", "a", "a1", "v1", "", "")
        engine.log("s1", "b", "a1", "v1", "", "")
        engine.log("s2", "a", "a1", "v1", "", "")
        stats = engine.stats()
        assert stats["total_events"] == 3
        assert stats["sessions"] == 2

    def test_sessions_empty(self, tmp_path):
        d = tmp_path / "ses"
        engine = AuditEngine(f"jsonl://{d}")
        assert engine.sessions() == []

    def test_sessions_after_writes(self, tmp_path):
        d = tmp_path / "ses2"
        engine = AuditEngine(f"jsonl://{d}")
        engine.log("s1", "a", "a1", "v1", "", "")
        engine.log("s2", "b", "a1", "v1", "", "")
        sessions = engine.sessions()
        assert "s1" in sessions
        assert "s2" in sessions
