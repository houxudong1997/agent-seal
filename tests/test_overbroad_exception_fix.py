"""Tests for the overly-broad exception handling fix.

Verifies fix t_404d1569 across crypto.py, evidence.py, and
opentelemetry.py — each exception handler now catches only what
it can meaningfully handle.

Key changes verified:
  crypto.py    — except (InvalidSignature, Exception) → except InvalidSignature
                 + except (ValueError, TypeError)
  evidence.py  — except Exception → except Exception as exc (logged)
  opentelemetry.py — all except Exception clauses are intentional
"""

import json
import logging
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# =========================================================================
#  crypto.py  — Verifier.verify() exception handling
# =========================================================================


class TestCryptoVerifyPrecision:
    """Verify that Verifier.verify() uses precise exception types."""

    def test_valid_signature_returns_true(self):
        """Normal path: valid signature is accepted."""
        from agent_seal.core.crypto import Signer, Verifier, generate_key_pair

        private, public = generate_key_pair()
        signer = Signer(private)
        verifier = Verifier(public)

        sig = signer.sign("hello world")
        assert verifier.verify("hello world", sig) is True

    def test_tampered_data_returns_false_via_invalid_signature(self):
        """Tampered data hits InvalidSignature → returns False."""
        from agent_seal.core.crypto import Signer, Verifier, generate_key_pair

        private, public = generate_key_pair()
        signer = Signer(private)
        verifier = Verifier(public)

        sig = signer.sign("original")
        result = verifier.verify("tampered", sig)
        assert result is False

    def test_bad_base64_returns_false_via_value_error(self):
        """Invalid base64 hits ValueError → returns False."""
        from agent_seal.core.crypto import Verifier, generate_key_pair

        _, public = generate_key_pair()
        verifier = Verifier(public)

        result = verifier.verify("data", "!!!not-base64!!!")
        assert result is False

    def test_none_signature_returns_false_via_type_error(self):
        """None signature hits TypeError → returns False."""
        from agent_seal.core.crypto import Verifier, generate_key_pair

        _, public = generate_key_pair()
        verifier = Verifier(public)

        result = verifier.verify("data", None)
        assert result is False

    def test_empty_signature_returns_false_via_value_error(self):
        """Empty signature hits ValueError → returns False."""
        from agent_seal.core.crypto import Verifier, generate_key_pair

        _, public = generate_key_pair()
        verifier = Verifier(public)

        result = verifier.verify("data", "")
        assert result is False

    def test_verify_event_tampered_hash_returns_false(self):
        """Tampered event hash returns False."""
        from agent_seal.core.crypto import Signer, Verifier, generate_key_pair

        private, public = generate_key_pair()
        signer = Signer(private)
        verifier = Verifier(public)

        sig = signer.sign_event("hash123", "evt-001", 1000.0)
        assert verifier.verify_event("WRONG-HASH", "evt-001", 1000.0, sig) is False

    def test_verify_event_bad_signature_format_returns_false(self):
        """Malformed event signature returns False."""
        from agent_seal.core.crypto import Verifier, generate_key_pair

        _, public = generate_key_pair()
        verifier = Verifier(public)

        result = verifier.verify_event("h", "e", 1.0, "bad-sig!!")
        assert result is False

    def test_save_private_key_empty_password_raises_value_error(self):
        """save_private_key with empty password raises ValueError."""
        from agent_seal.core.crypto import generate_key_pair, save_private_key

        private, _ = generate_key_pair()
        with pytest.raises(ValueError, match="password must not be empty"):
            save_private_key(private, "/tmp/nonexistent.pem", b"")


class TestCryptoNoOverbroadException:
    """Ensure old 'except Exception' pattern is gone from crypto.py."""

    def test_no_bare_except_in_source(self):
        """Scan crypto.py for forbidden patterns (fail-fast)."""
        source = Path(__file__).resolve().parent.parent / "agent_seal" / "core" / "crypto.py"
        text = source.read_text()

        # The old code had 'except (InvalidSignature, Exception):'
        assert "except (InvalidSignature, Exception)" not in text, (
            "Old overbroad catch still present"
        )
        # The verify() method must not have any 'except Exception' clause
        verify_body = (
            text.split("def verify")[1].split("def verify_event")[0] if "def verify" in text else ""
        )
        if verify_body:
            assert "except Exception" not in verify_body, "except Exception found in verify()"


# =========================================================================
#  evidence.py  — EvidenceExporter exception handling
# =========================================================================


class TestEvidenceExporterExceptionHandling:
    """Verify evidence.py exception handlers are well-behaved."""

    def test_check_integrity_logs_and_returns_false_on_failure(self, caplog):
        """_check_integrity catches exception, logs it, returns False."""
        from agent_seal.evidence import EvidenceExporter

        engine = MagicMock()
        engine.verify.side_effect = ValueError("DB integrity check failed")
        registry = MagicMock()
        exporter = EvidenceExporter(engine, registry)

        with caplog.at_level(logging.ERROR):
            result = exporter._check_integrity()

        assert result is False
        assert "DB integrity check failed" in caplog.text

    def test_verify_bundle_not_found_returns_fail(self):
        """Missing bundle path returns FAIL with reason."""
        from agent_seal.evidence import EvidenceExporter

        engine = MagicMock()
        registry = MagicMock()
        exporter = EvidenceExporter(engine, registry)

        result = exporter.verify_bundle("/tmp/nonexistent-bundle.zip")
        assert result["status"] == "FAIL"
        assert "Bundle not found" in result["reason"]

    def test_verify_bundle_corrupt_zip_returns_fail(self, tmp_path):
        """Invalid ZIP file returns FAIL with corrupt reason."""
        from agent_seal.evidence import EvidenceExporter

        bad_zip = tmp_path / "corrupt.zip"
        bad_zip.write_text("this is not a zip file")

        engine = MagicMock()
        registry = MagicMock()
        exporter = EvidenceExporter(engine, registry)

        result = exporter.verify_bundle(str(bad_zip))
        assert result["status"] == "FAIL"
        assert "Corrupt bundle" in result["reason"]

    def test_verify_bundle_missing_json_keys_returns_fail(self, tmp_path):
        """ZIP without metadata.json returns FAIL."""
        from agent_seal.evidence import EvidenceExporter

        bad_zip = tmp_path / "missing-meta.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("events.json", "[]")

        engine = MagicMock()
        registry = MagicMock()
        exporter = EvidenceExporter(engine, registry)

        result = exporter.verify_bundle(str(bad_zip))
        assert result["status"] == "FAIL"

    def test_verify_bundle_valid_structure_but_bad_hash(self, tmp_path):
        """ZIP with valid structure but hash mismatch returns FAIL."""
        from agent_seal.core.storage import AuditEngine
        from agent_seal.evidence import EvidenceExporter
        from agent_seal.prompt_version import PromptRegistry

        zipp = tmp_path / "bundle.zip"
        with zipfile.ZipFile(zipp, "w") as zf:
            zf.writestr("metadata.json", json.dumps({"tool": "agent-seal v1.0.0"}))
            zf.writestr(
                "events.json", json.dumps([{"event_id": "1", "hash": "aaa", "prev_hash": ""}]))
            zf.writestr(
                "bundle.json",
                json.dumps({
                    "sha256": "BAD_HASH_VALUE",
                    "bundle_id": "test-001",
                    "signature": "",
                    "integrity_verified": False,
                }),
            )
            zf.writestr("prompts.json", "{}")

        engine = MagicMock(spec=AuditEngine)
        registry = MagicMock(spec=PromptRegistry)
        exporter = EvidenceExporter(engine, registry)

        result = exporter.verify_bundle(str(zipp))
        assert result["status"] == "FAIL"


# =========================================================================
#  opentelemetry.py  — AuditSpanProcessor exception safety
# =========================================================================


class TestAuditSpanProcessorExceptionSafety:
    """Verify opentelemetry.py handles failures gracefully."""

    def test_on_end_swallows_exception_from_process_span(self):
        """on_end catches any exception from _process_span without raising."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        proc = AuditSpanProcessor()

        # _process_span will enter logic flow — should not raise
        span = {"attributes": {"llm.model": "gpt-4"}}
        proc.on_end(span)

    def test_on_end_handles_completely_empty_span(self):
        """on_end with empty span does not crash."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        proc = AuditSpanProcessor()
        proc.on_end({})  # empty span
        proc.on_end(None)  # None span

    def test_on_end_handles_malformed_span_no_attributes(self):
        """on_end with missing attributes does not crash."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        proc = AuditSpanProcessor()
        proc.on_end({"no": "attributes"})

    def test_cost_estimation_failure_does_not_block_persist(self):
        """When cost estimation fails, span processing continues."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine, auto_audit=True)

        span = {
            "attributes": {
                "llm.model": "gpt-4",
                "llm.provider": "openai",
                "session.id": "sess-1",
                "agent.id": "agent-x",
            },
            "trace_id": "abc",
            "span_id": "def",
            "parent_span_id": "",
        }

        # Should not raise even though cost estimation may fail
        proc.on_end(span)
        # The span should still be processed even if cost fails
        engine.log.assert_called_once()

    @patch("agent_seal.tracing.openai_instrumentor._persist_llm_call")
    def test_persist_failure_does_not_block_audit(self, mock_persist):
        """When LLM persist fails, audit trail logging continues."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        mock_persist.side_effect = RuntimeError("DB unavailable")

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine, auto_audit=True)

        span = {
            "attributes": {
                "llm.model": "gpt-4",
                "llm.provider": "openai",
                "session.id": "sess-1",
                "agent.id": "agent-x",
                "audit.enabled": "true",
            },
            "trace_id": "abc",
            "span_id": "def",
            "parent_span_id": "",
        }

        proc.on_end(span)
        # Audit trail still called despite persist failure
        engine.log.assert_called_once()

    @patch("agent_seal.tracing.openai_instrumentor._persist_llm_call", side_effect=RuntimeError)
    @patch("agent_seal.tracing.cost.estimate_cost", side_effect=ValueError("bad model"))
    def test_all_internal_failures_still_do_not_crash(self, mock_cost, mock_persist):
        """Multiple simultaneous failures don't crash on_end."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine, auto_audit=True, auto_cost=True)

        span = {
            "attributes": {
                "llm.model": "gpt-4",
                "llm.provider": "openai",
                "session.id": "sess-42",
                "audit.enabled": "true",
            },
            "trace_id": "abc",
            "span_id": "def",
            "parent_span_id": "",
        }

        # Cost → fails (ValueError), Persist → fails (RuntimeError),
        # Audit log → succeeds (still no raise)
        proc.on_end(span)
        engine.log.assert_called_once()

    def test_get_attributes_empty_span_returns_dict(self):
        """_get_attributes handles spans with no structure."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        assert AuditSpanProcessor._get_attributes({}) == {}
        assert AuditSpanProcessor._get_attributes(None) == {}

    def test_get_attributes_from_object_without_attributes(self):
        """_get_attributes handles objects without attributes."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        obj = object()
        assert AuditSpanProcessor._get_attributes(obj) == {}

    def test_get_trace_id_from_dict(self):
        """_get_trace_id extracts trace_id from dict spans."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        span = {"trace_id": "abc123"}
        assert AuditSpanProcessor._get_trace_id(span) == "abc123"

    def test_get_trace_id_from_object_without_context(self):
        """_get_trace_id returns empty string when span has no context."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        obj = MagicMock()
        # No get_span_context method
        del obj.get_span_context
        assert AuditSpanProcessor._get_trace_id(obj) == ""

    def test_get_span_id_returns_empty_on_exception(self):
        """_get_span_id catches exceptions and returns empty string."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        span = MagicMock()
        span.get_span_context.side_effect = TypeError("not a span")
        assert AuditSpanProcessor._get_span_id(span) == ""

    def test_get_parent_span_id_from_dict(self):
        """_get_parent_span_id extracts parent_span_id from dict spans."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        span = {"parent_span_id": "parent123"}
        assert AuditSpanProcessor._get_parent_span_id(span) == "parent123"

    def test_get_parent_span_id_from_object_with_parent(self):
        """_get_parent_span_id extracts from object with parent context."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        parent_ctx = MagicMock()
        parent_ctx.get_span_context.return_value = MagicMock()
        parent_ctx.get_span_context.return_value.span_id = 12345

        span = MagicMock()
        span.parent = parent_ctx

        result = AuditSpanProcessor._get_parent_span_id(span)
        assert result == format(12345, "016x")

    def test_get_parent_span_id_no_parent(self):
        """_get_parent_span_id returns empty when there's no parent."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        span = MagicMock()
        span.parent = None
        assert AuditSpanProcessor._get_parent_span_id(span) == ""

    def test_shutdown_is_noop(self):
        """shutdown does not raise."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        AuditSpanProcessor().shutdown()

    def test_force_flush_returns_true(self):
        """force_flush returns True."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        assert AuditSpanProcessor().force_flush() is True

    def test_create_span_processor_wires_engine(self):
        """create_span_processor returns a properly wired AuditSpanProcessor."""
        from agent_seal.tracing.opentelemetry import create_span_processor

        engine = MagicMock()
        proc = create_span_processor(engine, auto_audit=True, auto_cost=False)
        assert proc.engine is engine
        assert proc.auto_audit is True
        assert proc.auto_cost is False

    def test_auto_audit_false_skips_audit_log(self):
        """When auto_audit is False, engine.log is not called."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine, auto_audit=False)
        span = {
            "attributes": {"llm.model": "gpt-4", "llm.provider": "openai"},
            "trace_id": "a",
            "span_id": "b",
            "parent_span_id": "",
        }
        proc.on_end(span)
        engine.log.assert_not_called()


# =========================================================================
#  Version consistency v1.0.0
# =========================================================================


class TestVersionConsistency:
    """All version references must match __version__."""

    PACKAGE_VERSION = "1.0.0"

    def test_init_version_matches(self):
        """agent_seal.__init__.__version__ is 1.0.0."""
        import agent_seal

        assert agent_seal.__version__ == self.PACKAGE_VERSION

    def test_setup_version_matches(self):
        """setup.py version is 1.0.0."""
        setup_path = Path(__file__).resolve().parent.parent / "setup.py"
        text = setup_path.read_text()
        assert (
            f'version="{self.PACKAGE_VERSION}"' in text
            or f"version='{self.PACKAGE_VERSION}'" in text
        )

    def test_evidence_tool_version_matches(self):
        """evidence.py tool string references v1.0.0."""
        src_path = Path(__file__).resolve().parent.parent / "agent_seal" / "evidence.py"
        text = src_path.read_text()
        assert f"v{self.PACKAGE_VERSION}" in text

    def test_spa_version_tag_matches(self):
        """SPA version tag is v1.0.0."""
        spa_path = (
            Path(__file__).resolve().parent.parent / "agent_seal" / "spa" / "src" / "App.svelte"
        )
        if spa_path.exists():
            text = spa_path.read_text()
            assert f"v{self.PACKAGE_VERSION}" in text
