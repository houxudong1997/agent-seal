"""Tests for encrypted audit storage."""

import tempfile

from agent_audit.core.encrypted import EncryptedStore, generate_master_key


def test_write_and_read():
    with tempfile.TemporaryDirectory() as d:
        key = generate_master_key()
        store = EncryptedStore(d, key)

        store.write("sess-1", {"event_type": "decision", "output": "approved"})
        store.write("sess-1", {"event_type": "tool_call", "output": "refund executed"})

        events = store.read("sess-1")
        assert len(events) == 2
        assert events[0]["event_type"] == "decision"
        assert events[1]["output"] == "refund executed"


def test_wrong_key_fails():
    with tempfile.TemporaryDirectory() as d:
        store1 = EncryptedStore(d, generate_master_key())
        store1.write("sess-1", {"msg": "hello"})

        store2 = EncryptedStore(d, generate_master_key())
        try:
            store2.read("sess-1")
            assert False, "Should have raised"
        except ValueError:
            pass  # expected


def test_sessions():
    with tempfile.TemporaryDirectory() as d:
        store = EncryptedStore(d, generate_master_key())
        store.write("a", {"x": 1})
        store.write("b", {"x": 2})
        assert store.sessions() == ["a", "b"]


def test_stats():
    with tempfile.TemporaryDirectory() as d:
        store = EncryptedStore(d, generate_master_key())
        store.write("s1", {"x": 1})
        store.write("s1", {"x": 2})
        store.write("s2", {"x": 3})
        assert store.stats()["total_events"] == 3
        assert store.stats()["sessions"] == 2
