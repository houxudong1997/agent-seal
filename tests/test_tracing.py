"""
Tests for agent-audit tracing module — OpenAI Instrumentor, OTel bridging,
cost estimation, and auto-tracing entry point.

Coverage targets:
  - TraceConfig defaults and env-var overrides
  - Cost estimation: exact matches, prefix fallback, unknown models
  - OpenAIInstrumentor install / uninstall lifecycle
  - _trace_call logic: span creation, telemetry extraction, error paths
  - AuditSpanProcessor: span attribute extraction, audit disable flag
  - auto.install_auto_tracing() activation
  - Graceful degradation: no openai installed, no opentelemetry, no DB
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. TraceConfig
# ---------------------------------------------------------------------------


class TestTraceConfig:
    """TraceConfig should read defaults from the app-level Config."""

    def test_default_values(self):
        from agent_audit.tracing.config import TraceConfig

        cfg = TraceConfig()
        assert cfg.auto_audit is False
        assert cfg.auto_cost is True
        assert cfg.pii_redact is False
        assert cfg.max_prompt_len == 4000
        assert cfg.cost_model == "openai"
        assert cfg.span_prefix == "llm"
        assert cfg.capture_request is True
        assert cfg.capture_response is True

    def test_override_at_construction(self):
        from agent_audit.tracing.config import TraceConfig

        cfg = TraceConfig(
            auto_audit=True,
            auto_cost=False,
            pii_redact=True,
            max_prompt_len=8000,
            cost_model="anthropic",
            span_prefix="ai",
            capture_request=False,
            capture_response=False,
        )
        assert cfg.auto_audit is True
        assert cfg.auto_cost is False
        assert cfg.pii_redact is True
        assert cfg.max_prompt_len == 8000
        assert cfg.cost_model == "anthropic"
        assert cfg.span_prefix == "ai"
        assert cfg.capture_request is False
        assert cfg.capture_response is False

    def test_env_var_respected(self):
        """When AGENT_AUDIT_AUTO_TRACE=1, TraceConfig.auto_audit is True."""
        saved = {}
        for k in (
            "AGENT_AUDIT_AUTO_TRACE",
            "AGENT_AUDIT_TRACE_PII_REDACT",
            "AGENT_AUDIT_TRACE_MAX_LEN",
            "AGENT_AUDIT_TRACE_COST_MODEL",
        ):
            saved[k] = os.environ.pop(k, None)

        os.environ["AGENT_AUDIT_AUTO_TRACE"] = "1"
        os.environ["AGENT_AUDIT_TRACE_PII_REDACT"] = "true"
        os.environ["AGENT_AUDIT_TRACE_MAX_LEN"] = "2000"
        os.environ["AGENT_AUDIT_TRACE_COST_MODEL"] = "deepseek"
        try:
            from agent_audit.tracing.config import TraceConfig

            cfg = TraceConfig()
            assert cfg.auto_audit is True
            assert cfg.pii_redact is True
            assert cfg.max_prompt_len == 2000
            assert cfg.cost_model == "deepseek"
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# 2. Cost estimation
# ---------------------------------------------------------------------------


class TestCostEstimation:
    """Pricing lookups with exact match and prefix fallback."""

    def test_openai_exact_match(self):
        from agent_audit.tracing.cost import estimate_openai_cost

        cost = estimate_openai_cost("gpt-4o", 1000, 500)
        expected = Decimal("0.002500") + Decimal("0.005000")
        assert cost == expected.quantize(Decimal("0.000001"))

    def test_openai_prefix_fallback(self):
        from agent_audit.tracing.cost import estimate_openai_cost

        cost = estimate_openai_cost("gpt-4o-2024-08-06", 1_000_000, 0)
        assert cost == Decimal("2.50")

    def test_openai_unknown_model(self):
        from agent_audit.tracing.cost import estimate_openai_cost

        cost = estimate_openai_cost("nonexistent-model-v99", 1_000_000, 1_000_000)
        assert cost == Decimal("0")

    def test_anthropic_model(self):
        from agent_audit.tracing.cost import estimate_anthropic_cost

        cost = estimate_anthropic_cost("claude-sonnet-4", 1_000_000, 1_000_000)
        assert cost == Decimal("18.000000")

    def test_deepseek_model(self):
        from agent_audit.tracing.cost import estimate_deepseek_cost

        cost = estimate_deepseek_cost("deepseek-v3", 1_000_000, 1_000_000)
        assert cost == Decimal("0.420000")

    def test_estimate_cost_dispatcher(self):
        from agent_audit.tracing.cost import estimate_cost

        c1 = estimate_cost("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
        assert c1 == Decimal("0.750000")

        c2 = estimate_cost("anthropic", "claude-haiku-3", 1_000_000, 1_000_000)
        assert c2 == Decimal("1.500000")

        c3 = estimate_cost("deepseek", "deepseek-r1", 1_000_000, 1_000_000)
        assert c3 == Decimal("2.740000")

    def test_unknown_provider_returns_zero(self):
        from agent_audit.tracing.cost import estimate_cost

        c = estimate_cost("unknown-provider", "gpt-5", 1_000_000, 1_000_000)
        assert c == Decimal("0")


# ---------------------------------------------------------------------------
# 3. OpenAIInstrumentor — lifecycle
# ---------------------------------------------------------------------------


class TestOpenAIInstrumentor:
    """Install / uninstall cycle."""

    def test_install_idempotent(self):
        from agent_audit.tracing.openai_instrumentor import OpenAIInstrumentor

        instr = OpenAIInstrumentor()
        instr._installed = True
        instr.install()
        assert instr._installed is True

    def test_install_no_openai_package(self):
        """When openai is not importable, install() is graceful no-op."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "openai" or name.startswith("openai."):
                raise ImportError("No module named 'openai'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            from agent_audit.tracing.openai_instrumentor import OpenAIInstrumentor

            instr = OpenAIInstrumentor()
            instr.install()
            assert instr._installed is False

    def test_uninstall_restores_original(self):
        mock_openai = MagicMock()
        mock_openai.chat.completions.create = MagicMock(return_value="original")
        original = mock_openai.chat.completions.create

        with patch.dict(sys.modules, {"openai": mock_openai}):
            from agent_audit.tracing.openai_instrumentor import OpenAIInstrumentor

            instr = OpenAIInstrumentor()
            mock_openai.chat.completions.create = MagicMock(return_value="patched")
            instr._original_create = original
            instr._installed = True

            instr.uninstall()

            assert mock_openai.chat.completions.create is original
            assert instr._installed is False
            assert instr._original_create is None

    def test_uninstall_not_installed_noop(self):
        from agent_audit.tracing.openai_instrumentor import OpenAIInstrumentor

        instr = OpenAIInstrumentor()
        instr.uninstall()
        assert instr._installed is False


# ---------------------------------------------------------------------------
# 3b. AnthropicInstrumentor — lifecycle
# ---------------------------------------------------------------------------


class TestAnthropicInstrumentor:
    """Install / uninstall cycle for Anthropic instrumentor."""

    def test_install_idempotent(self):
        from agent_audit.tracing.anthropic import AnthropicInstrumentor

        instr = AnthropicInstrumentor()
        instr._installed = True
        instr.install()
        assert instr._installed is True

    def test_install_no_anthropic_package(self):
        """When anthropic is not importable, install() is graceful no-op."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "anthropic" or name.startswith("anthropic."):
                raise ImportError("No module named 'anthropic'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            from agent_audit.tracing.anthropic import AnthropicInstrumentor

            instr = AnthropicInstrumentor()
            instr.install()
            assert instr._installed is False

    def test_uninstall_restores_original(self):
        mock_anthropic = MagicMock()
        mock_anthropic.messages.create = MagicMock(return_value="original")
        original = mock_anthropic.messages.create

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            from agent_audit.tracing.anthropic import AnthropicInstrumentor

            instr = AnthropicInstrumentor()
            mock_anthropic.messages.create = MagicMock(return_value="patched")
            instr._original_create = original
            instr._installed = True

            instr.uninstall()

            assert mock_anthropic.messages.create is original
            assert instr._installed is False
            assert instr._original_create is None

    def test_uninstall_not_installed_noop(self):
        from agent_audit.tracing.anthropic import AnthropicInstrumentor

        instr = AnthropicInstrumentor()
        instr.uninstall()
        assert instr._installed is False


# ---------------------------------------------------------------------------
# 4. _trace_call core logic
# ---------------------------------------------------------------------------


class TestTraceCall:
    """Test _trace_call in isolation."""

    def test_successful_call_returns_result(self):
        from agent_audit.tracing.config import TraceConfig
        from agent_audit.tracing.openai_instrumentor import _trace_call

        original = MagicMock(return_value="fake-result")
        config = TraceConfig(auto_audit=False)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            config=config,
            engine=None,
            tracer=None,
            db_available=False,
        )

        assert result == "fake-result"
        original.assert_called_once()

    def test_error_propagates(self):
        from agent_audit.tracing.config import TraceConfig
        from agent_audit.tracing.openai_instrumentor import _trace_call

        original = MagicMock(side_effect=RuntimeError("API error"))
        config = TraceConfig(auto_audit=False)

        with pytest.raises(RuntimeError, match="API error"):
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=None,
                db_available=False,
            )

    def test_error_writes_nothing_to_audit(self):
        from agent_audit.tracing.config import TraceConfig
        from agent_audit.tracing.openai_instrumentor import _trace_call

        original = MagicMock(side_effect=ValueError("boom"))
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        with pytest.raises(ValueError, match="boom"):
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]},
                config=config,
                engine=engine,
                tracer=None,
                db_available=False,
            )

        engine.log.assert_not_called()

    def test_audit_trail_called_when_enabled(self):
        from agent_audit.tracing.config import TraceConfig
        from agent_audit.tracing.openai_instrumentor import _trace_call

        result = MagicMock()
        result.model = "gpt-4o"
        result.usage = MagicMock()
        result.usage.prompt_tokens = 10
        result.usage.completion_tokens = 20
        result.usage.total_tokens = 30
        result.choices = [MagicMock()]
        result.choices[0].message.content = "Hello back"
        result.model_dump = MagicMock(
            return_value={"choices": [{"message": {"content": "Hello back"}}]}
        )

        original = MagicMock(return_value=result)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_call(
            original=original,
            args=(),
            kwargs={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hello"}],
                "audit_session_id": "sess-001",
                "audit_agent_id": "agent-7",
            },
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        engine.log.assert_called_once()
        call_kwargs = engine.log.call_args.kwargs
        assert call_kwargs["session_id"] == "sess-001"
        assert call_kwargs["event_type"] == "model_request"
        assert call_kwargs["agent_id"] == "agent-7"
        assert call_kwargs["metadata"]["model"] == "gpt-4o"
        assert call_kwargs["metadata"]["tokens"] == 30


# ---------------------------------------------------------------------------
# 4b. Anthropic _trace_anthropic_call core logic
# ---------------------------------------------------------------------------


class TestAnthropicTraceCall:
    """Test _trace_anthropic_call in isolation."""

    def test_successful_call_returns_result(self):
        from agent_audit.tracing.anthropic import _trace_anthropic_call
        from agent_audit.tracing.config import TraceConfig

        original = MagicMock(return_value="fake-result")
        config = TraceConfig(auto_audit=False)

        result = _trace_anthropic_call(
            original=original,
            args=(),
            kwargs={"model": "claude-sonnet-4", "messages": [{"role": "user", "content": "hi"}]},
            config=config,
            engine=None,
            tracer=None,
            db_available=False,
        )

        assert result == "fake-result"
        original.assert_called_once()

    def test_error_propagates(self):
        from agent_audit.tracing.anthropic import _trace_anthropic_call
        from agent_audit.tracing.config import TraceConfig

        original = MagicMock(side_effect=RuntimeError("Anthropic API error"))
        config = TraceConfig(auto_audit=False)

        with pytest.raises(RuntimeError, match="Anthropic API error"):
            _trace_anthropic_call(
                original=original,
                args=(),
                kwargs={"model": "claude-sonnet-4", "messages": []},
                config=config,
                engine=None,
                tracer=None,
                db_available=False,
            )

    def test_error_writes_nothing_to_audit(self):
        from agent_audit.tracing.anthropic import _trace_anthropic_call
        from agent_audit.tracing.config import TraceConfig

        original = MagicMock(side_effect=ValueError("boom"))
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        with pytest.raises(ValueError, match="boom"):
            _trace_anthropic_call(
                original=original,
                args=(),
                kwargs={"model": "claude-haiku-3", "messages": [{"role": "user", "content": "x"}]},
                config=config,
                engine=engine,
                tracer=None,
                db_available=False,
            )

        engine.log.assert_not_called()

    def test_audit_trail_called_when_enabled(self):
        from agent_audit.tracing.anthropic import _trace_anthropic_call
        from agent_audit.tracing.config import TraceConfig

        # Anthropic response uses content blocks (TextBlock objects)
        content_block = MagicMock()
        content_block.text = "Hello back from Claude"

        result = MagicMock()
        result.model = "claude-sonnet-4"
        result.usage = MagicMock()
        result.usage.input_tokens = 10
        result.usage.output_tokens = 20
        result.content = [content_block]
        result.model_dump = MagicMock(
            return_value={"content": [{"type": "text", "text": "Hello back from Claude"}]}
        )

        original = MagicMock(return_value=result)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_anthropic_call(
            original=original,
            args=(),
            kwargs={
                "model": "claude-sonnet-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "audit_session_id": "sess-001",
                "audit_agent_id": "agent-7",
            },
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        engine.log.assert_called_once()
        call_kwargs = engine.log.call_args.kwargs
        assert call_kwargs["session_id"] == "sess-001"
        assert call_kwargs["event_type"] == "model_request"
        assert call_kwargs["agent_id"] == "agent-7"
        assert call_kwargs["metadata"]["model"] == "claude-sonnet-4"
        assert call_kwargs["metadata"]["tokens"] == 30
        assert call_kwargs["output_text"] == "Hello back from Claude"

    def test_extract_content_text_from_blocks(self):
        from agent_audit.tracing.anthropic import _extract_content_text

        # TextBlock object
        block = MagicMock()
        block.text = "Response text"
        assert _extract_content_text([block]) == "Response text"

        # dict content
        assert _extract_content_text([{"type": "text", "text": "Dict text"}]) == "Dict text"

        # empty list
        assert _extract_content_text([]) == ""

        # None
        assert _extract_content_text(None) == ""

        # string (direct)
        assert _extract_content_text("plain string") == "plain string"


# ---------------------------------------------------------------------------
# 5. AuditSpanProcessor
# ---------------------------------------------------------------------------


class TestAuditSpanProcessor:
    """SpanProcessor bridge."""

    def test_ignores_non_llm_span(self):
        from agent_audit.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine)

        span = {"attributes": {"http.method": "GET"}}
        proc.on_end(span)

        engine.log.assert_not_called()

    def test_processes_llm_span(self):
        from agent_audit.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine, auto_audit=True)

        span = {
            "attributes": {
                "llm.model": "gpt-4o",
                "llm.provider": "openai",
                "llm.request_tokens": 100,
                "llm.response_tokens": 200,
                "llm.total_tokens": 300,
                "llm.latency_ms": 1500,
                "session.id": "sess-42",
                "agent.id": "agent-x",
                "audit.enabled": "true",
            },
            "trace_id": "abc123",
            "span_id": "def456",
            "parent_span_id": "",
        }

        proc.on_end(span)

        engine.log.assert_called_once()
        call_kwargs = engine.log.call_args.kwargs
        assert call_kwargs["session_id"] == "sess-42"
        assert call_kwargs["agent_id"] == "agent-x"

    def test_audit_disabled_flag_skips_log(self):
        from agent_audit.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine, auto_audit=True)

        span = {
            "attributes": {
                "llm.model": "gpt-4o",
                "audit.enabled": "false",
            },
            "trace_id": "x",
            "span_id": "y",
            "parent_span_id": "",
        }

        proc.on_end(span)
        engine.log.assert_not_called()

    def test_attributes_extraction_from_dict(self):
        from agent_audit.tracing.opentelemetry import AuditSpanProcessor

        span = {"attributes": {"key": "val"}}
        attrs = AuditSpanProcessor._get_attributes(span)
        assert attrs == {"key": "val"}

    def test_attributes_extraction_from_object(self):
        from agent_audit.tracing.opentelemetry import AuditSpanProcessor

        span = MagicMock()
        span.attributes = {"foo": "bar"}
        attrs = AuditSpanProcessor._get_attributes(span)
        assert attrs == {"foo": "bar"}

    def test_shutdown_and_flush_noop(self):
        from agent_audit.tracing.opentelemetry import AuditSpanProcessor

        proc = AuditSpanProcessor()
        proc.shutdown()
        assert proc.force_flush() is True


# ---------------------------------------------------------------------------
# 6. Auto-tracing entry point
# ---------------------------------------------------------------------------


class TestAutoTracing:
    """install_auto_tracing() activation."""

    def test_install_auto_tracing_idempotent(self):
        import agent_audit.tracing.auto as auto_mod
        from agent_audit.tracing.auto import install_auto_tracing

        auto_mod._OPENAI_INSTALLED = False

        with patch("agent_audit.tracing.openai_instrumentor.OpenAIInstrumentor") as mock_instr_cls:
            mock_instr = MagicMock()
            mock_instr_cls.return_value = mock_instr

            result = install_auto_tracing()
            assert result is True
            mock_instr.install.assert_called_once()

            result2 = install_auto_tracing()
            assert result2 is True
            mock_instr.install.assert_called_once()

    def test_install_auto_tracing_exception_returns_false(self):
        import agent_audit.tracing.auto as auto_mod
        from agent_audit.tracing.auto import install_auto_tracing

        auto_mod._OPENAI_INSTALLED = False

        with patch("agent_audit.tracing.openai_instrumentor.OpenAIInstrumentor") as mock_instr_cls:
            mock_instr = MagicMock()
            mock_instr.install.side_effect = RuntimeError("nope")
            mock_instr_cls.return_value = mock_instr

            result = install_auto_tracing()
            assert result is False


# ---------------------------------------------------------------------------
# 7. Package exports
# ---------------------------------------------------------------------------


class TestPackageExports:
    """Public API is importable."""

    def test_toplevel_imports(self):
        import agent_audit.tracing

        assert hasattr(agent_audit.tracing, "TraceConfig")
        assert hasattr(agent_audit.tracing, "OpenAIInstrumentor")
        assert hasattr(agent_audit.tracing, "AnthropicInstrumentor")
        assert hasattr(agent_audit.tracing, "AuditSpanProcessor")
        assert hasattr(agent_audit.tracing, "estimate_openai_cost")
        assert hasattr(agent_audit.tracing, "install_auto_tracing")

    def test_submodule_imports(self):
        from agent_audit.tracing.anthropic import AnthropicInstrumentor
        from agent_audit.tracing.auto import install_auto_tracing
        from agent_audit.tracing.config import TraceConfig
        from agent_audit.tracing.cost import estimate_cost
        from agent_audit.tracing.openai_instrumentor import OpenAIInstrumentor
        from agent_audit.tracing.opentelemetry import AuditSpanProcessor, create_span_processor

        assert TraceConfig is not None
        assert estimate_cost is not None
        assert OpenAIInstrumentor is not None
        assert AnthropicInstrumentor is not None
        assert AuditSpanProcessor is not None
        assert create_span_processor is not None
        assert install_auto_tracing is not None


# ---------------------------------------------------------------------------
# 8. Redaction helper
# ---------------------------------------------------------------------------


class TestRedaction:
    """PII redaction and message truncation."""

    def test_redact_truncates_long_content(self):
        from agent_audit.tracing.openai_instrumentor import _redact_messages

        long_msg = [{"role": "user", "content": "A" * 3000}]
        result = _redact_messages(long_msg)
        assert len(result[0]["content"]) <= 2000

    def test_redact_preserves_short_content(self):
        from agent_audit.tracing.openai_instrumentor import _redact_messages

        msg = [{"role": "user", "content": "Hello"}]
        result = _redact_messages(msg)
        assert result[0]["content"] == "Hello"

    def test_redact_handles_non_dict_messages(self):
        from agent_audit.tracing.openai_instrumentor import _redact_messages

        msg = ["plain string", 42, None]
        result = _redact_messages(msg)
        assert result == msg
