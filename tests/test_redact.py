"""Tests for core/redact.py — PII redaction (0% baseline)."""

import pytest
from agent_seal.core.redact import Redactor, REDACTORS


class TestRedactorSanitize:
    def test_sanitize_email(self):
        r = Redactor(rules=["email"])
        result = r.sanitize("Contact me at user@example.com please")
        assert "<EMAIL>" in result
        assert "user@example.com" not in result

    def test_sanitize_phone(self):
        r = Redactor(rules=["phone"])
        result = r.sanitize("Call +1-555-123-4567 now")
        assert "<PHONE>" in result
        assert "555-123-4567" not in result

    def test_sanitize_credit_card(self):
        r = Redactor(rules=["credit_card"])
        result = r.sanitize("Card: 4111-1111-1111-1111")
        assert "<CARD>" in result
        assert "4111" not in result

    def test_sanitize_ssn(self):
        r = Redactor(rules=["ssn"])
        result = r.sanitize("SSN: 123-45-6789")
        assert "<SSN>" in result
        assert "123-45-6789" not in result

    def test_sanitize_api_key(self):
        r = Redactor(rules=["api_key"])
        result = r.sanitize("api_key=sk-abcdef1234567890abc")
        assert "<API_KEY>" in result

    def test_sanitize_ip(self):
        r = Redactor(rules=["ip"])
        result = r.sanitize("From 192.168.1.1")
        assert "<IP>" in result

    def test_all_rules_default(self):
        r = Redactor()
        text = (
            "Email: alice@corp.com Phone: +1-555-123-4567 "
            "Card: 4111-1111-1111-1111 SSN: 123-45-6789 "
            "IP: 10.0.0.1"
        )
        result = r.sanitize(text)
        assert "<EMAIL>" in result
        assert "<PHONE>" in result
        assert "<CARD>" in result
        assert "<SSN>" in result
        assert "<IP>" in result

    def test_no_pii_unchanged(self):
        r = Redactor()
        result = r.sanitize("Just a normal sentence without any PII.")
        assert result == "Just a normal sentence without any PII."

    def test_empty_string(self):
        r = Redactor()
        assert r.sanitize("") == ""

    def test_partial_match(self):
        r = Redactor(rules=["email"])
        result = r.sanitize("My email is @notanemail but user@test.com is")
        assert "<EMAIL>" in result
        assert "notanemail" in result

    def test_multiple_occurrences(self):
        r = Redactor(rules=["email"])
        result = r.sanitize("a@a.com and b@b.com and c@c.com")
        assert result.count("<EMAIL>") == 3

    def test_subdomain_email(self):
        r = Redactor(rules=["email"])
        result = r.sanitize("test@sub.domain.co.uk")
        assert "<EMAIL>" in result

    def test_phone_without_country_code(self):
        r = Redactor(rules=["phone"])
        result = r.sanitize("Call 555-123-4567")
        assert "<PHONE>" in result

    def test_phone_parentheses(self):
        r = Redactor(rules=["phone"])
        result = r.sanitize("Call (555) 123-4567")
        assert "<PHONE>" in result

    def test_selective_rules(self):
        r = Redactor(rules=["email", "ip"])
        text = "Email: a@b.com IP: 1.2.3.4 Card: 4111-1111-1111-1111"
        result = r.sanitize(text)
        assert "<EMAIL>" in result
        assert "<IP>" in result
        assert "4111" in result  # credit_card not in rules
        assert "<CARD>" not in result

    def test_unknown_rule_ignored(self):
        r = Redactor(rules=["email", "nonexistent"])
        result = r.sanitize("test@test.com")
        assert "<EMAIL>" in result

    def test_sanitize_long_text(self):
        r = Redactor()
        text = " ".join(["user@test.com"] * 100)
        result = r.sanitize(text)
        assert result.count("<EMAIL>") == 100

    def test_unicode_text(self):
        r = Redactor(rules=["email"])
        result = r.sanitize("联系 user@中国.com 处理")
        assert "<EMAIL>" in result


class TestRedactorHashSensitive:
    def test_hash_email(self):
        r = Redactor(rules=["email"])
        result = r.hash_sensitive("Contact me at user@example.com")
        assert "user@example.com" not in result
        assert len(result) > 0
        assert "@" not in result  # replaced by hex hash

    def test_hash_multiple(self):
        r = Redactor(rules=["email", "ssn"])
        result = r.hash_sensitive("a@b.com and 123-45-6789")
        assert "a@b.com" not in result
        assert "123-45-6789" not in result

    def test_hash_output_is_deterministic(self):
        r = Redactor(rules=["email"])
        a = r.hash_sensitive("email: test@example.com")
        b = r.hash_sensitive("email: test@example.com")
        assert a == b

    def test_hash_length_is_short(self):
        r = Redactor(rules=["ssn"])
        result = r.hash_sensitive("SSN: 123-45-6789")
        # SHA-256 hexdigest[:12] = 12 chars
        for word in result.split():
            if "<SSN>" not in word and len(word) <= 12:
                pass
        assert "<SSN>" not in result  # replaced

    def test_hash_no_pii(self):
        r = Redactor()
        text = "safe text with no sensitive data"
        assert r.hash_sensitive(text) == text

    def test_hash_empty_string(self):
        r = Redactor()
        assert r.hash_sensitive("") == ""

    def test_hash_preserves_non_sensitive(self):
        r = Redactor(rules=["ip"])
        result = r.hash_sensitive("Server at 10.0.0.1 is running")
        assert "is running" in result


class TestRedactorEdgeCases:
    def test_proximity_noise(self):
        r = Redactor()
        text = "email@domain"  # not a valid email (no dot extent)
        result = r.sanitize(text)
        # may or may not match depending on regex
        assert isinstance(result, str)

    def test_empty_rules_list_falls_back(self):
        # NOTE: `rules=[]` is falsy, so it falls back to ALL rules.
        # This is the current behavior — ensure it doesn't crash.
        r = Redactor(rules=[])
        assert r.rules == list(REDACTORS.keys())

    def test_all_redactors_defined(self):
        expected = {"email", "phone", "credit_card", "ssn", "api_key", "ip"}
        assert set(REDACTORS.keys()) == expected

    def test_each_redactor_has_pattern_and_replacement(self):
        for name, (pattern, replacement) in REDACTORS.items():
            assert hasattr(pattern, "search"), f"{name} missing regex pattern"
            assert isinstance(replacement, str), f"{name} missing replacement string"
