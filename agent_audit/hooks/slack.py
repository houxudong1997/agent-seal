"""Slack notification hook."""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SlackConfig:
    webhook_url: str
    channel: str = ""
    username: str = "agent-audit"


class SlackHook:
    def __init__(self, config: SlackConfig):
        self.config = config

    def send(
        self, title: str, body: str, level: str = "info", agent_id: str = "", session_id: str = ""
    ) -> bool:
        color = {"info": "#39d2c0", "warn": "#d29922", "critical": "#da3633"}.get(level, "#6b7280")
        payload = {
            "channel": self.config.channel,
            "username": self.config.username,
            "attachments": [
                {
                    "color": color,
                    "title": f"[{level.upper()}] {title}",
                    "text": body,
                    "fields": [
                        {"title": "Agent", "value": agent_id or "-", "short": True},
                        {"title": "Session", "value": session_id or "-", "short": True},
                    ],
                    "footer": "agent-audit",
                }
            ],
        }
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.config.webhook_url, data=data, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=5)
            return True
        except (OSError, urllib.error.URLError) as exc:
            logger.warning(
                "Slack hook notification failed (level=%s, title=%r): %s",
                level,
                title,
                exc,
            )
            return False
