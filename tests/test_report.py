"""Tests for report.py — EU AI Act compliance report generation.

Coverage targets:
  - generate_eu_ai_report() — with data, empty data, with output_path
  - _ts_to_date() — with timestamp, with None
  - _event_table() — with types, empty dict
  - _prompt_table() — with versions, empty list
  - _sample_events() — with events, empty list
  - _try_verify() — succeeds, raises exception
  - _integrity_status() — succeeds, raises exception
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_seal.report import (
    _event_table,
    _integrity_status,
    _prompt_table,
    _sample_events,
    _try_verify,
    _ts_to_date,
    generate_eu_ai_report,
)


# ═══════════════════════════ FIXTURES ═══════════════════════════


@pytest.fixture
def mock_engine():
    """Create a mock AuditEngine with realistic return data."""
    engine = MagicMock()
    engine.store_uri = "sqlite:///tmp/test.db"

    engine.stats.return_value = {
        "total_events": 100,
        "sessions": 4,
        "event_types": {"decision": 60, "tool_call": 30, "observation": 10},
        "first_event": 1717000000.0,
        "last_event": 1719000000.0,
    }

    engine.sessions.return_value = ["sess-1", "sess-2", "sess-3"]

    engine.read.side_effect = lambda sid: [
        {
            "event_id": f"evt-{i}",
            "session_id": sid,
            "timestamp": 1718000000.0 + i,
            "event_type": "decision" if i % 2 == 0 else "tool_call",
            "agent_id": "bot-1",
            "prompt_version": "v2" if i > 1 else "v1",
            "input_snapshot": "classify customer email",
            "output_snapshot": "approve refund request",
        }
        for i in range(4)
    ]

    engine.verify.return_value = True
    return engine


@pytest.fixture
def mock_registry():
    """Create a mock PromptRegistry with prompt version history."""
    registry = MagicMock()
    registry.audit_report.return_value = {
        "agent_id": "refund-agent",
        "total_versions": 2,
        "versions": [
            {
                "version_id": "v1",
                "changed_by": "alice",
                "change_reason": "Initial prompt",
                "timestamp": 1717000000.0,
                "hash": "aaa",
                "prev_version": "",
            },
            {
                "version_id": "v2",
                "changed_by": "bob",
                "change_reason": "Add $500 limit rule",
                "timestamp": 1718000000.0,
                "hash": "bbb",
                "prev_version": "v1",
            },
        ],
    }
    return registry


@pytest.fixture
def empty_engine():
    """Mock AuditEngine with zero data."""
    engine = MagicMock()
    engine.store_uri = "sqlite:///tmp/empty.db"
    engine.stats.return_value = {
        "total_events": 0,
        "sessions": 0,
        "event_types": {},
    }
    engine.sessions.return_value = []
    engine.read.return_value = []
    engine.verify.return_value = True
    return engine


@pytest.fixture
def empty_registry():
    """Mock PromptRegistry with no versions."""
    registry = MagicMock()
    registry.audit_report.return_value = {
        "agent_id": "empty-agent",
        "total_versions": 0,
        "versions": [],
    }
    return registry


# ═══════════════════════════ generate_eu_ai_report ═══════════════════════════


class TestGenerateEUAIReport:
    """generate_eu_ai_report() — full report generation."""

    def test_report_contains_all_sections(self, mock_engine, mock_registry):
        """Normal path: report includes all required sections."""
        report = generate_eu_ai_report("refund-agent", mock_engine, mock_registry)
        assert "EU AI Act Compliance Report" in report
        assert "Article 12" in report
        assert "System Overview" in report
        assert "Event Type Distribution" in report
        assert "Prompt Change History" in report
        assert "Decision Traceability" in report
        assert "Sample Events" in report
        assert "Integrity Verification" in report
        assert "Data Retention" in report
        assert "refund-agent" in report

    def test_report_includes_stats(self, mock_engine, mock_registry):
        """Report includes correct stats from engine."""
        report = generate_eu_ai_report("refund-agent", mock_engine, mock_registry)
        assert "100" in report  # total_events
        assert "decision" in report  # event type
        assert "tool_call" in report
        assert "v1" in report  # prompt version
        assert "v2" in report

    def test_report_empty_data(self, empty_engine, empty_registry):
        """Edge: empty engine/registry produces valid report."""
        report = generate_eu_ai_report("empty-agent", empty_engine, empty_registry)
        assert "EU AI Act Compliance Report" in report
        assert "0" in report  # zero events
        assert "No events recorded" in report
        assert "No prompt versions tracked" in report
        assert "No sample events available" in report

    def test_report_writes_to_file(self, mock_engine, mock_registry, tmp_path):
        """When output_path is provided, report is written to disk."""
        output_path = tmp_path / "eu-report.md"
        report = generate_eu_ai_report("refund-agent", mock_engine, mock_registry, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert content == report
        assert "EU AI Act Compliance Report" in content

    def test_report_calls_engine_stats(self, mock_engine, mock_registry):
        """Verifies engine.stats() is called."""
        generate_eu_ai_report("agent-x", mock_engine, mock_registry)
        mock_engine.stats.assert_called_once()

    def test_report_calls_engine_sessions(self, mock_engine, mock_registry):
        """Verifies engine.sessions() is called."""
        generate_eu_ai_report("agent-x", mock_engine, mock_registry)
        mock_engine.sessions.assert_called_once()

    def test_report_calls_registry_audit(self, mock_engine, mock_registry):
        """Verifies registry.audit_report() is called with correct agent_id."""
        generate_eu_ai_report("my-agent-42", mock_engine, mock_registry)
        mock_registry.audit_report.assert_called_once_with("my-agent-42")

    def test_report_calls_engine_read(self, mock_engine, mock_registry):
        """Verifies engine.read() is called for last 3 sessions."""
        generate_eu_ai_report("agent-x", mock_engine, mock_registry)
        assert mock_engine.read.call_count == 3  # 3 sessions


# ═══════════════════════════ _ts_to_date ═══════════════════════════


class TestTsToDate:
    """_ts_to_date() — timestamp formatting."""

    def test_with_timestamp(self):
        """Normal: returns formatted UTC datetime string."""
        result = _ts_to_date(1717000000.0)
        assert "2024-05-29" in result
        assert "UTC" in result

    def test_with_none(self):
        """Edge: None returns 'N/A'."""
        result = _ts_to_date(None)
        assert result == "N/A"

    def test_with_zero(self):
        """Edge: epoch timestamp."""
        result = _ts_to_date(0)
        assert "1970-01-01" in result
        assert "UTC" in result


# ═══════════════════════════ _event_table ═══════════════════════════


class TestEventTable:
    """_event_table() — event type distribution table."""

    def test_with_types(self):
        """Normal dict returns sorted markdown table."""
        types = {"decision": 60, "tool_call": 30, "observation": 10}
        result = _event_table(types)
        assert "| Event Type | Count |" in result
        assert "| `decision` | 60 |" in result
        assert "| `tool_call` | 30 |" in result
        assert "| `observation` | 10 |" in result
        # Sorted by count descending: decision (60) first
        assert result.index("decision") < result.index("tool_call") < result.index("observation")

    def test_empty_dict(self):
        """Empty dict returns 'No events recorded'."""
        result = _event_table({})
        assert result == "No events recorded."

    def test_single_type(self):
        """Single type still produces table."""
        result = _event_table({"decision": 5})
        assert "| `decision` | 5 |" in result
        assert "|------------|-------|" in result


# ═══════════════════════════ _prompt_table ═══════════════════════════


class TestPromptTable:
    """_prompt_table() — prompt version change history table."""

    def test_with_versions(self):
        """Versions list returns markdown table."""
        audit = {
            "versions": [
                {"version_id": "v1", "changed_by": "alice", "change_reason": "Initial", "timestamp": 1717000000.0},
                {"version_id": "v2", "changed_by": "bob", "change_reason": "Update", "timestamp": 1718000000.0},
            ]
        }
        result = _prompt_table(audit)
        assert "| Version | Changed By | Reason | Timestamp |" in result
        assert "v1" in result
        assert "alice" in result
        assert "Initial" in result

    def test_empty_versions(self):
        """Empty versions list returns 'No prompt versions tracked'."""
        result = _prompt_table({"versions": []})
        assert result == "No prompt versions tracked."


# ═══════════════════════════ _sample_events ═══════════════════════════


class TestSampleEvents:
    """_sample_events() — sample events table."""

    def test_with_events(self):
        """Events list returns markdown table with previews."""
        events = [
            {
                "event_id": "evt-001",
                "event_type": "decision",
                "input_snapshot": "classify customer email message",
                "output_snapshot": "approve refund of $200",
                "prompt_version": "v2",
            },
            {
                "event_id": "evt-002",
                "event_type": "tool_call",
                "input_snapshot": "search database for order",
                "output_snapshot": "found order #12345",
                "prompt_version": "v1",
            },
        ]
        result = _sample_events(events)
        assert "| Event ID | Type | Input | Output | Prompt Ver |" in result
        assert "evt-001" in result
        assert "decision" in result
        assert "evt-002" in result
        assert "tool_call" in result
        assert "classify" in result

    def test_empty_events(self):
        """Empty events list returns 'No sample events available'."""
        result = _sample_events([])
        assert result == "No sample events available."

    def test_truncated_previews(self):
        """Input/output previews are truncated to 60 chars."""
        long_input = "x" * 100
        long_output = "y" * 100
        events = [
            {
                "event_id": "evt-001",
                "event_type": "decision",
                "input_snapshot": long_input,
                "output_snapshot": long_output,
                "prompt_version": "v1",
            }
        ]
        result = _sample_events(events)
        assert "x" * 60 in result
        assert "x" * 61 not in result  # truncated
        assert "y" * 60 in result

    def test_missing_fields(self):
        """Events with missing optional fields use empty defaults."""
        events = [
            {
                "event_id": "evt-001",
                "event_type": "decision",
                # input_snapshot, output_snapshot, prompt_version missing
            }
        ]
        result = _sample_events(events)
        assert "evt-001" in result
        assert "decision" in result

    def test_at_most_10_events(self):
        """Only first 10 events are included in the table."""
        events = [
            {
                "event_id": f"evt-{i:03d}",
                "event_type": "decision",
                "input_snapshot": "",
                "output_snapshot": "",
                "prompt_version": "v1",
            }
            for i in range(15)
        ]
        result = _sample_events(events)
        # Last event included: evt-009 (index 9, 10th event)
        assert "evt-009" in result
        # evt-010 should not be in the table (index 10, 11th event)
        assert "evt-010" not in result


# ═══════════════════════════ _try_verify ═══════════════════════════


class TestTryVerify:
    """_try_verify() — safe chain integrity check."""

    def test_verify_success(self, mock_engine):
        """When engine.verify() returns True, returns True."""
        mock_engine.verify.return_value = True
        assert _try_verify(mock_engine) is True

    def test_verify_false(self, mock_engine):
        """When engine.verify() returns False, returns False."""
        mock_engine.verify.return_value = False
        assert _try_verify(mock_engine) is False

    def test_verify_exception(self, mock_engine):
        """When engine.verify() raises, returns False (no crash)."""
        mock_engine.verify.side_effect = ValueError("chain broken")
        assert _try_verify(mock_engine) is False


# ═══════════════════════════ _integrity_status ═══════════════════════════


class TestIntegrityStatus:
    """_integrity_status() — human-readable integrity string."""

    def test_verify_passes(self, mock_engine):
        """Intact chain returns checkmark."""
        mock_engine.verify.return_value = True
        result = _integrity_status(mock_engine)
        assert "VERIFIED" in result
        assert "intact" in result

    def test_verify_raises(self, mock_engine):
        """Broken chain returns BROKEN with error message."""
        mock_engine.verify.side_effect = ValueError("Hash mismatch at event 5")
        result = _integrity_status(mock_engine)
        assert "BROKEN" in result
        assert "Hash mismatch" in result
