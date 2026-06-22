"""Tests for trail.py — AuditTrail compatibility wrapper + AuditEvent."""

import warnings
from unittest.mock import patch

import pytest

from agent_audit.core.chain import ChainEvent
from agent_audit.trail import AuditEvent, AuditIntegrityError, AuditTrail

# ═══════════════════════════ FIXTURES ═══════════════════════════


@pytest.fixture
def mock_engine():
    """Mock AuditEngine so no real store backend is created."""
    with patch("agent_audit.trail.AuditEngine") as m:
        instance = m.return_value
        # Provide sensible defaults for all delegated methods
        instance.log.return_value = ChainEvent(
            event_id="evt-001",
            session_id="sess-1",
            sequence=0,
            timestamp=1719000000.0,
            event_type="decision",
            agent_id="bot-1",
            prompt_version="v1",
            input_snapshot="input text",
            output_snapshot="output text",
            metadata={"key": "val"},
            prev_hash="",
            hash="abc123",
        )
        instance.sessions.return_value = ["sess-1", "sess-2"]
        instance.stats.return_value = {
            "total_events": 3,
            "sessions": 2,
            "event_types": {"decision": 3},
        }
        instance.verify.return_value = True
        instance.read.side_effect = lambda sid: [
            {"event_id": f"evt-{i}", "session_id": sid, "event_type": "decision"} for i in range(2)
        ]
        yield m


@pytest.fixture
def trail(mock_engine):
    """Create an AuditTrail instance, capturing the DeprecationWarning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        t = AuditTrail("/tmp/test-logs")
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        yield t


# ═══════════════════════════ DeprecationWarning ═══════════════════════════


class TestDeprecation:
    """AuditTrail emits DeprecationWarning on construction."""

    def test_deprecation_warning_emitted(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            AuditTrail("/tmp/test-logs")
            assert len(w) == 1, "Expected exactly 1 DeprecationWarning"
            assert issubclass(w[0].category, DeprecationWarning)
            assert "AuditEngine" in str(w[0].message)

    def test_engine_created_without_forced_jsonl_prefix(self, mock_engine, trail):
        """The internal AuditEngine is created with the path as-is (no forced jsonl:// prefix)."""
        mock_engine.assert_called_once_with("/tmp/test-logs")


# ═══════════════════════════ Delegation — log ═══════════════════════════


class TestLog:
    """AuditTrail.log delegates to AuditEngine.log and returns AuditEvent."""

    def test_log_delegates_to_engine(self, trail, mock_engine):
        event = trail.log(
            session_id="sess-1",
            event_type="decision",
            agent_id="bot-1",
            prompt_version="v1",
            input_snapshot="in",
            output_snapshot="out",
            metadata={"foo": "bar"},
        )
        mock_engine.return_value.log.assert_called_once_with(
            session_id="sess-1",
            event_type="decision",
            agent_id="bot-1",
            prompt_version="v1",
            input_text="in",
            output_text="out",
            metadata={"foo": "bar"},
        )
        assert isinstance(event, AuditEvent)
        assert event.event_id == "evt-001"

    def test_log_returns_audit_event_with_all_fields(self, trail, mock_engine):
        event = trail.log("sess-1", "tool_call", "agent-x", "v3", "i", "o")
        assert event.event_id == "evt-001"
        assert event.session_id == "sess-1"
        assert event.event_type == "decision"
        assert event.agent_id == "bot-1"
        assert event.prompt_version == "v1"
        assert event.input_snapshot == "input text"
        assert event.output_snapshot == "output text"
        assert event.metadata == {"key": "val"}
        assert event.prev_hash == ""
        assert event.hash == "abc123"


# ═══════════════════════════ Delegation — verify ═══════════════════════════


class TestVerify:
    """AuditTrail.verify delegates to AuditEngine.verify."""

    def test_verify_delegates_to_engine(self, trail, mock_engine):
        result = trail.verify()
        mock_engine.return_value.verify.assert_called_once_with(session_id=None)
        assert result is True

    def test_verify_wraps_value_error_as_integrity_error(self, trail, mock_engine):
        mock_engine.return_value.verify.side_effect = ValueError("chain broken")
        with pytest.raises(AuditIntegrityError, match="chain broken"):
            trail.verify()


# ═══════════════════════════ Delegation — search ═══════════════════════════


class TestSearch:
    """AuditTrail.search delegates and filters correctly."""

    def test_search_without_filters_returns_all(self, trail, mock_engine):
        results = trail.search()
        mock_engine.return_value.sessions.assert_called_once()
        assert len(results) == 4  # 2 sessions x 2 events each

    def test_search_with_session_id(self, trail, mock_engine):
        results = trail.search(session_id="sess-1")
        # Only reads sess-1 (2 events)
        assert len(results) == 2

    def test_search_with_event_type_filter(self, trail, mock_engine):
        # Engine returns events with event_type "decision"
        results = trail.search(event_type="decision")
        assert len(results) == 4

    def test_search_with_agent_id_filter(self, trail, mock_engine):
        # Engine events don't have "agent_id" key, so filter excludes all
        results = trail.search(agent_id="other-agent")
        assert len(results) == 0

    def test_search_respects_limit(self, trail, mock_engine):
        results = trail.search(limit=2)
        assert len(results) == 2

    def test_search_outer_break_when_limit_reached(self, mock_engine):
        """Outer loop break at line 174/175 when limit hit before next session."""
        mock_engine.return_value.sessions.return_value = ["s1", "s2", "s3"]
        mock_engine.return_value.read.side_effect = lambda sid: [
            {"event_id": f"e-{sid}", "event_type": "decision"} for _ in range(2)
        ]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            t = AuditTrail("/tmp/x")
        results = t.search(limit=1)  # First event appended, then outer break
        assert len(results) == 1

    def test_search_both_filters_match_some(self, mock_engine):
        """Both event_type and agent_id filters applied."""
        mock_engine.return_value.sessions.return_value = ["s1"]
        mock_engine.return_value.read.side_effect = lambda sid: [
            {"event_id": "e1", "session_id": sid, "event_type": "decision", "agent_id": "bot-1"},
            {"event_id": "e2", "session_id": sid, "event_type": "tool_call", "agent_id": "bot-2"},
        ]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            t = AuditTrail("/tmp/x")
        results = t.search(event_type="decision", agent_id="bot-1")
        assert len(results) == 1
        assert results[0]["event_id"] == "e1"

    def test_search_with_session_and_filters_all_pass(self, mock_engine):
        """Session_id + event_type + agent_id filter with all passing."""
        mock_engine.return_value.read.side_effect = lambda sid: [
            {"event_id": "e1", "session_id": sid, "event_type": "decision", "agent_id": "a1"},
            {"event_id": "e2", "session_id": sid, "event_type": "decision", "agent_id": "a1"},
        ]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            t = AuditTrail("/tmp/x")
        results = t.search(session_id="sess-1", event_type="decision", agent_id="a1")
        assert len(results) == 2


# ═══════════════════════════ Delegation — sessions / stats ═══════════════════


class TestSessionsAndStats:
    """sessions() and stats() delegate directly."""

    def test_sessions_delegates(self, trail, mock_engine):
        sids = trail.sessions()
        mock_engine.return_value.sessions.assert_called_once()
        assert sids == ["sess-1", "sess-2"]

    def test_stats_delegates(self, trail, mock_engine):
        s = trail.stats()
        mock_engine.return_value.stats.assert_called_once()
        assert s["total_events"] == 3


# ═══════════════════════════ AuditEvent type conversion ═══════════════════════


class TestAuditEvent:
    """AuditEvent.from_chain_event and from_dict."""

    def test_from_chain_event_converts_all_fields(self):
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
            metadata={"key": "val"},
            prev_hash="",
            hash="sha256hash",
        )
        ae = AuditEvent.from_chain_event(ce)
        assert ae.event_id == "evt-001"
        assert ae.session_id == "sess-1"
        assert ae.timestamp == 1719000000.0
        assert ae.event_type == "decision"
        assert ae.agent_id == "bot-1"
        assert ae.prompt_version == "v1"
        assert ae.input_snapshot == "input"
        assert ae.output_snapshot == "output"
        assert ae.metadata == {"key": "val"}
        assert ae.prev_hash == ""
        assert ae.hash == "sha256hash"
        # AuditEvent (trail.py) does NOT have a sequence/sequence field
        assert not hasattr(ae, "sequence")
        assert not hasattr(ae, "id")

    def test_from_dict_converts_all_fields(self):
        d = {
            "event_id": "evt-002",
            "session_id": "sess-2",
            "timestamp": 1719100000.0,
            "event_type": "tool_call",
            "agent_id": "agent-x",
            "prompt_version": "v2",
            "input_snapshot": "in",
            "output_snapshot": "out",
            "metadata": {"role": "admin"},
            "prev_hash": "prevhash",
            "hash": "curhash",
        }
        ae = AuditEvent.from_dict(d)
        assert ae.event_id == "evt-002"
        assert ae.session_id == "sess-2"
        assert ae.timestamp == 1719100000.0
        assert ae.event_type == "tool_call"
        assert ae.agent_id == "agent-x"
        assert ae.prompt_version == "v2"
        assert ae.input_snapshot == "in"
        assert ae.output_snapshot == "out"
        assert ae.metadata == {"role": "admin"}
        assert ae.prev_hash == "prevhash"
        assert ae.hash == "curhash"

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

    def test_from_dict_preserves_metadata_when_present(self):
        d = {"event_id": "x", "metadata": {"nested": {"a": 1}}}
        ae = AuditEvent.from_dict(d)
        assert ae.metadata == {"nested": {"a": 1}}
