"""Tests for storage.py — SQLiteTrail compatibility wrapper + AuditEvent."""

import json
import warnings
from unittest.mock import MagicMock, mock_open, patch

import pytest

from agent_seal.core.chain import ChainEvent
from agent_seal.storage import AuditEvent, SQLiteTrail

# ═══════════════════════════ FIXTURES ═══════════════════════════


@pytest.fixture
def mock_engine():
    """Mock AuditEngine so no real DB is created."""
    with patch("agent_seal.storage.AuditEngine") as m:
        instance = m.return_value
        instance.log.return_value = ChainEvent(
            event_id="evt-001",
            session_id="sess-1",
            sequence=0,
            timestamp=1719000000.0,
            event_type="decision",
            agent_id="bot-1",
            prompt_version="v1",
            input_snapshot="in",
            output_snapshot="out",
            metadata={"k": "v"},
            prev_hash="",
            hash="abcd1234",
        )
        instance.sessions.return_value = ["sess-1", "sess-2"]
        instance.stats.return_value = {
            "total_events": 4,
            "sessions": 2,
            "event_types": {"decision": 2, "tool_call": 2},
        }
        instance.verify.return_value = True
        instance.read.side_effect = lambda sid: [
            {
                "event_id": f"evt-{i}",
                "session_id": sid,
                "timestamp": 1719000000.0 + i,
                "event_type": "decision" if i % 2 == 0 else "tool_call",
                "agent_id": "bot-1",
            }
            for i in range(2)
        ]

        # query() side-effect: mirrors the real engine.query() behaviour
        # by delegating to read/sessions, then filtering in Python.
        # This matches what JSONLStore.query_events does.
        def _query_mock(session_id=None, event_type=None, limit=100, offset=0):
            sids = [session_id] if session_id else instance.sessions()
            all_events = []
            for sid in sids:
                all_events.extend(instance.read(sid))
            if event_type:
                all_events = [e for e in all_events if e.get("event_type") == event_type]
            total = len(all_events)
            page = all_events[offset : offset + limit]
            return page, total

        instance.query.side_effect = _query_mock
        yield m


@pytest.fixture
def sqlite_trail(mock_engine):
    """Create a SQLiteTrail instance, capturing DeprecationWarning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        t = SQLiteTrail("/tmp/test.db")
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        yield t


# ═══════════════════════════ DeprecationWarning ═══════════════════════════


class TestDeprecation:
    """SQLiteTrail emits DeprecationWarning on construction."""

    def test_deprecation_warning_emitted(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            SQLiteTrail("/tmp/test.db")
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "AuditEngine" in str(w[0].message)

    def test_engine_created_with_sqlite_uri(self, mock_engine, sqlite_trail):
        """The internal AuditEngine is created with a sqlite:// URI."""
        mock_engine.assert_called_once_with("sqlite:///tmp/test.db")


# ═══════════════════════════ Delegation — log ═══════════════════════════


class TestLog:
    """SQLiteTrail.log delegates to AuditEngine.log and returns AuditEvent."""

    def test_log_delegates_to_engine(self, sqlite_trail, mock_engine):
        event = sqlite_trail.log(
            session_id="sess-1",
            event_type="decision",
            agent_id="bot-1",
            prompt_version="v1",
            input_snapshot="input text",
            output_snapshot="output text",
            metadata={"key": "val"},
        )
        mock_engine.return_value.log.assert_called_once_with(
            session_id="sess-1",
            event_type="decision",
            agent_id="bot-1",
            prompt_version="v1",
            input_text="input text",
            output_text="output text",
            metadata={"key": "val"},
        )
        assert isinstance(event, AuditEvent)
        assert event.event_id == "evt-001"

    def test_log_returns_audit_event_with_all_fields(self, sqlite_trail, mock_engine):
        event = sqlite_trail.log("sess-1", "tool_call", "agent-x", "v3", "i", "o")
        assert event.event_id == "evt-001"
        assert event.session_id == "sess-1"
        assert event.event_type == "decision"
        assert event.agent_id == "bot-1"
        assert event.prompt_version == "v1"
        assert event.input_snapshot == "in"
        assert event.output_snapshot == "out"
        assert event.metadata == {"k": "v"}
        assert event.prev_hash == ""
        assert event.hash == "abcd1234"
        # storage.AuditEvent has an id field (not sequence-related)
        assert event.id is None  # from_chain_event without row_id


# ═══════════════════════════ Delegation — verify ═══════════════════════════


class TestVerify:
    """SQLiteTrail.verify delegates to AuditEngine.verify re-raising ValueError."""

    def test_verify_delegates(self, sqlite_trail, mock_engine):
        result = sqlite_trail.verify()
        mock_engine.return_value.verify.assert_called_once_with(session_id=None)
        assert result is True

    def test_verify_passthrough_value_error(self, sqlite_trail, mock_engine):
        """SQLiteTrail.verify does NOT wrap ValueError — re-raises as-is."""
        mock_engine.return_value.verify.side_effect = ValueError("chain broken")
        with pytest.raises(ValueError, match="chain broken"):
            sqlite_trail.verify()


# ═══════════════════════════ Delegation — search ═══════════════════════════


class TestSearch:
    """SQLiteTrail.search delegates and filters correctly."""

    def test_search_without_filters(self, sqlite_trail, mock_engine):
        results = sqlite_trail.search()
        mock_engine.return_value.sessions.assert_called_once()
        assert len(results) == 4  # 2 sessions x 2 events each

    def test_search_with_session_id(self, sqlite_trail, mock_engine):
        results = sqlite_trail.search(session_id="sess-1")
        assert len(results) == 2

    def test_search_with_event_type_filter(self, sqlite_trail, mock_engine):
        results = sqlite_trail.search(event_type="decision")
        assert len(results) == 2  # 1 per session (even-indexed)

    def test_search_respects_limit(self, sqlite_trail, mock_engine):
        results = sqlite_trail.search(limit=1)
        assert len(results) == 1

    def test_search_outer_break_when_limit_reached(self, mock_engine):
        """Outer loop break when limit hit before next session."""
        mock_engine.return_value.sessions.return_value = ["s1", "s2", "s3"]
        mock_engine.return_value.read.side_effect = lambda sid: [
            {"event_id": f"e-{sid}", "event_type": "decision"} for _ in range(2)
        ]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            t = SQLiteTrail("/tmp/x.db")
        results = t.search(limit=1)
        assert len(results) == 1

    def test_search_both_filters_match_some(self, mock_engine):
        """Both event_type and agent_id filters applied, agent_id rejects one."""
        mock_engine.return_value.sessions.return_value = ["s1"]
        mock_engine.return_value.read.side_effect = lambda sid: [
            {"event_id": "e1", "session_id": sid, "event_type": "decision", "agent_id": "bot-1"},
            {"event_id": "e2", "session_id": sid, "event_type": "tool_call", "agent_id": "bot-2"},
        ]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            t = SQLiteTrail("/tmp/x.db")
        results = t.search(event_type="decision", agent_id="bot-1")
        assert len(results) == 1
        assert results[0]["event_id"] == "e1"

    def test_search_agent_id_filter_rejects_after_event_type_passes(self, mock_engine):
        """agent_id filter continue is hit after event_type passes."""
        mock_engine.return_value.sessions.return_value = ["s1"]
        mock_engine.return_value.read.side_effect = lambda sid: [
            {
                "event_id": "e1",
                "session_id": sid,
                "event_type": "decision",
                "agent_id": "wrong-bot",
            },
            {"event_id": "e2", "session_id": sid, "event_type": "other", "agent_id": "bot-1"},
        ]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            t = SQLiteTrail("/tmp/x.db")
        # event_type="decision" passes for e1, but agent_id="bot-1" fails → continue
        # e2 has event_type="other" → continue before agent_id check
        results = t.search(event_type="decision", agent_id="bot-1")
        assert len(results) == 0  # e1 rejected by agent_id, e2 rejected by event_type


# ═══════════════════════════ Delegation — sessions / stats ═══════════════════


class TestSessionsAndStats:
    """sessions() and stats() delegate directly."""

    def test_sessions_delegates(self, sqlite_trail, mock_engine):
        sids = sqlite_trail.sessions()
        mock_engine.return_value.sessions.assert_called_once()
        assert sids == ["sess-1", "sess-2"]

    def test_stats_delegates(self, sqlite_trail, mock_engine):
        s = sqlite_trail.stats()
        mock_engine.return_value.stats.assert_called_once()
        assert s["total_events"] == 4


# ═══════════════════════════ Extra API methods ═══════════════════════════


class TestExtraAPI:
    """count_by_type, time_range, purge_before, export_jsonl."""

    def test_count_by_type_delegates_to_stats(self, sqlite_trail, mock_engine):
        counts = sqlite_trail.count_by_type()
        assert counts == {"decision": 2, "tool_call": 2}

    def test_time_range_with_events(self, sqlite_trail, mock_engine):
        result = sqlite_trail.time_range()
        assert result is not None
        min_ts, max_ts = result
        assert min_ts == 1719000000.0
        assert max_ts == 1719000001.0

    def test_time_range_empty(self, sqlite_trail, mock_engine):
        mock_engine.return_value.sessions.return_value = []
        result = sqlite_trail.time_range()
        assert result is None

    @patch("agent_seal.storage.sqlite3")
    def test_purge_before_deletes_old_events(self, mock_sqlite3, sqlite_trail):
        """purge_before runs a SQL DELETE directly."""
        mock_conn = mock_sqlite3.connect.return_value
        mock_cursor = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_cursor.rowcount = 5

        count = sqlite_trail.purge_before(1718000000.0)

        mock_sqlite3.connect.assert_called_once_with("/tmp/test.db")
        mock_conn.execute.assert_called_once_with(
            "DELETE FROM events WHERE timestamp < ?",
            (1718000000.0,),
        )
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()
        assert count == 5

    def test_export_jsonl_writes_events_to_file(self, sqlite_trail, mock_engine):
        mock_engine.return_value.read.side_effect = lambda sid: [
            {"event_id": f"e1-{sid}", "event_type": "decision"},
            {"event_id": f"e2-{sid}", "event_type": "tool_call"},
        ]

        m_open = mock_open()
        with patch("builtins.open", m_open):
            sqlite_trail.export_jsonl("/tmp/export.jsonl")

        m_open.assert_called_once_with("/tmp/export.jsonl", "w", encoding="utf-8")
        handle = m_open()
        # 2 sessions x 2 events = 4 lines
        assert handle.write.call_count == 4

        # Verify first written line is valid JSON
        first_call_args = handle.write.call_args_list[0][0][0]
        first_obj = json.loads(first_call_args.strip())
        assert first_obj["event_id"] == "e1-sess-1"


# ═══════════════════════════ AuditEvent type conversion ═══════════════════════


class TestAuditEvent:
    """storage.AuditEvent.from_chain_event and from_dict."""

    def test_from_chain_event_with_row_id(self):
        ce = ChainEvent(
            event_id="evt-001",
            session_id="sess-1",
            sequence=0,
            timestamp=1719000000.0,
            event_type="decision",
            agent_id="bot-1",
            prompt_version="v1",
            input_snapshot="input",
            output_snapshot="output",
            metadata={"k": "v"},
            prev_hash="",
            hash="deadbeef",
        )
        ae = AuditEvent.from_chain_event(ce, row_id=42)
        assert ae.event_id == "evt-001"
        assert ae.session_id == "sess-1"
        assert ae.timestamp == 1719000000.0
        assert ae.event_type == "decision"
        assert ae.agent_id == "bot-1"
        assert ae.prompt_version == "v1"
        assert ae.input_snapshot == "input"
        assert ae.output_snapshot == "output"
        assert ae.metadata == {"k": "v"}
        assert ae.prev_hash == ""
        assert ae.hash == "deadbeef"
        assert ae.id == 42

    def test_from_chain_event_without_row_id(self):
        ce = ChainEvent(
            event_id="evt-002",
            session_id="sess-2",
            sequence=1,
            timestamp=1719100000.0,
            event_type="tool_call",
            agent_id="agent-x",
            prompt_version="v2",
            input_snapshot="in",
            output_snapshot="out",
            metadata={},
            prev_hash="prev",
            hash="cur",
        )
        ae = AuditEvent.from_chain_event(ce)  # no row_id
        assert ae.id is None

    def test_from_dict_converts_all_fields(self):
        d = {
            "event_id": "evt-003",
            "session_id": "sess-3",
            "timestamp": 1719200000.0,
            "event_type": "guardrail",
            "agent_id": "bot-2",
            "prompt_version": "v5",
            "input_snapshot": "in3",
            "output_snapshot": "out3",
            "metadata": {"rule": "no-pii"},
            "prev_hash": "ph",
            "hash": "h3",
            "id": 99,
        }
        ae = AuditEvent.from_dict(d)
        assert ae.event_id == "evt-003"
        assert ae.session_id == "sess-3"
        assert ae.timestamp == 1719200000.0
        assert ae.event_type == "guardrail"
        assert ae.agent_id == "bot-2"
        assert ae.prompt_version == "v5"
        assert ae.input_snapshot == "in3"
        assert ae.output_snapshot == "out3"
        assert ae.metadata == {"rule": "no-pii"}
        assert ae.prev_hash == "ph"
        assert ae.hash == "h3"
        assert ae.id == 99

    def test_from_dict_uses_defaults_for_missing_keys(self):
        ae = AuditEvent.from_dict({})
        assert ae.event_id == ""
        assert ae.session_id == ""
        assert ae.timestamp == 0.0
        assert ae.event_type == ""
        assert ae.agent_id == ""
        assert ae.prompt_version == ""
        assert ae.input_snapshot == ""
        assert ae.output_snapshot == ""
        assert ae.metadata == {}
        assert ae.prev_hash == ""
        assert ae.hash == ""
        assert ae.id is None
