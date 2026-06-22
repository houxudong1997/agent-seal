"""
Notification modules for agent-audit events.

Currently supported: Slack webhook, stdout.
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """One alert to be sent."""

    level: str  # "info" | "warn" | "critical"
    title: str
    body: str
    agent_id: str = ""
    session_id: str = ""


class SlackNotifier:
    """Send audit alerts to Slack via webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, alert: Alert) -> bool:
        color = {"info": "#39d2c0", "warn": "#d29922", "critical": "#da3633"}.get(
            alert.level, "#6b7280"
        )
        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": f"[{alert.level.upper()}] {alert.title}",
                    "text": alert.body,
                    "fields": [
                        {"title": "Agent", "value": alert.agent_id, "short": True},
                        {"title": "Session", "value": alert.session_id, "short": True},
                    ],
                    "footer": "agent-audit",
                }
            ]
        }
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
            return True
        except (OSError, urllib.error.URLError) as exc:
            logger.warning(
                "Slack notification failed (level=%s, title=%r): %s",
                alert.level,
                alert.title,
                exc,
            )
            return False


class ConsoleNotifier:
    """Print alerts to stdout (for testing/development)."""

    def send(self, alert: Alert) -> bool:
        prefix = {"info": "INFO", "warn": "WARN", "critical": "CRIT"}.get(alert.level, "?")
        print(f"{prefix} [{alert.level.upper()}] {alert.title}")
        print(f"   {alert.body}")
        print(f"   Agent: {alert.agent_id} | Session: {alert.session_id}")
        return True
