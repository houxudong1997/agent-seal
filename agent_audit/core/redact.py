"""
PII redaction for audit logs. Masks sensitive data before storage.

Handles: emails, phone numbers, credit cards, API keys, IPs, SSNs.
Configurable: choose what to redact, how to redact (hash/mask/remove).
"""

import hashlib
import re

REDACTORS = {
    "email": (re.compile(r"[\w\.-]+@[\w\.-]+\.\w+"), "<EMAIL>"),
    "phone": (re.compile(r"\b(\+\d{1,3}[\s-]?)?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{4}\b"), "<PHONE>"),
    "credit_card": (re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"), "<CARD>"),
    "ssn": (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<SSN>"),
    "api_key": (re.compile(r"(?:sk|api[_-]?key|token|secret)[=:]\s*[\w-]{10,}"), "<API_KEY>"),
    "ip": (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
}


class Redactor:
    """Sanitize text before logging."""

    def __init__(self, rules: list[str] | None = None):
        self.rules = rules or list(REDACTORS.keys())

    def sanitize(self, text: str) -> str:
        for name in self.rules:
            if name in REDACTORS:
                pattern, replacement = REDACTORS[name]
                text = pattern.sub(replacement, text)
        return text

    def hash_sensitive(self, text: str) -> str:
        """Replace sensitive values with their SHA-256 hashes (reversible identification)."""
        for name in self.rules:
            if name in REDACTORS:
                pattern, _ = REDACTORS[name]
                text = pattern.sub(
                    lambda m: hashlib.sha256(m.group(0).encode()).hexdigest()[:12], text
                )
        return text
