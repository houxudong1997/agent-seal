"""
agent-seal configuration system (python-dotenv + 12-Factor App).

All configuration is sourced from environment variables with a .env file
fallback.  Sensible defaults are provided for local development (JSONL +
SQLite); production deployments MUST set the relevant production variables.

Usage::

    from agent_seal.config import config

    trail = AuditTrail(config.audit_dir)
    server_port = config.api_port
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Discover and load .env
_config_file_dir = Path(__file__).resolve().parent.parent
_dotenv_path = _config_file_dir / ".env"
if _dotenv_path.exists():
    load_dotenv(_dotenv_path, override=False)
else:
    load_dotenv(override=False)


# Helpers


def _bool_env(key: str, default: bool = False) -> bool:
    val = os.getenv(key, str(default)).strip().lower()
    return val in ("1", "true", "yes", "on")


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _path_env(key: str, default: str | Path) -> Path:
    val = os.getenv(key, str(default))
    return Path(os.path.expandvars(os.path.expanduser(val))).resolve()


class Config:
    """Application-wide configuration singleton.

    All attributes are read from AGENT_SEAL_* environment variables
    (loaded from .env with os.environ override).
    """

    # Core

    @property
    def db_url(self) -> str:
        return os.getenv(
            "AGENT_SEAL_DB_URL",
            os.getenv("DB_URL", os.getenv("DATABASE_URL", "")),
        )

    @property
    def secret_key(self) -> str:
        return os.getenv("AGENT_SEAL_SECRET_KEY", os.getenv("SECRET_KEY", ""))

    # Storage

    @property
    def audit_dir(self) -> Path:
        val = os.getenv(
            "AGENT_SEAL_AUDIT_DIR",
            os.getenv("AUDIT_DIR", os.getenv("AGENT_SEAL_URI", "./audit_logs")),
        )
        return Path(val).resolve()

    @property
    def store_uri(self) -> str:
        db = self.db_url
        if db:
            logger.info("store_uri using database: %s", db)
            return db
        audit = str(self.audit_dir)
        logger.info("store_uri using file backend (audit_dir): %s", audit)
        return audit

    @property
    def storage_backend(self) -> str:
        """Explicit backend override: 'jsonl' | 'sqlite' | 'postgresql'.

        Default 'auto' lets create_store() detect from the URI scheme.
        Set explicitly to force a specific backend regardless of URI.
        """
        return os.getenv("AGENT_SEAL_STORAGE_BACKEND", "auto")

    # API

    @property
    def api_host(self) -> str:
        return os.getenv("AGENT_SEAL_API_HOST", "0.0.0.0")

    @property
    def api_port(self) -> int:
        return _int_env("AGENT_SEAL_API_PORT", 8081)

    @property
    def api_keys(self) -> list[str]:
        raw = os.getenv("AGENT_SEAL_API_KEYS", os.getenv("API_KEYS", ""))
        return [k.strip() for k in raw.split(",") if k.strip()]

    # CORS

    @property
    def cors_origins(self) -> list[str]:
        raw = os.getenv("AGENT_SEAL_CORS_ORIGINS", "")
        return [o.strip() for o in raw.split(",") if o.strip()]

    # Signing and Encryption

    @property
    def signing_key(self) -> str:
        return os.getenv("AGENT_SEAL_SIGNING_KEY", os.getenv("SIGNING_KEY", ""))

    @property
    def signing_key_password(self) -> str:
        """Password for the Ed25519 private key (AGENT_SEAL_SIGNING_KEY_PASSWORD)."""
        return os.getenv("AGENT_SEAL_SIGNING_KEY_PASSWORD", "")

    @property
    def encryption_key(self) -> str:
        return os.getenv("AGENT_SEAL_ENCRYPTION_KEY", "")

    # Logging

    @property
    def log_level(self) -> str:
        return os.getenv("AGENT_SEAL_LOG_LEVEL", os.getenv("LOG_LEVEL", "info")).upper()

    @property
    def log_format(self) -> str:
        return os.getenv("AGENT_SEAL_LOG_FORMAT", "text").lower()

    # LLM Tracing

    @property
    def auto_trace(self) -> bool:
        return _bool_env("AGENT_SEAL_AUTO_TRACE", False)

    @property
    def trace_pii_redact(self) -> bool:
        return _bool_env("AGENT_SEAL_TRACE_PII_REDACT", False)

    @property
    def trace_max_len(self) -> int:
        return _int_env("AGENT_SEAL_TRACE_MAX_LEN", 4000)

    @property
    def trace_cost_model(self) -> str:
        return os.getenv("AGENT_SEAL_TRACE_COST_MODEL", "openai")

    # Notification

    @property
    def slack_webhook(self) -> str:
        return os.getenv("AGENT_SEAL_SLACK_WEBHOOK", "")

    @property
    def smtp_host(self) -> str:
        return os.getenv("AGENT_SEAL_SMTP_HOST", "")

    @property
    def notify_on_failure(self) -> bool:
        return _bool_env("AGENT_SEAL_NOTIFY_ON_FAILURE", False)

    # Evidence

    @property
    def evidence_store(self) -> str:
        return os.getenv("AGENT_SEAL_EVIDENCE_STORE", "")

    # Redis (optional)

    @property
    def redis_uri(self) -> str:
        return os.getenv("AGENT_SEAL_REDIS_URI", "")


config = Config()
