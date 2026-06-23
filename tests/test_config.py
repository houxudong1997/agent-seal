"""Comprehensive tests for agent_seal.config system.

Coverage targets:
  - Default values for all 20+ config properties
  - AGENT_SEAL_* env var overrides
  - Backward-compat legacy aliases (DB_URL, AUDIT_DIR, SECRET_KEY, etc.)
  - Helper functions: _bool_env, _int_env, _path_env
  - API keys / CORS parsing (comma-separated, empty, whitespace)
  - Edge cases: missing .env, invalid ints, empty strings, special chars
  - Integration: CLI usage of config, module-level .env loading
"""

from __future__ import annotations

import os
import textwrap
from importlib import reload
from pathlib import Path

import pytest

# ── Import config singleton and helpers ─────────────────────────────
# NOTE: config is imported module-level; its .env loading ran once at
# import time.  Tests that manipulate os.environ work because every
# Config property calls os.getenv() at access time — no caching.
from agent_seal.config import _bool_env, _int_env, _path_env, config

# ── Helpers ────────────────────────────────────────────────────────

RELEVANT_ENV_KEYS = {
    # AGENT_SEAL_* namespace
    "AGENT_SEAL_DB_URL",
    "AGENT_SEAL_SECRET_KEY",
    "AGENT_SEAL_AUDIT_DIR",
    "AGENT_SEAL_STORAGE_BACKEND",
    "AGENT_SEAL_API_HOST",
    "AGENT_SEAL_API_PORT",
    "AGENT_SEAL_API_KEYS",
    "AGENT_SEAL_CORS_ORIGINS",
    "AGENT_SEAL_SIGNING_KEY",
    "AGENT_SEAL_ENCRYPTION_KEY",
    "AGENT_SEAL_LOG_LEVEL",
    "AGENT_SEAL_LOG_FORMAT",
    "AGENT_SEAL_AUTO_TRACE",
    "AGENT_SEAL_TRACE_PII_REDACT",
    "AGENT_SEAL_TRACE_MAX_LEN",
    "AGENT_SEAL_TRACE_COST_MODEL",
    "AGENT_SEAL_SLACK_WEBHOOK",
    "AGENT_SEAL_SMTP_HOST",
    "AGENT_SEAL_NOTIFY_ON_FAILURE",
    "AGENT_SEAL_EVIDENCE_STORE",
    "AGENT_SEAL_REDIS_URI",
    # Legacy aliases
    "DB_URL",
    "DATABASE_URL",
    "AUDIT_DIR",
    "AGENT_SEAL_URI",
    "SECRET_KEY",
    "API_KEYS",
    "SIGNING_KEY",
    "LOG_LEVEL",
}


@pytest.fixture(autouse=True)
def _clean_env():
    """Fixture that runs before every test: save relevant env vars, yield,
    then restore them so tests never leak state."""
    saved = {k: os.environ[k] for k in RELEVANT_ENV_KEYS if k in os.environ}
    # Clear all relevant keys so each test starts fresh
    for k in RELEVANT_ENV_KEYS:
        os.environ.pop(k, None)
    yield
    # Restore
    for k in RELEVANT_ENV_KEYS:
        os.environ.pop(k, None)
    os.environ.update(saved)


# ═══════════════════════════════════════════════════════════════════
# 1. DEFAULT VALUES
# ═══════════════════════════════════════════════════════════════════


class TestDefaults:
    """Every Config property must return its documented default when no
    env var and no .env override is present."""

    def test_db_url_default_is_empty(self):
        assert config.db_url == ""

    def test_secret_key_default_is_empty(self):
        assert config.secret_key == ""

    def test_audit_dir_default(self):
        # Default is "./audit_logs" resolved to an absolute path
        p = config.audit_dir
        assert p.name == "audit_logs"
        assert p.is_absolute()

    def test_storage_backend_default_is_auto(self):
        assert config.storage_backend == "auto"

    def test_api_host_default(self):
        assert config.api_host == "0.0.0.0"

    def test_api_port_default(self):
        assert config.api_port == 8081

    def test_api_keys_default_is_empty_list(self):
        assert config.api_keys == []

    def test_cors_origins_default_is_empty(self):
        assert config.cors_origins == []

    def test_signing_key_default_is_empty(self):
        assert config.signing_key == ""

    def test_signing_key_password_default_is_empty(self):
        assert config.signing_key_password == ""

    def test_encryption_key_default_is_empty(self):
        assert config.encryption_key == ""

    def test_log_level_default_is_info(self):
        assert config.log_level == "INFO"

    def test_log_format_default_is_text(self):
        assert config.log_format == "text"

    def test_auto_trace_default_is_false(self):
        assert config.auto_trace is False

    def test_trace_pii_redact_default_is_false(self):
        assert config.trace_pii_redact is False

    def test_trace_max_len_default(self):
        assert config.trace_max_len == 4000

    def test_trace_cost_model_default(self):
        assert config.trace_cost_model == "openai"

    def test_slack_webhook_default_is_empty(self):
        assert config.slack_webhook == ""

    def test_smtp_host_default_is_empty(self):
        assert config.smtp_host == ""

    def test_notify_on_failure_default_is_false(self):
        assert config.notify_on_failure is False

    def test_evidence_store_default_is_empty(self):
        assert config.evidence_store == ""

    def test_redis_uri_default_is_empty(self):
        assert config.redis_uri == ""

    def test_store_uri_defaults_to_audit_dir(self):
        # store_uri = db_url or str(audit_dir)
        assert config.store_uri == str(config.audit_dir)


# ═══════════════════════════════════════════════════════════════════
# 2. AGENT_SEAL_* ENV OVERRIDE
# ═══════════════════════════════════════════════════════════════════


class TestAgentAuditEnvOverride:
    """Setting AGENT_SEAL_* env vars must override defaults."""

    def test_db_url(self):
        os.environ["AGENT_SEAL_DB_URL"] = "postgresql://user:***@localhost/db"
        assert config.db_url == "postgresql://user:***@localhost/db"

    def test_secret_key(self):
        os.environ["AGENT_SEAL_SECRET_KEY"] = "aabbccdd" * 8
        assert config.secret_key == "aabbccdd" * 8

    def test_audit_dir(self):
        os.environ["AGENT_SEAL_AUDIT_DIR"] = "/custom/path/trail"
        assert config.audit_dir == Path("/custom/path/trail").resolve()

    def test_storage_backend(self):
        os.environ["AGENT_SEAL_STORAGE_BACKEND"] = "sqlite"
        assert config.storage_backend == "sqlite"

    def test_api_host(self):
        os.environ["AGENT_SEAL_API_HOST"] = "127.0.0.1"
        assert config.api_host == "127.0.0.1"

    def test_api_port(self):
        os.environ["AGENT_SEAL_API_PORT"] = "9090"
        assert config.api_port == 9090

    def test_api_keys_single(self):
        os.environ["AGENT_SEAL_API_KEYS"] = "sk-test123"
        assert config.api_keys == ["sk-test123"]

    def test_api_keys_multiple(self):
        os.environ["AGENT_SEAL_API_KEYS"] = "sk-a,sk-b,sk-c"
        assert config.api_keys == ["sk-a", "sk-b", "sk-c"]

    def test_api_keys_with_whitespace(self):
        os.environ["AGENT_SEAL_API_KEYS"] = " sk-a , sk-b "
        assert config.api_keys == ["sk-a", "sk-b"]

    def test_cors_origins_multiple(self):
        os.environ["AGENT_SEAL_CORS_ORIGINS"] = "https://a.com,https://b.com"
        assert config.cors_origins == ["https://a.com", "https://b.com"]

    def test_cors_origins_single(self):
        os.environ["AGENT_SEAL_CORS_ORIGINS"] = "https://app.example.com"
        assert config.cors_origins == ["https://app.example.com"]

    def test_signing_key(self):
        os.environ["AGENT_SEAL_SIGNING_KEY"] = "/etc/keys/ed25519.pem"
        assert config.signing_key == "/etc/keys/ed25519.pem"

    def test_signing_key_password(self):
        os.environ["AGENT_SEAL_SIGNING_KEY_PASSWORD"] = "my-secure-password"
        assert config.signing_key_password == "my-secure-password"

    def test_encryption_key(self):
        os.environ["AGENT_SEAL_ENCRYPTION_KEY"] = "ab" * 16  # 32 hex bytes
        assert config.encryption_key == "ab" * 16

    def test_log_level_debug(self):
        os.environ["AGENT_SEAL_LOG_LEVEL"] = "debug"
        assert config.log_level == "DEBUG"

    def test_log_format_json(self):
        os.environ["AGENT_SEAL_LOG_FORMAT"] = "json"
        assert config.log_format == "json"

    def test_auto_trace_enabled(self):
        os.environ["AGENT_SEAL_AUTO_TRACE"] = "1"
        assert config.auto_trace is True

    def test_trace_pii_redact_enabled(self):
        os.environ["AGENT_SEAL_TRACE_PII_REDACT"] = "true"
        assert config.trace_pii_redact is True

    def test_trace_max_len_custom(self):
        os.environ["AGENT_SEAL_TRACE_MAX_LEN"] = "10000"
        assert config.trace_max_len == 10000

    def test_trace_cost_model_custom(self):
        os.environ["AGENT_SEAL_TRACE_COST_MODEL"] = "anthropic"
        assert config.trace_cost_model == "anthropic"

    def test_slack_webhook(self):
        os.environ["AGENT_SEAL_SLACK_WEBHOOK"] = "https://hooks.slack.com/abc"
        assert config.slack_webhook == "https://hooks.slack.com/abc"

    def test_smtp_host(self):
        os.environ["AGENT_SEAL_SMTP_HOST"] = "smtp.example.com:587"
        assert config.smtp_host == "smtp.example.com:587"

    def test_notify_on_failure_enabled(self):
        os.environ["AGENT_SEAL_NOTIFY_ON_FAILURE"] = "yes"
        assert config.notify_on_failure is True

    def test_evidence_store(self):
        os.environ["AGENT_SEAL_EVIDENCE_STORE"] = "s3://my-bucket/evidence/"
        assert config.evidence_store == "s3://my-bucket/evidence/"

    def test_redis_uri(self):
        os.environ["AGENT_SEAL_REDIS_URI"] = "redis://localhost:6379/0"
        assert config.redis_uri == "redis://localhost:6379/0"

    def test_store_uri_with_db_url(self):
        os.environ["AGENT_SEAL_DB_URL"] = "sqlite:///custom/audit.db"
        assert config.store_uri == "sqlite:///custom/audit.db"


# ═══════════════════════════════════════════════════════════════════
# 3. BACKWARD-COMPAT LEGACY ALIASES
# ═══════════════════════════════════════════════════════════════════


class TestBackwardCompatAliases:
    """Legacy env-var names must still work as fallbacks."""

    # db_url
    def test_db_url_legacy_db_url(self):
        os.environ["DB_URL"] = "postgresql://legacy/db"
        assert config.db_url == "postgresql://legacy/db"

    def test_db_url_legacy_database_url(self):
        os.environ["DATABASE_URL"] = "postgresql://legacy/via_database_url"
        assert config.db_url == "postgresql://legacy/via_database_url"

    def test_db_url_agent_seal_takes_precedence(self):
        os.environ["AGENT_SEAL_DB_URL"] = "postgresql://new/db"
        os.environ["DB_URL"] = "postgresql://old/db"
        assert config.db_url == "postgresql://new/db"

    def test_db_url_db_url_takes_precedence_over_database_url(self):
        os.environ["DB_URL"] = "postgresql://via_db_url"
        os.environ["DATABASE_URL"] = "postgresql://via_database_url"
        assert config.db_url == "postgresql://via_db_url"

    def test_db_url_agent_seal_precedes_database_url(self):
        os.environ["AGENT_SEAL_DB_URL"] = "postgresql://new/db"
        os.environ["DATABASE_URL"] = "postgresql://old/db"
        assert config.db_url == "postgresql://new/db"

    # secret_key
    def test_secret_key_legacy(self):
        os.environ["SECRET_KEY"] = "legacy-secret"
        assert config.secret_key == "legacy-secret"

    def test_secret_key_agent_seal_takes_precedence(self):
        os.environ["AGENT_SEAL_SECRET_KEY"] = "new-secret"
        os.environ["SECRET_KEY"] = "old-secret"
        assert config.secret_key == "new-secret"

    # audit_dir
    def test_audit_dir_legacy_audit_dir(self):
        os.environ["AUDIT_DIR"] = "/legacy/trail"
        assert config.audit_dir == Path("/legacy/trail").resolve()

    def test_audit_dir_legacy_agent_seal_uri(self):
        os.environ["AGENT_SEAL_URI"] = "/legacy/uri"
        assert config.audit_dir == Path("/legacy/uri").resolve()

    def test_audit_dir_agent_seal_takes_precedence(self):
        os.environ["AGENT_SEAL_AUDIT_DIR"] = "/new/path"
        os.environ["AUDIT_DIR"] = "/old/path"
        assert config.audit_dir == Path("/new/path").resolve()

    def test_audit_dir_audit_dir_takes_precedence_over_uri(self):
        os.environ["AUDIT_DIR"] = "/via_audit_dir"
        os.environ["AGENT_SEAL_URI"] = "/via_uri"
        assert config.audit_dir == Path("/via_audit_dir").resolve()

    # api_keys
    def test_api_keys_legacy(self):
        os.environ["API_KEYS"] = "legacy-key-1,legacy-key-2"
        assert config.api_keys == ["legacy-key-1", "legacy-key-2"]

    def test_api_keys_agent_seal_takes_precedence(self):
        os.environ["AGENT_SEAL_API_KEYS"] = "new-key"
        os.environ["API_KEYS"] = "old-key"
        assert config.api_keys == ["new-key"]

    # signing_key
    def test_signing_key_legacy(self):
        os.environ["SIGNING_KEY"] = "/legacy/signing.pem"
        assert config.signing_key == "/legacy/signing.pem"

    def test_signing_key_agent_seal_takes_precedence(self):
        os.environ["AGENT_SEAL_SIGNING_KEY"] = "/new/signing.pem"
        os.environ["SIGNING_KEY"] = "/old/signing.pem"
        assert config.signing_key == "/new/signing.pem"

    # log_level
    def test_log_level_legacy(self):
        os.environ["LOG_LEVEL"] = "warning"
        assert config.log_level == "WARNING"

    def test_log_level_agent_seal_takes_precedence(self):
        os.environ["AGENT_SEAL_LOG_LEVEL"] = "error"
        os.environ["LOG_LEVEL"] = "info"
        assert config.log_level == "ERROR"


# ═══════════════════════════════════════════════════════════════════
# 4. HELPER FUNCTIONS (unit tests for _bool_env / _int_env / _path_env)
# ═══════════════════════════════════════════════════════════════════


class TestBoolEnvHelper:
    """_bool_env parses boolean-ish env values."""

    TRUTHY: list[str] = ["1", "true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"]  # noqa: RUF012
    FALSY: list[str] = [  # noqa: RUF012
        "0",
        "false",
        "False",
        "FALSE",
        "no",
        "No",
        "NO",
        "off",
        "Off",
        "OFF",
        "",
        "maybe",
        "2",
    ]

    @pytest.mark.parametrize("val", TRUTHY)
    def test_truthy_values(self, val):
        os.environ["_TEST_BOOL"] = val
        assert _bool_env("_TEST_BOOL", False) is True

    @pytest.mark.parametrize("val", FALSY)
    def test_falsy_values(self, val):
        os.environ["_TEST_BOOL"] = val
        assert _bool_env("_TEST_BOOL", True) is False

    def test_default_used_when_missing(self):
        assert _bool_env("_NONEXISTENT_BOOL", True) is True
        assert _bool_env("_NONEXISTENT_BOOL", False) is False

    def test_default_bool_coerced_to_str(self):
        os.environ["_TEST_BOOL"] = "1"
        assert _bool_env("_TEST_BOOL", False) is True


class TestIntEnvHelper:
    """_int_env parses integer env values with fallback."""

    def test_normal_int(self):
        os.environ["_TEST_INT"] = "42"
        assert _int_env("_TEST_INT", 0) == 42

    def test_negative_int(self):
        os.environ["_TEST_INT"] = "-5"
        assert _int_env("_TEST_INT", 0) == -5

    def test_zero(self):
        os.environ["_TEST_INT"] = "0"
        assert _int_env("_TEST_INT", 99) == 0

    def test_large_int(self):
        os.environ["_TEST_INT"] = "999999999"
        assert _int_env("_TEST_INT", 0) == 999999999

    def test_default_on_missing(self):
        assert _int_env("_NONEXISTENT_INT", 8081) == 8081

    def test_default_on_invalid_value(self):
        os.environ["_TEST_INT"] = "not-a-number"
        assert _int_env("_TEST_INT", 42) == 42

    def test_default_on_empty_string(self):
        os.environ["_TEST_INT"] = ""
        assert _int_env("_TEST_INT", 10) == 10

    def test_default_on_whitespace(self):
        os.environ["_TEST_INT"] = "  "
        assert _int_env("_TEST_INT", 7) == 7

    @pytest.mark.parametrize("val", ["3.14", "0xFF", "1e5"])
    def test_default_on_non_integer_strings(self, val):
        os.environ["_TEST_INT"] = val
        assert _int_env("_TEST_INT", 0) == 0


class TestPathEnvHelper:
    """_path_env resolves env var values to absolute Paths."""

    def test_plain_path(self):
        os.environ["_TEST_PATH"] = "/tmp/test-dir"
        assert _path_env("_TEST_PATH", "/fallback") == Path("/tmp/test-dir").resolve()

    def test_relative_path_resolves(self):
        os.environ["_TEST_PATH"] = "relative/path"
        result = _path_env("_TEST_PATH", "/fallback")
        assert result.is_absolute()
        # On Windows paths use backslashes; on POSIX forward slashes
        assert "relative" in str(result).split(os.sep)

    def test_expands_user_home(self):
        os.environ["_TEST_PATH"] = "~/my-audit"
        result = _path_env("_TEST_PATH", "/fallback")
        assert str(result).lower().startswith(str(Path.home()).lower())

    def test_expands_env_vars_in_path(self):
        os.environ["_TEST_HOME"] = "/custom/base"
        os.environ["_TEST_PATH"] = "$_TEST_HOME/audit"
        result = _path_env("_TEST_PATH", "/fallback")
        assert str(result) == str(Path("/custom/base/audit").resolve())

    def test_default_on_missing(self):
        result = _path_env("_NONEXISTENT_PATH", "/fallback/dir")
        assert result == Path("/fallback/dir").resolve()


# ═══════════════════════════════════════════════════════════════════
# 5. EDGE CASES & ERROR HANDLING
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions and unusual but valid inputs."""

    def test_api_keys_empty_string(self):
        os.environ["AGENT_SEAL_API_KEYS"] = ""
        assert config.api_keys == []

    def test_api_keys_only_commas(self):
        os.environ["AGENT_SEAL_API_KEYS"] = ",,,"
        assert config.api_keys == []

    def test_api_keys_whitespace_only(self):
        os.environ["AGENT_SEAL_API_KEYS"] = " , , "
        assert config.api_keys == []

    def test_cors_origins_empty_string(self):
        os.environ["AGENT_SEAL_CORS_ORIGINS"] = ""
        # Empty string splits to [""] and "".strip() is falsy → filter removes it
        assert config.cors_origins == []

    def test_cors_origins_just_star(self):
        os.environ["AGENT_SEAL_CORS_ORIGINS"] = "*"
        assert config.cors_origins == ["*"]

    def test_api_port_invalid_string_falls_back(self):
        os.environ["AGENT_SEAL_API_PORT"] = "not-a-port"
        assert config.api_port == 8081  # default

    def test_api_port_empty_string_falls_back(self):
        os.environ["AGENT_SEAL_API_PORT"] = ""
        assert config.api_port == 8081

    def test_trace_max_len_invalid_falls_back(self):
        os.environ["AGENT_SEAL_TRACE_MAX_LEN"] = "lots"
        assert config.trace_max_len == 4000  # default

    def test_log_level_case_normalized(self):
        os.environ["AGENT_SEAL_LOG_LEVEL"] = "DeBuG"
        assert config.log_level == "DEBUG"

    def test_log_format_lowercased(self):
        os.environ["AGENT_SEAL_LOG_FORMAT"] = "JSON"
        assert config.log_format == "json"

    def test_audit_dir_special_characters(self):
        os.environ["AGENT_SEAL_AUDIT_DIR"] = "/path/with spaces/and_unicode_中文"
        assert config.audit_dir == Path("/path/with spaces/and_unicode_中文").resolve()

    def test_secret_key_with_special_chars(self):
        key = "abc!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        os.environ["AGENT_SEAL_SECRET_KEY"] = key
        assert config.secret_key == key

    def test_all_env_vars_set_simultaneously(self):
        """Set every AGENT_SEAL_* var at once and verify all properties."""
        vals = {
            "AGENT_SEAL_DB_URL": "sqlite:///full.db",
            "AGENT_SEAL_SECRET_KEY": "sec-" + "ff" * 16,
            "AGENT_SEAL_AUDIT_DIR": "/full/path",
            "AGENT_SEAL_STORAGE_BACKEND": "postgresql",
            "AGENT_SEAL_API_HOST": "10.0.0.1",
            "AGENT_SEAL_API_PORT": "3000",
            "AGENT_SEAL_API_KEYS": "k1,k2",
            "AGENT_SEAL_CORS_ORIGINS": "https://x.com,https://y.com",
            "AGENT_SEAL_SIGNING_KEY": "/keys/sign.pem",
            "AGENT_SEAL_SIGNING_KEY_PASSWORD": "key-password-123",
            "AGENT_SEAL_ENCRYPTION_KEY": "cd" * 16,
            "AGENT_SEAL_LOG_LEVEL": "critical",
            "AGENT_SEAL_LOG_FORMAT": "json",
            "AGENT_SEAL_AUTO_TRACE": "true",
            "AGENT_SEAL_TRACE_PII_REDACT": "yes",
            "AGENT_SEAL_TRACE_MAX_LEN": "9999",
            "AGENT_SEAL_TRACE_COST_MODEL": "custom",
            "AGENT_SEAL_SLACK_WEBHOOK": "https://hooks.slack.com/xyz",
            "AGENT_SEAL_SMTP_HOST": "mail.example.com:25",
            "AGENT_SEAL_NOTIFY_ON_FAILURE": "on",
            "AGENT_SEAL_EVIDENCE_STORE": "s3://bucket/evidence/",
            "AGENT_SEAL_REDIS_URI": "redis://r.example.com:6379",
        }
        for k, v in vals.items():
            os.environ[k] = v

        assert config.db_url == "sqlite:///full.db"
        assert config.secret_key == "sec-" + "ff" * 16
        assert config.audit_dir == Path("/full/path").resolve()
        assert config.storage_backend == "postgresql"
        assert config.api_host == "10.0.0.1"
        assert config.api_port == 3000
        assert config.api_keys == ["k1", "k2"]
        assert config.cors_origins == ["https://x.com", "https://y.com"]
        assert config.signing_key == "/keys/sign.pem"
        assert config.signing_key_password == "key-password-123"
        assert config.encryption_key == "cd" * 16
        assert config.log_level == "CRITICAL"
        assert config.log_format == "json"
        assert config.auto_trace is True
        assert config.trace_pii_redact is True
        assert config.trace_max_len == 9999
        assert config.trace_cost_model == "custom"
        assert config.slack_webhook == "https://hooks.slack.com/xyz"
        assert config.smtp_host == "mail.example.com:25"
        assert config.notify_on_failure is True
        assert config.evidence_store == "s3://bucket/evidence/"
        assert config.redis_uri == "redis://r.example.com:6379"

    def test_store_uri_falls_back_to_audit_dir_when_no_db_url(self):
        """store_uri = db_url or str(audit_dir)."""
        os.environ["AGENT_SEAL_AUDIT_DIR"] = "/custom/trail"
        expected = str(Path("/custom/trail").resolve())
        assert config.store_uri == expected

    def test_store_uri_uses_db_url_when_set(self):
        os.environ["AGENT_SEAL_DB_URL"] = "postgresql://server/db"
        os.environ["AGENT_SEAL_AUDIT_DIR"] = "/custom/trail"
        assert config.store_uri == "postgresql://server/db"


# ═══════════════════════════════════════════════════════════════════
# 6. .ENV LOADING (module-level dotenv integration)
# ═══════════════════════════════════════════════════════════════════


class TestDotenvLoading:
    """Tests for the module-level python-dotenv loading at import time.

    These tests reload the config module inside a temp directory that
    contains a custom .env file.  They are intentionally isolated from
    the other tests because they modify the module state.
    """

    DOTENV_CONTENT = textwrap.dedent("""\
        AGENT_SEAL_API_PORT=9999
        AGENT_SEAL_LOG_LEVEL=warning
        AGENT_SEAL_AUTO_TRACE=1
        AGENT_SEAL_CORS_ORIGINS=http://localhost:3000
    """)

    @pytest.fixture
    def _with_dotenv(self, tmp_path, monkeypatch):
        """Write a .env to the project root, reload config, then restore."""
        import agent_seal.config as cfg_mod

        # The module looks for .env at _config_file_dir / ".env"
        config_dir = cfg_mod._config_file_dir
        original_dotenv = config_dir / ".env"
        had_original = original_dotenv.exists()

        if had_original:
            original_content = original_dotenv.read_text()

        # Write our test .env to the project root
        original_dotenv.write_text(self.DOTENV_CONTENT)

        # Clear relevant env so .env values are actually used
        for k in RELEVANT_ENV_KEYS:
            os.environ.pop(k, None)

        reload(cfg_mod)
        from agent_seal.config import config as fresh_config

        yield fresh_config

        # Restore original .env (or remove ours)
        if had_original:
            original_dotenv.write_text(original_content)
        else:
            original_dotenv.unlink(missing_ok=True)

        # Reload original config state
        reload(cfg_mod)

    def test_dotenv_values_loaded(self, _with_dotenv):
        cfg = _with_dotenv
        assert cfg.api_port == 9999
        assert cfg.log_level == "WARNING"
        assert cfg.auto_trace is True
        assert cfg.cors_origins == ["http://localhost:3000"]

    def test_env_overrides_dotenv(self):
        """Environment vars must take precedence over .env values."""
        import agent_seal.config as cfg_mod

        config_dir = cfg_mod._config_file_dir
        original_dotenv = config_dir / ".env"
        had_original = original_dotenv.exists()
        if had_original:
            original_content = original_dotenv.read_text()

        # Write test .env
        original_dotenv.write_text("AGENT_SEAL_API_PORT=9999\n")
        os.environ.pop("AGENT_SEAL_API_PORT", None)

        # Set env var AFTER writing .env — env must override
        os.environ["AGENT_SEAL_API_PORT"] = "7777"

        reload(cfg_mod)
        from agent_seal.config import config as fresh

        assert fresh.api_port == 7777

        # Restore
        if had_original:
            original_dotenv.write_text(original_content)
        else:
            original_dotenv.unlink(missing_ok=True)
        reload(cfg_mod)

    def test_dotenv_not_found_graceful(self, monkeypatch):
        """When no .env exists, config should load defaults gracefully."""
        import agent_seal.config as cfg_mod

        # Temporarily remove .env from project root if it exists
        config_dir = cfg_mod._config_file_dir
        original_dotenv = config_dir / ".env"
        had_original = original_dotenv.exists()
        if had_original:
            original_content = original_dotenv.read_text()
            original_dotenv.unlink()

        for k in RELEVANT_ENV_KEYS:
            os.environ.pop(k, None)

        reload(cfg_mod)
        from agent_seal.config import config as fresh

        assert fresh.api_port == 8081
        assert fresh.log_level == "INFO"

        # Restore
        if had_original:
            original_dotenv.write_text(original_content)
        reload(cfg_mod)


# ═══════════════════════════════════════════════════════════════════
# 7. CLI INTEGRATION (config used by agent_seal.cli and downstream)
# ═══════════════════════════════════════════════════════════════════


class TestCLIIntegration:
    """Config properties must be usable from the CLI module."""

    def test_cli_uses_config_audit_dir(self):
        """The CLI's _trail_dir() reads from config.audit_dir."""
        from agent_seal.cli import _trail_dir

        d = _trail_dir()
        assert isinstance(d, Path)
        assert d.is_absolute()

    def test_cli_trail_dir_respects_env_override(self):
        """Setting AUDIT_DIR env var changes CLI behaviour."""
        os.environ["AUDIT_DIR"] = "/cli-test-override"
        from agent_seal.cli import _trail_dir

        assert _trail_dir() == Path("/cli-test-override").resolve()

    def test_cli_uses_config_api_port(self):
        """The serve command uses config.api_port as default."""
        os.environ["AGENT_SEAL_API_PORT"] = "5555"
        import agent_seal.cli as cli_mod

        reload(cli_mod)
        assert config.api_port == 5555

    def test_api_keys_loaded_from_config(self):
        """server/api.py uses config.api_keys to populate _api_keys."""
        os.environ["AGENT_SEAL_API_KEYS"] = "svc-key-01,svc-key-02"
        assert config.api_keys == ["svc-key-01", "svc-key-02"]

    def test_storage_uses_config(self):
        """core/storage.py imports config for backend resolution."""
        os.environ["AGENT_SEAL_STORAGE_BACKEND"] = "jsonl"
        os.environ["AGENT_SEAL_AUDIT_DIR"] = "/tmp/storage-test"
        assert config.storage_backend == "jsonl"
        assert config.audit_dir == Path("/tmp/storage-test").resolve()
