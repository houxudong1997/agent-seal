"""Tests for cli.py — AuditEngine migration CLI commands.

Coverage targets:
  - cmd_verify — normal pass, ValueError failure, sys.exit on failure
  - cmd_trail — sessions present, no sessions
  - cmd_report — with/without output path
  - cmd_log — normal, missing args (sys.exit)
  - main() — dispatch, unknown command, missing command
"""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

import pytest

from agent_audit.core.chain import ChainEvent


# ═══════════════════════════ FIXTURES ═══════════════════════════


@pytest.fixture
def mock_engine():
    """Mock AuditEngine so no real store backend is created."""
    with patch("agent_audit.cli.AuditEngine") as m:
        instance = m.return_value
        instance.store_uri = "jsonl:///tmp/test-logs"

        # log() returns a ChainEvent
        instance.log.return_value = ChainEvent(
            event_id="evt-001",
            session_id="test-session",
            sequence=0,
            timestamp=1719000000.0,
            event_type="test_type",
            agent_id="test-agent",
            prompt_version="v1",
            input_snapshot="CLI manual entry",
            output_snapshot="test output",
            metadata={},
            prev_hash="",
            hash="abc123def4567890abcdef1234567890",
        )

        # stats()
        instance.stats.return_value = {
            "total_events": 42,
            "sessions": 3,
            "event_types": {"decision": 30, "tool_call": 12},
            "first_event": 1718000000.0,
            "last_event": 1719000000.0,
        }

        # sessions()
        instance.sessions.return_value = ["sess-1", "sess-2", "sess-3"]

        # read()
        instance.read.side_effect = lambda sid: [
            {
                "event_id": f"evt-{i}",
                "session_id": sid,
                "timestamp": 1719000000.0 + i,
                "event_type": "decision" if i % 2 == 0 else "tool_call",
                "agent_id": "bot-1",
                "output_snapshot": f"output-{i}",
            }
            for i in range(3)
        ]

        yield m


@pytest.fixture
def mock_registry():
    """Mock PromptRegistry so no real disk I/O happens."""
    with patch("agent_audit.cli.PromptRegistry") as m:
        instance = m.return_value
        instance.audit_report.return_value = {
            "agent_id": "default-agent",
            "total_versions": 2,
            "versions": [
                {
                    "version_id": "v1",
                    "changed_by": "alice",
                    "change_reason": "initial",
                    "timestamp": 1718000000.0,
                    "hash": "aaa",
                    "prev_version": "",
                },
                {
                    "version_id": "v2",
                    "changed_by": "bob",
                    "change_reason": "update rules",
                    "timestamp": 1718500000.0,
                    "hash": "bbb",
                    "prev_version": "v1",
                },
            ],
        }
        yield m


# ═══════════════════════════ cmd_verify ═══════════════════════════


class TestCmdVerify:
    """cmd_verify — check audit trail integrity."""

    def test_verify_passes(self, mock_engine, capsys):
        """Normal path: engine.verify() succeeds, prints success."""
        from agent_audit.cli import cmd_verify

        cmd_verify()
        out, err = capsys.readouterr()
        assert "intact" in out or "No tampering" in out
        assert "✅" in out
        assert err == ""

    def test_verify_fails_value_error(self, mock_engine, capsys):
        """Error path: engine.verify() raises ValueError, exits with code 1."""
        mock_engine.return_value.verify.side_effect = ValueError("Chain broken at event 5")

        from agent_audit.cli import cmd_verify

        with pytest.raises(SystemExit) as exc_info:
            cmd_verify()
        assert exc_info.value.code == 1

        out, err = capsys.readouterr()
        assert "INTEGRITY FAILURE" in out
        assert "Chain broken" in out

    def test_verify_calls_engine(self, mock_engine, capsys):
        """verify() calls engine.verify() once."""
        from agent_audit.cli import cmd_verify

        cmd_verify()
        mock_engine.return_value.verify.assert_called_once()


# ═══════════════════════════ cmd_trail ═══════════════════════════


class TestCmdTrail:
    """cmd_trail — show recent events."""

    def test_trail_with_sessions(self, mock_engine, capsys):
        """Normal path: prints stats and last 3 sessions with events."""
        from agent_audit.cli import cmd_trail

        cmd_trail()
        out, err = capsys.readouterr()
        assert "Audit Trail:" in out
        assert "Total events: 42" in out
        assert "Sessions:     3" in out
        assert "Event types:  " in out
        assert "sess-1" in out
        assert "sess-2" in out
        assert "sess-3" in out
        assert err == ""

    def test_trail_no_sessions(self, mock_engine, capsys):
        """Edge: no sessions, should still print stats."""
        mock_engine.return_value.sessions.return_value = []
        mock_engine.return_value.stats.return_value = {
            "total_events": 0,
            "sessions": 0,
            "event_types": {},
        }

        from agent_audit.cli import cmd_trail

        cmd_trail()
        out, err = capsys.readouterr()
        assert "Total events: 0" in out
        assert "Sessions:     0" in out
        # No "Last 3 sessions" since there are none
        assert err == ""

    def test_trail_calls_engine_methods(self, mock_engine, capsys):
        """Verifies the right engine methods are called."""
        from agent_audit.cli import cmd_trail

        cmd_trail()
        engine = mock_engine.return_value
        engine.stats.assert_called_once()
        engine.sessions.assert_called_once()


# ═══════════════════════════ cmd_report ═══════════════════════════


class TestCmdReport:
    """cmd_report — generate EU AI Act compliance report."""

    def test_report_default_agent(self, mock_engine, mock_registry, capsys):
        """Default agent with no output path."""
        test_argv = ["agent-audit", "report"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import cmd_report

            cmd_report()

        out, err = capsys.readouterr()
        assert "EU AI Act Compliance Report" in out
        assert "default-agent" in out
        assert err == ""

    def test_report_custom_agent_no_output(self, mock_engine, mock_registry, capsys):
        """Custom agent id, no output path.

        Note: cmd_report reads sys.argv[3] for agent_id (argv[2] is unused).
        """
        test_argv = ["agent-audit", "report", "skip", "my-agent"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import cmd_report

            cmd_report()

        out, err = capsys.readouterr()
        assert "my-agent" in out
        assert "my-agent" in mock_registry.return_value.audit_report.call_args[0][0]

    def test_report_with_output_path(self, mock_engine, mock_registry, capsys, tmp_path):
        """With output path, generates report to file and prints to stdout.

        Note: cmd_report reads sys.argv[3] for agent_id, sys.argv[4] for output_path.
        """
        report_file = tmp_path / "eu-report.md"
        test_argv = ["agent-audit", "report", "skip", "default-agent", str(report_file)]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import cmd_report

            cmd_report()

        out, err = capsys.readouterr()
        assert "EU AI Act Compliance Report" in out
        assert report_file.exists()
        content = report_file.read_text(encoding="utf-8")
        assert "EU AI Act Compliance Report" in content

    def test_report_calls_generate(self, mock_engine, mock_registry, capsys):
        """Verifies generate_eu_ai_report is called with correct args."""
        test_argv = ["agent-audit", "report"]
        with patch("agent_audit.cli.generate_eu_ai_report") as mock_generate:
            mock_generate.return_value = "mock report output"
            with patch.object(sys, "argv", test_argv):
                from agent_audit.cli import cmd_report

                cmd_report()

            mock_generate.assert_called_once()
            args, kwargs = mock_generate.call_args
            # positional: agent_id, engine, registry, output (None)
            assert args[0] == "default-agent"
            assert kwargs.get("output") is None or (len(args) > 3 and args[3] is None) or len(args) == 3


# ═══════════════════════════ cmd_log ═══════════════════════════


class TestCmdLog:
    """cmd_log — record a test event."""

    def test_log_normal(self, mock_engine, capsys):
        """Normal path: logs event and prints event_id + hash."""
        test_argv = ["agent-audit", "log", "test_type", "my output text"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import cmd_log

            cmd_log()

        out, err = capsys.readouterr()
        assert "Event recorded" in out
        assert "evt-001" in out
        assert "Hash:" in out
        assert err == ""

    def test_log_default_output(self, mock_engine, capsys):
        """When no output_text arg, defaults to 'test output'.

        Note: cmd_log reads sys.argv[3] for event_type, sys.argv[4] for output_text.
        """
        test_argv = ["agent-audit", "log", "skip", "my_type"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import cmd_log

            cmd_log()

        out, err = capsys.readouterr()
        assert "Event recorded" in out
        assert err == ""

    def test_log_missing_args(self, capsys):
        """Missing event_type: prints usage and exits with code 1."""
        test_argv = ["agent-audit", "log"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import cmd_log

            with pytest.raises(SystemExit) as exc_info:
                cmd_log()
            assert exc_info.value.code == 1

        out, err = capsys.readouterr()
        assert "Usage:" in out
        assert "event_type" in out

    def test_log_calls_engine_log(self, mock_engine, capsys):
        """Verifies engine.log() is called with correct parameters.

        Note: cmd_log reads sys.argv[3] for event_type, sys.argv[4] for output_text.
        """
        test_argv = ["agent-audit", "log", "skip", "decision", "approved"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import cmd_log

            cmd_log()

        mock_engine.return_value.log.assert_called_once_with(
            session_id="test-session",
            event_type="decision",
            agent_id="test-agent",
            prompt_version="v1",
            input_text="CLI manual entry",
            output_text="approved",
        )


# ═══════════════════════════ main() ═══════════════════════════


class TestMain:
    """main() — command dispatcher."""

    def test_main_verify_dispatch(self, mock_engine, capsys):
        """main() dispatches to cmd_verify when argv[1] == 'verify'."""
        test_argv = ["agent-audit", "verify"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import main

            main()
        out, err = capsys.readouterr()
        assert "intact" in out

    def test_main_unknown_command(self, capsys):
        """Unknown command exits with code 1 and prints help."""
        test_argv = ["agent-audit", "nonexistent"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        out, err = capsys.readouterr()
        assert "Commands:" in out
        assert "verify" in out

    def test_main_no_command(self, capsys):
        """No command exits with code 1 and prints help."""
        test_argv = ["agent-audit"]
        with patch.object(sys, "argv", test_argv):
            from agent_audit.cli import main

            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1
        out, err = capsys.readouterr()
        assert "Commands:" in out
        assert "verify" in out
