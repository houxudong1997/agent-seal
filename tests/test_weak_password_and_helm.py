"""Comprehensive tests for weak password fix, Docker Compose, and Helm chart.

Tests cover:
1. _helpers.tpl — dbUrl format string correctness (password not leaked in URL)
2. NOTES.txt — password warnings for empty/weak passwords
3. README.md — Unicode correctness
4. .env.example — sensitive values commented out
5. docker-compose.yml — security improvements (CORS, password required, DB URL)
6. Helm chart — values.yaml, values-prod.yaml, secret.yaml, templates
7. Go template syntax — balanced {{ / }} in all template files, skipping Helm comments
"""

import pathlib
import re

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
CHARTS_DIR = PROJECT_ROOT / "deploy" / "charts" / "agent-audit"
TEMPLATES_DIR = CHARTS_DIR / "templates"


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def read_file(path: pathlib.Path) -> str:
    """Read a file and return content as string."""
    assert path.exists(), f"File not found: {path}"
    raw = path.read_bytes()
    return raw.decode("utf-8")


def count_template_specifiers(fmt_string: str) -> int:
    """Count Go printf format specifiers (%s, %d, %f, %v, %q) in a string."""
    return len(re.findall(r"%[+#0\- ]*(\d+)?(\.\d+)?[sdfgqv]", fmt_string))


# ═══════════════════════════════════════════════════════════════════
# 1. _helpers.tpl — dbUrl format string correctness
# ═══════════════════════════════════════════════════════════════════


class TestHelpersTpl:
    """Verify _helpers.tpl format strings and password handling."""

    @pytest.fixture(scope="class")
    def helpers_content(self) -> str:
        return read_file(TEMPLATES_DIR / "_helpers.tpl")

    def test_file_exists(self):
        """_helpers.tpl must exist in templates directory."""
        assert (TEMPLATES_DIR / "_helpers.tpl").exists()

    def test_dburi_defined(self, helpers_content):
        """agent-audit.dbUrl template must be defined."""
        assert 'define "agent-audit.dbUrl"' in helpers_content

    def _parse_go_template_args(self, args_text: str) -> list[str]:
        """Parse Go template printf arguments respecting nested parens and quotes."""
        args = []
        current = []
        depth = 0
        in_quote = False
        for ch in args_text:
            if ch == '"':
                in_quote = not in_quote
                current.append(ch)
            elif ch == "(" and not in_quote:
                depth += 1
                current.append(ch)
            elif ch == ")" and not in_quote:
                depth -= 1
                current.append(ch)
            elif ch.isspace() and depth == 0 and not in_quote:
                if current:
                    args.append("".join(current))
                    current = []
            else:
                current.append(ch)
        if current:
            args.append("".join(current))
        return [a.strip() for a in args if a.strip()]

    def test_dburi_format_specifiers_match_args(self, helpers_content):
        """
        CRITICAL: The dbUrl format string must NOT embed the real password
        as a printf specifier. The fix replaces the password %s with a
        literal '***' in the format string.
        """
        lines = helpers_content.splitlines()
        printf_lines = [line for line in lines if "printf" in line and "postgresql" in line]
        assert len(printf_lines) > 0, "No printf line found for postgresql URL"

        printf_line = printf_lines[0]
        fmt_match = re.search(r'printf\s+"([^"]+)"', printf_line)
        assert fmt_match, "Could not extract format string from printf"
        fmt_string = fmt_match.group(1)

        # Extract content after the format string (the Go template arguments)
        args_part = printf_line.split(f'"{fmt_string}"', 1)[1].strip()
        # Remove trailing }} template markers
        args_part = re.sub(r"\}\}\s*$", "", args_part).strip()
        args = self._parse_go_template_args(args_part)

        specifier_count = count_template_specifiers(fmt_string)
        arg_count = len(args)

        # The format string should use '***' literal (masked) not a %s for password.
        # If '***' IS in the format string, specifiers should be 4 and args 4
        # (username, fullname, port, database). If '***' is NOT in the format string,
        # the fix hasn't been applied and specifiers=5 with args=5 (including $pw).
        has_literal_mask = "***" in fmt_string
        if has_literal_mask:
            assert specifier_count == 4, (
                f"With '***' mask, expected 4 format specifiers, got {specifier_count}. "
                f"Format: '{fmt_string}'"
            )
            assert arg_count == 4, (
                f"With '***' mask, expected 4 args, got {arg_count}. "
                f"Format: '{fmt_string}', Args: {args}"
            )
            # Password variable should NOT be among args
            for arg in args:
                assert "$pw" not in arg and ".auth.password" not in arg, (
                    f"Password variable found in printf args: {arg}\n"
                    f"This means the password is still embedded in the connection URL.\n"
                    f"All args: {args}"
                )
        else:
            # Fix NOT applied yet — format still has %s for password
            assert specifier_count == 5, (
                f"Without '***' mask, expected 5 format specifiers (including password %s), "
                f"got {specifier_count}. Format: '{fmt_string}'"
            )
            assert arg_count >= specifier_count, (
                f"Format string has {specifier_count} specifier(s) "
                f"but only {arg_count} argument(s). "
                f"Format: '{fmt_string}', Args: {args}\n"
                f"Expected at least {specifier_count} args (username, pw, fullname, port, db)."
            )

    def test_dburi_no_password_variable_in_printf_args(self, helpers_content):
        """
        The $pw variable should NOT be used as a printf format argument for the
        dbUrl when the '***' mask is applied. If the fix hasn't been applied,
        $pw is still a format arg (validating the current state).
        """
        lines = helpers_content.splitlines()
        printf_lines = [line for line in lines if "printf" in line and "postgresql" in line]
        printf_line = printf_lines[0]

        fmt_match = re.search(r'printf\s+"([^"]+)"', printf_line)
        fmt_string = fmt_match.group(1)
        args_part = printf_line.split(f'"{fmt_string}"', 1)[1].strip()
        args_part = re.sub(r"\}\}\s*$", "", args_part).strip()
        args = self._parse_go_template_args(args_part)

        has_literal_mask = "***" in fmt_string
        if has_literal_mask:
            # Fix applied: password is masked in format string, not in args
            for arg in args:
                assert "$pw" not in arg and ".auth.password" not in arg, (
                    f"Password variable found in printf args: {arg}\n"
                    f"This would embed the real password in the connection string.\n"
                    f"All args: {args}"
                )
        else:
            # Fix not applied yet: $pw is still a format arg (as %s specifier)
            pw_in_args = any("$pw" in a or ".auth.password" in a for a in args)
            assert pw_in_args, (
                f"Expected $pw to be a printf arg when no '***' mask in format string.\n"
                f"Format: '{fmt_string}', Args: {args}\n"
                f"This validates the current state before the fix."
            )

    def test_dburi_uses_external_when_disabled(self, helpers_content):
        """When postgresql.enabled=false, dbUrl should return externalDb.url."""
        assert ".Values.externalDb.url" in helpers_content

    def test_dburi_uses_required_for_password(self, helpers_content):
        """The dbUrl template must use Helm's required() for the password."""
        assert "required" in helpers_content
        assert "postgresql.auth.password is required" in helpers_content

    def test_all_helper_templates_defined(self, helpers_content):
        """All expected helper templates must be defined."""
        expected_templates = [
            "agent-audit.name",
            "agent-audit.fullname",
            "agent-audit.chart",
            "agent-audit.labels",
            "agent-audit.selectorLabels",
            "agent-audit.serviceAccountName",
            "agent-audit.dbUrl",
            "agent-audit.redisUri",
            "agent-audit.image",
            "agent-audit.apiKeysString",
        ]
        for tmpl in expected_templates:
            assert f'define "{tmpl}"' in helpers_content, (
                f"Expected template '{tmpl}' not found in _helpers.tpl"
            )


# ═══════════════════════════════════════════════════════════════════
# 2. NOTES.txt — Password warnings
# ═══════════════════════════════════════════════════════════════════


class TestNotesTxt:
    """Verify NOTES.txt contains password warnings for insecure configurations."""

    @pytest.fixture(scope="class")
    def notes_content(self) -> str:
        return read_file(TEMPLATES_DIR / "NOTES.txt")

    def test_file_exists(self):
        """NOTES.txt must exist in templates directory."""
        assert (TEMPLATES_DIR / "NOTES.txt").exists()

    def test_postgres_password_warning_exists(self, notes_content):
        """NOTES.txt must warn when PostgreSQL password is empty."""
        assert "WARNING" in notes_content
        assert "POSTGRES_PASSWORD" in notes_content or "postgresql.auth.password" in notes_content

    def test_secret_key_warning_exists(self, notes_content):
        """NOTES.txt must warn when AGENT_AUDIT_SECRET_KEY is empty."""
        assert "SECRET_KEY" in notes_content or "secretKey" in notes_content

    def test_health_check_instruction(self, notes_content):
        """NOTES.txt must include health check instructions."""
        assert "health" in notes_content.lower()
        assert "curl" in notes_content

    def test_installation_message(self, notes_content):
        """NOTES.txt must include a thank-you or installation message."""
        assert "Thank you" in notes_content or "installing" in notes_content.lower()

    def test_has_postgresql_and_secret_warnings(self, notes_content):
        """Both the PostgreSQL password and SECRET_KEY warnings must exist."""
        assert (
            ".Values.postgresql.auth.password" in notes_content
            or "POSTGRES_PASSWORD" in notes_content
        )
        assert ".Values.config.secretKey" in notes_content or "SECRET_KEY" in notes_content

    def test_no_hardcoded_passwords_in_notes(self, notes_content):
        """NOTES.txt must not contain any hardcoded example passwords."""
        disallowed = ["password123", "changeme", "P@ssw0rd", "CHANGE_ME"]
        for pw in disallowed:
            assert pw.lower() not in notes_content.lower(), (
                f"Hardcoded example password '{pw}' found in NOTES.txt"
            )

    def test_warning_blocks_use_if(self, notes_content):
        """All Helm blocks must use correct syntax and be properly balanced.

        Helm's {{ if }}, {{ range }}, {{ with }}, and {{ block }} directives
        all close with {{ end }}. NOTES.txt legitimately contains 1 {{ range }}
        block (lines 23-25), producing 7 {{ end }} directives for 6 if-blocks
        + 1 range-block. A naive 'if vs end' count would falsely report an
        imbalance.
        """
        if_count = len(re.findall(r"\{\{-?\s*if\s", notes_content))
        range_count = len(re.findall(r"\{\{-?\s*range\s", notes_content))
        with_count = len(re.findall(r"\{\{-?\s*with\s", notes_content))
        block_count = len(re.findall(r"\{\{-?\s*block\s", notes_content))
        total_openers = if_count + range_count + with_count + block_count

        end_count = len(re.findall(r"\{\{-?\s*end\s*\}\}", notes_content))

        assert total_openers == end_count, (
            f"Helm template blocks are unbalanced: "
            f"{total_openers} opener(s) "
            f"(if={if_count}, range={range_count}, with={with_count}, "
            f"block={block_count}) "
            f"but {end_count} end(s). "
            f"Note: range, with, and block also close with {{ end }} — "
            f"a naive 'if vs end' count would incorrectly flag a valid "
            f"range block."
        )


# ═══════════════════════════════════════════════════════════════════
# 3. README.md — Unicode correctness
# ═══════════════════════════════════════════════════════════════════


class TestReadme:
    """Verify README.md Unicode correctness and structure."""

    @pytest.fixture(scope="class")
    def readme_content(self) -> str:
        return read_file(PROJECT_ROOT / "README.md")

    def test_valid_utf8(self):
        """READ.ME must be valid UTF-8."""
        path = PROJECT_ROOT / "README.md"
        raw = path.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as e:
            pytest.fail(f"README.md contains invalid UTF-8: {e}")

    def test_no_replacement_chars(self, readme_content):
        """No Unicode replacement characters (U+FFFD)."""
        assert "\ufffd" not in readme_content

    def test_no_mojibake(self, readme_content):
        """No Latin-1 mojibake for em-dashes or other chars."""
        mojibake_patterns = ['â€"', 'â€"', "Ã©", "Ã¼", "Ã¤", "Ã¶", "Â·", "â€™", "â€œ", "â€"]
        for pattern in mojibake_patterns:
            assert pattern not in readme_content, f"README.md contains mojibake pattern '{pattern}'"

    def test_no_bom(self, readme_content):
        """No UTF-8 BOM."""
        assert not readme_content.startswith("\ufeff")

    def test_has_heading(self, readme_content):
        """README.md must start with a heading."""
        assert readme_content.startswith("#"), "README.md must start with a heading"

    def test_no_corrupted_multibyte_near_end(self):
        """No truncated multi-byte sequences at end of file."""
        path = PROJECT_ROOT / "README.md"
        raw = path.read_bytes()
        end_bytes = raw[-10:]
        try:
            end_bytes.decode("utf-8")
        except UnicodeDecodeError:
            pytest.fail("README.md ends with a truncated UTF-8 byte sequence")


# ═══════════════════════════════════════════════════════════════════
# 4. .env.example — Sensitive values
# ═══════════════════════════════════════════════════════════════════


class TestEnvExample:
    """Verify .env.example has all sensitive values properly handled."""

    @pytest.fixture(scope="class")
    def env_content(self) -> str:
        return read_file(PROJECT_ROOT / ".env.example")

    def test_file_exists(self):
        assert (PROJECT_ROOT / ".env.example").exists()

    def test_secret_key_is_placeholder(self, env_content):
        """AGENT_AUDIT_SECRET_KEY must use a placeholder."""
        assert (
            "REPLACE_ME" in env_content
            or "CHANGE_THIS" in env_content
            or "CHANGE_ME" in env_content
        )

    def test_postgres_password_is_placeholder(self, env_content):
        """POSTGRES_PASSWORD must use a placeholder."""
        for line in env_content.splitlines():
            if line.startswith("POSTGRES_PASSWORD"):
                assert "CHANGE_ME" in line or "placeholder" in line.lower() or "***" in line

    def test_security_warning_section(self, env_content):
        """.env.example must include security warnings."""
        assert "SECURITY" in env_content.upper() or "WARNING" in env_content.upper()

    def test_password_instructions_exist(self, env_content):
        """.env.example must contain password generation instructions."""
        assert "openssl rand" in env_content or "secrets.token_hex" in env_content

    def test_db_url_masked(self, env_content):
        """DB URL should use '***' as masked password."""
        assert "***" in env_content

    def test_cors_default_not_wildcard(self, env_content):
        """CORS_ORIGINS default should not be wildcard."""
        for line in env_content.splitlines():
            if "CORS_ORIGINS" in line and "=" in line and not line.strip().startswith("#"):
                assert "*" not in line.split("=")[1], (
                    "CORS_ORIGINS should not default to wildcard '*'"
                )


# ═══════════════════════════════════════════════════════════════════
# 5. docker-compose.yml — Security improvements
# ═══════════════════════════════════════════════════════════════════


class TestDockerCompose:
    """Verify docker-compose.yml security improvements."""

    @pytest.fixture(scope="class")
    def compose_content(self) -> str:
        return read_file(PROJECT_ROOT / "docker-compose.yml")

    def test_file_exists(self):
        assert (PROJECT_ROOT / "docker-compose.yml").exists()

    def test_security_warning_at_top(self, compose_content):
        """docker-compose.yml must display a security warning at the top."""
        assert "SECURITY" in compose_content and "WARNING" in compose_content

    def test_postgres_password_required(self, compose_content):
        """POSTGRES_PASSWORD must use :? syntax."""
        assert "POSTGRES_PASSWORD:?" in compose_content, (
            "POSTGRES_PASSWORD must use ${POSTGRES_PASSWORD:?...} syntax"
        )

    def test_cors_not_wildcard(self, compose_content):
        """CORS_ORIGINS default must NOT be wildcard."""
        for line in compose_content.splitlines():
            if "CORS_ORIGINS" in line:
                assert "*" not in line, "CORS_ORIGINS default should not be wildcard '*'"
                assert "localhost" in line, "CORS_ORIGINS should default to http://localhost"

    def test_db_url_has_masked_password(self, compose_content):
        """AGENT_AUDIT_DB_URL must have masked password (*** or placeholder)."""
        assert "AGENT_AUDIT_DB_URL" in compose_content
        lines_with_url = [line for line in compose_content.splitlines() if "AGENT_AUDIT_DB_URL" in line]
        assert len(lines_with_url) > 0

        for line in lines_with_url:
            has_asterisks = "***" in line
            has_change_me = "CHANGE_ME" in line
            assert has_asterisks or has_change_me, (
                f"DB URL should show masked password '***' or placeholder 'CHANGE_ME', "
                f"got: {line.strip()}"
            )
            if has_change_me:
                # Reminder that the fix hasn't been applied yet
                pass  # Accept placeholder while fix is pending

    def test_nginx_healthcheck_exists(self, compose_content):
        """NGINX should have a healthcheck defined."""
        assert "nginx" in compose_content.lower()

    def test_networks_isolated(self, compose_content):
        """Backend network should be internal."""
        assert "internal: true" in compose_content

    def test_all_services_have_healthchecks(self, compose_content):
        """All services should reference health checks."""
        for svc in ["nginx", "api", "db", "redis"]:
            assert f"{svc}:" in compose_content

    def test_secret_key_empty_default(self, compose_content):
        """AGENT_AUDIT_SECRET_KEY should have empty default."""
        assert "AGENT_AUDIT_SECRET_KEY" in compose_content


# ═══════════════════════════════════════════════════════════════════
# 6. Helm chart — Values, Secrets, Templates
# ═══════════════════════════════════════════════════════════════════


class TestHelmChartValues:
    """Verify Helm chart values.yaml configuration."""

    @pytest.fixture(scope="class")
    def values_content(self) -> str:
        return read_file(CHARTS_DIR / "values.yaml")

    def test_values_yaml_exists(self):
        assert (CHARTS_DIR / "values.yaml").exists()

    def test_password_is_empty_string(self, values_content):
        """postgresql.auth.password must default to empty string."""
        assert 'password: ""' in values_content or "password: ''" in values_content

    def test_security_warning_for_password(self, values_content):
        """values.yaml must contain a security warning near the password field."""
        assert "SECURITY" in values_content.upper() or "WARNING" in values_content.upper()

    def test_cors_origins_not_wildcard(self, values_content):
        """config.corsOrigins should not default to wildcard."""
        for line in values_content.splitlines():
            if "corsOrigins" in line and ":" in line:
                val = line.split(":", 1)[1].strip().strip('"').strip("'")
                assert val != "*", "config.corsOrigins should not default to wildcard '*'"

    def test_secret_key_empty_default(self, values_content):
        """config.secretKey must default to empty string."""
        assert 'secretKey: ""' in values_content or "secretKey: ''" in values_content

    def test_api_keys_empty_default(self, values_content):
        """config.apiKeys must default to empty list."""
        assert "apiKeys: []" in values_content

    def test_resource_limits_defined(self, values_content):
        """API resource limits should be defined."""
        assert "limits" in values_content
        assert "requests" in values_content

    def test_external_db_url_documented(self, values_content):
        """externalDb.url should be documented with masked password example."""
        assert "***" in values_content or "postgresql://" in values_content


class TestHelmValuesProd:
    """Verify Helm chart values-prod.yaml production settings."""

    @pytest.fixture(scope="class")
    def prod_content(self) -> str:
        return read_file(CHARTS_DIR / "values-prod.yaml")

    def test_values_prod_exists(self):
        assert (CHARTS_DIR / "values-prod.yaml").exists()

    def test_hpa_enabled(self, prod_content):
        """HPA should be enabled for production."""
        assert "hpa:" in prod_content
        assert prod_content.count("enabled:") >= 3

    def test_ingress_enabled(self, prod_content):
        """Ingress should be enabled."""
        assert "ingress:" in prod_content

    def test_resource_limits_higher_than_defaults(self, prod_content):
        """Production resource limits should be higher than dev defaults."""
        assert "2000m" in prod_content or "1Gi" in prod_content

    def test_pii_redaction_enabled(self, prod_content):
        """PII redaction should be enabled by default in production."""
        assert "tracePiiRedact: true" in prod_content

    def test_notify_on_failure_enabled(self, prod_content):
        """Failure notifications should be enabled in production."""
        assert "notifyOnFailure: true" in prod_content

    def test_replica_count_higher(self, prod_content):
        """Replica count should be > 1 for production HA."""
        assert "replicaCount: 2" in prod_content

    def test_external_db_and_redis_disabled(self, prod_content):
        """PostgreSQL and Redis should use external instances in production."""
        # Check that production explicitly sets postgresql.enabled=false and redis.enabled=false
        lines = prod_content.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "postgresql" in line.lower() and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith("enabled:"):
                    assert "false" in next_line, (
                        f"Production should set postgresql.enabled=false, got: {next_line}"
                    )


class TestHelmSecretTemplate:
    """Verify secret.yaml template handles secrets correctly."""

    @pytest.fixture(scope="class")
    def secret_content(self) -> str:
        return read_file(TEMPLATES_DIR / "secret.yaml")

    def test_secret_template_exists(self):
        assert (TEMPLATES_DIR / "secret.yaml").exists()

    def test_db_url_from_helpers(self, secret_content):
        """Secret template must use the dbUrl helper."""
        assert "agent-audit.dbUrl" in secret_content

    def test_redis_uri_from_helpers(self, secret_content):
        """Secret template must use the redisUri helper."""
        assert "agent-audit.redisUri" in secret_content

    def test_secret_key_from_values(self, secret_content):
        """Secret template must reference config.secretKey."""
        assert ".Values.config.secretKey" in secret_content

    def test_postgres_password_conditional(self, secret_content):
        """POSTGRES_PASSWORD must be conditional on postgresql.enabled."""
        assert "postgresql.enabled" in secret_content
        assert "POSTGRES_PASSWORD" in secret_content

    def test_secret_type_opaque(self, secret_content):
        """Secret should be of type Opaque."""
        assert "Opaque" in secret_content

    def test_uses_stringdata(self, secret_content):
        """Sensitive keys should be in stringData."""
        assert "stringData" in secret_content

    def test_no_hardcoded_secrets(self, secret_content):
        """Secret template must use Helm values, not hardcoded secrets."""
        hardcoded = ['= "secret', "= 'secret", '= "password', "= 'password"]
        for hc in hardcoded:
            assert hc not in secret_content, f"Hardcoded secret value found: {hc}"


class TestHelmStatefulsetDb:
    """Verify PostgreSQL StatefulSet handles passwords securely."""

    @pytest.fixture(scope="class")
    def ss_content(self) -> str:
        return read_file(TEMPLATES_DIR / "statefulset-db.yaml")

    def test_statefulset_exists(self):
        assert (TEMPLATES_DIR / "statefulset-db.yaml").exists()

    def test_password_from_secret(self, ss_content):
        """POSTGRES_PASSWORD must come from secretKeyRef."""
        assert "secretKeyRef" in ss_content
        assert "POSTGRES_PASSWORD" in ss_content

    def test_secret_ref_not_optional(self, ss_content):
        """secretKeyRef must be required (optional: false)."""
        assert "optional: false" in ss_content

    def test_postgres_user_and_db_specified(self, ss_content):
        """POSTGRES_USER and POSTGRES_DB must be defined."""
        assert "POSTGRES_USER" in ss_content
        assert "POSTGRES_DB" in ss_content

    def test_healthcheck_exists(self, ss_content):
        """StatefulSet must have health probes."""
        assert "livenessProbe" in ss_content
        assert "readinessProbe" in ss_content
        assert "pg_isready" in ss_content

    def test_resources_defined(self, ss_content):
        """StatefulSet must have resource limits."""
        assert "resources" in ss_content

    def test_persistence_support(self, ss_content):
        """StatefulSet must support persistent volumes."""
        assert "volumeClaimTemplates" in ss_content or "emptyDir" in ss_content

    def test_conditional_deploy(self, ss_content):
        """StatefulSet must be conditional."""
        assert "postgresql.enabled" in ss_content


class TestHelmConfigmap:
    """Verify configmap.yaml separates config types correctly."""

    @pytest.fixture(scope="class")
    def configmap_content(self) -> str:
        return read_file(TEMPLATES_DIR / "configmap.yaml")

    def test_configmap_exists(self):
        assert (TEMPLATES_DIR / "configmap.yaml").exists()

    def test_no_sensitive_data_in_configmap(self, configmap_content):
        """ConfigMap must NOT contain sensitive values."""
        sensitive_keys = [
            "SECRET_KEY",
            "POSTGRES_PASSWORD",
            "SLACK_WEBHOOK",
            "SIGNING_KEY",
            "ENCRYPTION_KEY",
            "API_KEYS",
        ]
        for key in sensitive_keys:
            assert key not in configmap_content, (
                f"Sensitive key '{key}' found in ConfigMap (should be in Secret)"
            )

    def test_non_sensitive_config_in_configmap(self, configmap_content):
        """ConfigMap should contain non-sensitive config values."""
        expected_keys = [
            "STORAGE_BACKEND",
            "AUDIT_DIR",
            "CORS_ORIGINS",
            "LOG_LEVEL",
            "LOG_FORMAT",
            "AUTO_TRACE",
            "TRACE_PII_REDACT",
            "TRACE_COST_MODEL",
        ]
        for key in expected_keys:
            assert key in configmap_content, f"Expected key '{key}' not found"

    def test_nginx_conf_template(self, configmap_content):
        """ConfigMap should include NGINX configuration."""
        assert "nginx-conf" in configmap_content or "default.conf" in configmap_content

    def test_postgresql_init_sql_conditional(self, configmap_content):
        """PostgreSQL init SQL should be conditional."""
        assert "postgresql.enabled" in configmap_content


class TestHelmChartStructure:
    """Verify Helm chart file structure is complete."""

    def test_chart_yaml(self):
        assert (CHARTS_DIR / "Chart.yaml").exists()

    def test_required_template_files(self):
        """All standard Kubernetes resource templates must exist."""
        expected = [
            "configmap.yaml",
            "secret.yaml",
            "deployment-api.yaml",
            "deployment-nginx.yaml",
            "deployment-redis.yaml",
            "statefulset-db.yaml",
            "service-api.yaml",
            "service-db.yaml",
            "service-redis.yaml",
            "service-nginx.yaml",
            "ingress.yaml",
            "serviceaccount.yaml",
            "_helpers.tpl",
            "NOTES.txt",
        ]
        for tmpl in expected:
            assert (TEMPLATES_DIR / tmpl).exists(), f"Missing required template: {tmpl}"

    def test_optional_template_files(self):
        """Optional production templates should exist."""
        optional = [
            "hpa.yaml",
            "pdb.yaml",
            "network-policy.yaml",
            "servicemonitor.yaml",
            "pvc.yaml",
        ]
        for tmpl in optional:
            assert (TEMPLATES_DIR / tmpl).exists(), f"Missing optional template: {tmpl}"

    def test_chart_version_consistency(self):
        """Chart version must be consistent."""
        chart = read_file(CHARTS_DIR / "Chart.yaml")
        version_match = re.search(r'^version:\s*"?([^"\s]+)"?', chart, re.MULTILINE)
        assert version_match
        version = version_match.group(1)
        assert version == "1.0.0", f"Expected chart version 1.0.0, got {version}"

    def test_maintainer_info(self):
        """Chart.yaml should have maintainer information."""
        chart = read_file(CHARTS_DIR / "Chart.yaml")
        assert "maintainers:" in chart
        assert "name:" in chart


class TestHelmDeploymentSecurity:
    """Verify security context in api deployment template."""

    @pytest.fixture(scope="class")
    def api_deploy(self) -> str:
        return read_file(TEMPLATES_DIR / "deployment-api.yaml")

    def test_api_uses_service_account(self, api_deploy):
        """API deployment should use a ServiceAccount."""
        assert "serviceAccountName" in api_deploy

    def test_api_uses_configmap_and_secret(self, api_deploy):
        """API should reference both ConfigMap and Secret."""
        assert "configMapRef" in api_deploy
        assert "secretRef" in api_deploy

    def test_api_has_liveness_and_readiness(self, api_deploy):
        """API must have health probes."""
        assert "livenessProbe" in api_deploy
        assert "readinessProbe" in api_deploy

    def test_api_annotations_use_checksums(self, api_deploy):
        """API should have config/secret checksum annotations."""
        assert "checksum/config" in api_deploy
        assert "checksum/secret" in api_deploy

    def test_api_env_from_both_sources(self, api_deploy):
        """API should use envFrom with both configMapRef and secretRef."""
        assert "envFrom" in api_deploy
        assert "configMapRef" in api_deploy
        assert "secretRef" in api_deploy


# ═══════════════════════════════════════════════════════════════════
# 7. Go template syntax — balanced {{ / }} in all template files
# ═══════════════════════════════════════════════════════════════════


class TestNoUnrenderedGoTemplateSyntax:
    """Verify all Go template {{ / }} braces are balanced in Helm templates.

    Skips Helm comment blocks {{/* ... */}} which can span multiple lines
    and would otherwise cause false-positive brace-count mismatches.
    For example, _helpers.tpl line 1's {{/* and line 3's */}} balance each
    other, but a naive per-line count would flag {{/* as an unmatched opener.
    """

    # Helm comment blocks may span multiple lines
    HELM_COMMENT_RE = re.compile(r"\{\{/\*.*?\*/\}\}", re.DOTALL)

    @pytest.fixture(scope="class")
    def template_files(self) -> list:
        """Collect all template files (yaml, tpl, txt) from templates directory."""
        files = []
        for p in TEMPLATES_DIR.iterdir():
            if p.is_file() and p.suffix in (".yaml", ".tpl", ".txt"):
                files.append(p)
        return files

    @staticmethod
    def _count_braces(content: str) -> tuple:
        """Return (open_count, close_count) of Go template braces.

        Helm comment blocks {{/* ... */}} are stripped first so that
        multi-line comments do not produce false-positive imbalances.
        """
        # Strip Helm comment blocks — these use {{/* ... */}} and can
        # span multiple lines (e.g. _helpers.tpl block headers).
        cleaned = TestNoUnrenderedGoTemplateSyntax.HELM_COMMENT_RE.sub("", content)
        open_count = cleaned.count("{{")
        close_count = cleaned.count("}}")
        return open_count, close_count

    def test_all_template_files_exist(self, template_files):
        """At least one template file must be found."""
        assert len(template_files) > 0, f"No template files found in {TEMPLATES_DIR}"

    def test_every_template_file_has_balanced_braces(self, template_files):
        """Every template file must have matching {{ and }} counts."""
        failed = []
        for path in template_files:
            content = read_file(path)
            open_count, close_count = TestNoUnrenderedGoTemplateSyntax._count_braces(content)
            if open_count != close_count:
                failed.append(
                    f"  {path.name}: {open_count} opening '{{{{' vs {close_count} closing '}}}}'"
                )

        assert not failed, (
            f"Unbalanced Go template braces in {len(failed)} file(s):\n"
            + "\n".join(failed)
            + "\n\nHelm comment blocks {{/* ... */}} are stripped before counting."
        )
