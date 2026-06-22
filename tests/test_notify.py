"""Tests for notify.py — Slack + Console notifications (0% baseline)."""

import json
from unittest.mock import patch, MagicMock
import pytest
from agent_audit.notify import Alert, SlackNotifier, ConsoleNotifier


class TestAlert:
    def test_basic_alert(self):
        alert = Alert(level="info", title="Test Alert", body="This is a test")
        assert alert.level == "info"
        assert alert.title == "Test Alert"
        assert alert.body == "This is a test"
        assert alert.agent_id == ""
        assert alert.session_id == ""

    def test_alert_with_all_fields(self):
        alert = Alert(
            level="critical",
            title="CRITICAL",
            body="System failure",
            agent_id="agent-1",
            session_id="session-42",
        )
        assert alert.level == "critical"
        assert alert.agent_id == "agent-1"
        assert alert.session_id == "session-42"

    def test_alert_levels_valid(self):
        for level in ("info", "warn", "critical"):
            alert = Alert(level=level, title="x", body="y")
            assert alert.level == level

    def test_default_string_fields(self):
        alert = Alert(level="info", title="", body="")
        assert isinstance(alert.agent_id, str)
        assert isinstance(alert.session_id, str)


class TestSlackNotifier:
    def test_send_info_alert(self):
        notifier = SlackNotifier("https://hooks.slack.com/test")
        alert = Alert(level="info", title="Info", body="Details", agent_id="ag", session_id="s1")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_urlopen.return_value = mock_response
            result = notifier.send(alert)

        assert result is True
        mock_urlopen.assert_called_once()
        args = mock_urlopen.call_args
        request = args[0][0]
        payload = json.loads(request.data)
        assert payload["attachments"][0]["color"] == "#39d2c0"
        assert "[INFO]" in payload["attachments"][0]["title"]

    def test_send_warn_alert(self):
        notifier = SlackNotifier("https://hooks.slack.com/test")
        alert = Alert(level="warn", title="Warning", body="Watch out")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock()
            notifier.send(alert)

        payload = json.loads(mock_urlopen.call_args[0][0].data)
        assert payload["attachments"][0]["color"] == "#d29922"

    def test_send_critical_alert(self):
        notifier = SlackNotifier("https://hooks.slack.com/test")
        alert = Alert(level="critical", title="Critical", body="Down!")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock()
            notifier.send(alert)

        payload = json.loads(mock_urlopen.call_args[0][0].data)
        assert payload["attachments"][0]["color"] == "#da3633"

    def test_send_unknown_level_uses_default_color(self):
        notifier = SlackNotifier("https://hooks.slack.com/test")
        alert = Alert(level="unknown", title="Test", body="test")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock()
            notifier.send(alert)

        payload = json.loads(mock_urlopen.call_args[0][0].data)
        assert payload["attachments"][0]["color"] == "#6b7280"

    def test_send_network_error_returns_false(self):
        notifier = SlackNotifier("https://hooks.slack.com/test")
        alert = Alert(level="info", title="Test", body="body")

        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            result = notifier.send(alert)

        assert result is False

    def test_send_urlerror_returns_false(self):
        import urllib.error

        notifier = SlackNotifier("https://hooks.slack.com/test")
        alert = Alert(level="info", title="Test", body="body")

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            result = notifier.send(alert)

        assert result is False

    def test_payload_fields(self):
        notifier = SlackNotifier("https://hooks.slack.com/test")
        alert = Alert(
            level="info",
            title="Test Title",
            body="Test body",
            agent_id="agent-x",
            session_id="session-y",
        )

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock()
            notifier.send(alert)

        payload = json.loads(mock_urlopen.call_args[0][0].data)
        attachment = payload["attachments"][0]
        assert attachment["footer"] == "agent-audit"
        fields = {f["title"]: f["value"] for f in attachment["fields"]}
        assert fields["Agent"] == "agent-x"
        assert fields["Session"] == "session-y"

    def test_send_with_timeout(self):
        notifier = SlackNotifier("https://hooks.slack.com/test")
        alert = Alert(level="info", title="Test", body="body")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = MagicMock()
            notifier.send(alert)

        # Verify timeout=5 is passed
        kwargs = mock_urlopen.call_args[1]
        assert kwargs.get("timeout") == 5 or kwargs.get("timeout") == 5.0


class TestConsoleNotifier:
    def test_send_info(self, capsys):
        notifier = ConsoleNotifier()
        alert = Alert(level="info", title="Info Alert", body="Info body", agent_id="a1", session_id="s1")
        result = notifier.send(alert)

        assert result is True
        captured = capsys.readouterr()
        assert "INFO" in captured.out
        assert "Info Alert" in captured.out
        assert "Info body" in captured.out
        assert "a1" in captured.out
        assert "s1" in captured.out

    def test_send_warn(self, capsys):
        notifier = ConsoleNotifier()
        alert = Alert(level="warn", title="Warning", body="Careful")
        notifier.send(alert)
        captured = capsys.readouterr()
        assert "WARN" in captured.out

    def test_send_critical(self, capsys):
        notifier = ConsoleNotifier()
        alert = Alert(level="critical", title="CRIT", body="Boom")
        notifier.send(alert)
        captured = capsys.readouterr()
        assert "CRIT" in captured.out

    def test_unknown_level(self, capsys):
        notifier = ConsoleNotifier()
        alert = Alert(level="debug", title="Debug", body="x")
        notifier.send(alert)
        captured = capsys.readouterr()
        # unknown level uses "?" prefix
        assert "?" in captured.out

    def test_always_returns_true(self):
        notifier = ConsoleNotifier()
        alert = Alert(level="info", title="x", body="y")
        assert notifier.send(alert) is True
