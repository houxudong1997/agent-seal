"""Email notification hook (SMTP)."""

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


@dataclass
class EmailConfig:
    smtp_host: str
    smtp_port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = "agent-seal@localhost"
    to_addrs: list[str] = field(default_factory=list)


class EmailHook:
    def __init__(self, config: EmailConfig):
        self.config = config

    def send(self, title: str, body: str, level: str = "info") -> bool:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[{level.upper()}] {title}"
        msg["From"] = self.config.from_addr
        msg["To"] = ", ".join(self.config.to_addrs)

        try:
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=10) as s:
                s.starttls()
                if self.config.username:
                    s.login(self.config.username, self.config.password)
                s.sendmail(self.config.from_addr, self.config.to_addrs, msg.as_string())
            return True
        except (OSError, smtplib.SMTPException, ssl.SSLError) as exc:
            logger.warning(
                "Email notification failed (host=%s:%s, subject=%r): %s",
                self.config.smtp_host,
                self.config.smtp_port,
                msg["Subject"],
                exc,
            )
            return False
