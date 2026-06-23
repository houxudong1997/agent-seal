"""Comprehensive tests for agent-seal tracing module.

Covers the full surface area per P3.1 spec:
  - LLM call interception (real monkey-patching flow)
  - Audit trail write (detailed metadata, edge cases)
  - Cost calculation (integration with _trace_call, disabled path)
  - Session tracking (from kwargs, empty, missing)
  - Error edge cases (span cleanup, persist failures, audit failures)
  - DB persistence (_persist_llm_call)
  - Span handling (trace_id, span_id, attributes)
  - Redaction + capture flags
  - Auto-tracing env-var activation
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════
# 1. LLM Call Interception — full monkey-patching flow
# ═══════════════════════════════════════════════════════════════════


class TestLLMInterception:
    """Full install -> patch -> call -> trace -> uninstall flow."""

    def test_install_monkeypatches_openai(self):
        """After install, openai.chat.completions.create is replaced."""
        mock_openai = MagicMock()
        original_fn = MagicMock(return_value="original")
        mock_openai.chat.completions.create = original_fn

        with patch.dict(sys.modules, {"openai": mock_openai}):
            from agent_seal.tracing.openai_instrumentor import OpenAIInstrumentor

            instr = OpenAIInstrumentor()
            instr.install()

            assert instr._installed is True
            assert instr._original_create is original_fn
            assert mock_openai.chat.completions.create is not original_fn

    def test_install_idempotent_preserves_first_original(self):
        """Calling install twice does not lose the original reference."""
        mock_openai = MagicMock()
        original_fn = MagicMock(return_value="original")
        mock_openai.chat.completions.create = original_fn

        with patch.dict(sys.modules, {"openai": mock_openai}):
            from agent_seal.tracing.openai_instrumentor import OpenAIInstrumentor

            instr = OpenAIInstrumentor()
            instr.install()
            first_original = instr._original_create

            # Second call -- idempotent
            instr.install()
            assert instr._original_create is first_original

    def test_uninstall_restores_completely(self):
        """After uninstall, calling the original works normally."""
        mock_openai = MagicMock()
        original_fn = MagicMock(return_value="real-response")
        mock_openai.chat.completions.create = original_fn

        with patch.dict(sys.modules, {"openai": mock_openai}):
            from agent_seal.tracing.openai_instrumentor import OpenAIInstrumentor

            instr = OpenAIInstrumentor()
            instr.install()
            instr.uninstall()

            assert mock_openai.chat.completions.create is original_fn
            assert instr._installed is False
            assert instr._original_create is None

    def test_full_trace_flow_with_mock_response(self):
        """End-to-end: install -> call -> traced result returned."""
        from unittest.mock import PropertyMock

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 25
        mock_usage.total_tokens = 35

        mock_choice = MagicMock()
        mock_choice.message.content = "Hello, world!"

        mock_response = MagicMock()
        type(mock_response).model = PropertyMock(return_value="gpt-4o-mini")
        mock_response.usage = mock_usage
        mock_response.choices = [mock_choice]
        mock_response.model_dump.return_value = {
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Hello, world!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 25, "total_tokens": 35},
        }

        mock_openai = MagicMock()
        mock_original_create = MagicMock(return_value=mock_response)
        mock_openai.chat.completions.create = mock_original_create

        with patch.dict(sys.modules, {"openai": mock_openai}):
            from agent_seal.tracing.config import TraceConfig
            from agent_seal.tracing.openai_instrumentor import OpenAIInstrumentor

            config = TraceConfig(auto_audit=False, auto_cost=True)
            instr = OpenAIInstrumentor(config=config)
            instr.install()

            result = mock_openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Hi"}],
            )

            assert result is mock_response

    def test_trace_call_with_openai_sdk_response(self):
        """_trace_call extracts telemetry from an SDK-like response object."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        usage = MagicMock()
        usage.prompt_tokens = 50
        usage.completion_tokens = 100
        usage.total_tokens = 150

        choice = MagicMock()
        choice.message.content = "Response text"

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = usage
        response.choices = [choice]
        response.model_dump.return_value = {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "Response text"}}],
        }

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, capture_request=True, capture_response=True)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=None,
            tracer=None,
            db_available=False,
        )

        assert result is response

    def test_trace_call_result_no_usage_field(self):
        """When result has no usage, tokens default to 0."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        del response.usage

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, capture_request=False, auto_cost=False)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": []},
            config=config,
            engine=None,
            tracer=None,
            db_available=False,
        )
        assert result is response

    def test_redact_messages_various_types(self):
        """_redact_messages handles diverse content types."""
        from agent_seal.tracing.openai_instrumentor import _redact_messages

        long_content = "x" * 5000
        result = _redact_messages([{"role": "user", "content": long_content}])
        assert len(result[0]["content"]) == 2000

        result = _redact_messages([{"role": "user", "content": "short"}])
        assert result[0]["content"] == "short"

        assert _redact_messages([]) == []
        assert _redact_messages("string") == "string"
        assert _redact_messages(None) is None
        assert _redact_messages(42) == 42

        result = _redact_messages(["plain", {"role": "user", "content": "hi"}, None])
        assert result[0] == "plain"
        assert result[1]["content"] == "hi"
        assert result[2] is None

        exact = "a" * 2000
        result = _redact_messages([{"role": "user", "content": exact}])
        assert result[0]["content"] == exact

        over = "a" * 2001
        result = _redact_messages([{"role": "user", "content": over}])
        assert len(result[0]["content"]) == 2000


# ═══════════════════════════════════════════════════════════════════
# 2. Audit Trail Write -- detailed metadata + edge cases
# ═══════════════════════════════════════════════════════════════════


class TestAuditTrailWrite:
    """Audit trail logging from _trace_call."""

    def test_audit_logged_with_full_metadata(self):
        """Audit event includes all expected fields."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        usage = MagicMock()
        usage.prompt_tokens = 100
        usage.completion_tokens = 200
        usage.total_tokens = 300

        choice = MagicMock()
        choice.message.content = "Output text here"

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = usage
        response.choices = [choice]
        response.model_dump.return_value = {
            "choices": [{"message": {"content": "Output text here"}}]
        }

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True, auto_cost=True)

        with patch("agent_seal.tracing.openai_instrumentor.estimate_cost") as mock_cost:
            mock_cost.return_value = Decimal("0.002000")
            _trace_call(
                original=original,
                args=(),
                kwargs={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "audit_session_id": "sess-abc",
                    "audit_agent_id": "agent-xyz",
                    "prompt_version": "v2.1",
                },
                config=config,
                engine=engine,
                tracer=None,
                db_available=False,
            )

        engine.log.assert_called_once()
        kw = engine.log.call_args.kwargs
        assert kw["session_id"] == "sess-abc"
        assert kw["event_type"] == "model_request"
        assert kw["agent_id"] == "agent-xyz"
        assert kw["prompt_version"] == "v2.1"
        assert kw["input_text"] == "Hello"
        assert kw["output_text"] == "Output text here"
        assert kw["metadata"]["model"] == "gpt-4o"
        assert kw["metadata"]["tokens"] == 300
        assert kw["metadata"]["cost_usd"] == 0.002

    def test_audit_not_called_when_auto_audit_false(self):
        """auto_audit=False skips engine.log entirely."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = [MagicMock()]
        response.choices[0].message.content = "out"

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=False)

        _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        engine.log.assert_not_called()

    def test_audit_with_no_engine_noop(self):
        """When engine is None and auto_audit=True, no crash."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = [MagicMock()]
        response.choices[0].message.content = "out"

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=True)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=None,
            tracer=None,
            db_available=False,
        )
        assert result is response

    def test_audit_with_empty_response_content(self):
        """When response has no content, output_text is empty string."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        choice = MagicMock()
        choice.message.content = None

        response = MagicMock()
        response.model = "o1"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 5
        response.usage.completion_tokens = 5
        response.usage.total_tokens = 10
        response.choices = [choice]

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_call(
            original=original,
            args=(),
            kwargs={"model": "o1", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        engine.log.assert_called_once()
        assert engine.log.call_args.kwargs["output_text"] == ""

    def test_audit_with_no_choices(self):
        """When response.choices is empty, output_text is empty."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        engine.log.assert_called_once()
        assert engine.log.call_args.kwargs["output_text"] == ""

    def test_audit_exception_does_not_propagate(self):
        """If engine.log raises, _trace_call still returns the result."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = [MagicMock()]
        response.choices[0].message.content = "out"

        original = MagicMock(return_value=response)
        engine = MagicMock()
        engine.log.side_effect = RuntimeError("audit engine down")
        config = TraceConfig(auto_audit=True)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        assert result is response

    def test_audit_input_text_truncated_to_max_prompt_len(self):
        """Input/output text is truncated by config.max_prompt_len."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        choice = MagicMock()
        choice.message.content = "o" * 6000

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 10
        response.usage.completion_tokens = 10
        response.usage.total_tokens = 20
        response.choices = [choice]

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True, max_prompt_len=100)

        long_input = "i" * 5000
        _trace_call(
            original=original,
            args=(),
            kwargs={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": long_input}],
                "audit_session_id": "s",
                "audit_agent_id": "a",
            },
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        kw = engine.log.call_args.kwargs
        assert len(kw["input_text"]) == 100
        assert len(kw["output_text"]) == 100


# ═══════════════════════════════════════════════════════════════════
# 3. Cost Calculation -- integration with _trace_call
# ═══════════════════════════════════════════════════════════════════


class TestCostCalculation:
    """Cost estimation inside _trace_call."""

    def test_auto_cost_true_estimates_cost(self):
        """When auto_cost=True, estimate_cost is called with correct args."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        usage = MagicMock()
        usage.prompt_tokens = 1000
        usage.completion_tokens = 500
        usage.total_tokens = 1500

        response = MagicMock()
        response.model = "gpt-4o-mini"
        response.usage = usage
        response.choices = [MagicMock()]
        response.choices[0].message.content = "ok"

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_cost=True, auto_audit=False)

        with patch("agent_seal.tracing.openai_instrumentor.estimate_cost") as mock_cost:
            mock_cost.return_value = Decimal("0.000600")
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]},
                config=config,
                engine=None,
                tracer=None,
                db_available=False,
            )

        mock_cost.assert_called_once_with("openai", "gpt-4o-mini", 1000, 500)

    def test_auto_cost_false_skips_cost(self):
        """When auto_cost=False, estimate_cost is not called."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        usage = MagicMock()
        usage.prompt_tokens = 1000
        usage.completion_tokens = 500
        usage.total_tokens = 1500

        response = MagicMock()
        response.model = "gpt-4o-mini"
        response.usage = usage
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_cost=False, auto_audit=False)

        with patch("agent_seal.tracing.openai_instrumentor.estimate_cost") as mock_cost:
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o-mini", "messages": []},
                config=config,
                engine=None,
                tracer=None,
                db_available=False,
            )

        mock_cost.assert_not_called()

    def test_cost_exception_does_not_crash(self):
        """If estimate_cost raises, it's caught and cost defaults to 0.0."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 100
        response.usage.completion_tokens = 100
        response.usage.total_tokens = 200
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_cost=True, auto_audit=False)

        with patch("agent_seal.tracing.openai_instrumentor.estimate_cost") as mock_cost:
            mock_cost.side_effect = ValueError("bad model")
            result = _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=None,
                db_available=False,
            )
        assert result is response

    def test_cost_with_zero_tokens(self):
        """Cost is zero when both token counts are zero."""
        from agent_seal.tracing.cost import estimate_cost

        cost = estimate_cost("openai", "gpt-4o", 0, 0)
        assert cost == Decimal("0")

    def test_cost_with_large_numbers(self):
        """Cost calculation with large token counts."""
        from agent_seal.tracing.cost import estimate_openai_cost

        cost = estimate_openai_cost("gpt-4o", 10_000_000, 10_000_000)
        expected = Decimal("25.00") + Decimal("100.00")
        assert cost == expected.quantize(Decimal("0.000001"))

    def test_cost_all_openai_models(self):
        """All OpenAI models in price table produce non-zero cost."""
        from agent_seal.tracing.cost import _OPENAI_PRICES, estimate_openai_cost

        for model in _OPENAI_PRICES:
            cost = estimate_openai_cost(model, 100, 50)
            assert cost > Decimal("0"), f"Model {model} should have non-zero cost"


# ═══════════════════════════════════════════════════════════════════
# 4. Session Tracking -- from kwargs, empty, missing
# ═══════════════════════════════════════════════════════════════════


class TestSessionTracking:
    """Session/agent ID extraction from kwargs."""

    def test_session_id_from_audit_session_id(self):
        """session_id comes from kwargs['audit_session_id']."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = [MagicMock()]
        response.choices[0].message.content = "out"

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_call(
            original=original,
            args=(),
            kwargs={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
                "audit_session_id": "custom-session",
            },
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        assert engine.log.call_args.kwargs["session_id"] == "custom-session"

    def test_session_id_fallback_to_user(self):
        """Without audit_session_id, fallback to kwargs['user']."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = [MagicMock()]
        response.choices[0].message.content = "out"

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_call(
            original=original,
            args=(),
            kwargs={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
                "user": "user-42",
            },
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        assert engine.log.call_args.kwargs["session_id"] == "user-42"

    def test_session_id_empty_no_session(self):
        """When neither audit_session_id nor user is present, session becomes 'default'."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = [MagicMock()]
        response.choices[0].message.content = "out"

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_call(
            original=original,
            args=(),
            kwargs={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
            },
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        assert engine.log.call_args.kwargs["session_id"] == "default"

    def test_agent_id_from_audit_agent_id(self):
        """agent_id comes from kwargs['audit_agent_id']."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = [MagicMock()]
        response.choices[0].message.content = "out"

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_call(
            original=original,
            args=(),
            kwargs={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
                "audit_agent_id": "my-bot",
            },
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        assert engine.log.call_args.kwargs["agent_id"] == "my-bot"

    def test_agent_id_fallback_to_openai(self):
        """Without audit_agent_id, agent_id defaults to 'openai'."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = [MagicMock()]
        response.choices[0].message.content = "out"

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_call(
            original=original,
            args=(),
            kwargs={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
            },
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        assert engine.log.call_args.kwargs["agent_id"] == "openai"

    def test_audit_session_id_used_in_llm_calls_persist(self):
        """Session/agent IDs flow into _persist_llm_call."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, capture_request=False)

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            _trace_call(
                original=original,
                args=(),
                kwargs={
                    "model": "gpt-4o",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "audit_session_id": "sess-99",
                    "audit_agent_id": "agent-007",
                },
                config=config,
                engine=None,
                tracer=None,
                db_available=True,
            )

        mock_persist.assert_called_once()
        kw = mock_persist.call_args.kwargs
        assert kw["session_id"] == "sess-99"
        assert kw["agent_id"] == "agent-007"


# ═══════════════════════════════════════════════════════════════════
# 5. Error Edge Cases -- every error path in the instrumentor
# ═══════════════════════════════════════════════════════════════════


class TestErrorEdgeCases:
    """Error handling throughout the tracing pipeline."""

    def test_error_propagates_after_span_cleanup(self):
        """Error from original() is re-raised after span is properly ended."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        original = MagicMock(side_effect=ConnectionError("API timeout"))
        config = TraceConfig(auto_audit=False)

        with pytest.raises(ConnectionError, match="API timeout"):
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=None,
                db_available=False,
            )

    def test_error_from_span_start_not_crash(self):
        """If tracer.start_span raises, _trace_call degrades gracefully."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        bad_tracer = MagicMock()
        bad_tracer.start_span.side_effect = TypeError("span failed")

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": []},
            config=config,
            engine=None,
            tracer=bad_tracer,
            db_available=False,
        )
        assert result is response

    def test_span_end_called_on_success(self):
        """Span.end() is called after a successful call."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False)

        _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": []},
            config=config,
            engine=None,
            tracer=mock_tracer,
            db_available=False,
        )

        mock_span.end.assert_called_once()

    def test_span_end_called_on_error(self):
        """Span.end() is still called when original raises."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        original = MagicMock(side_effect=RuntimeError("fail"))
        config = TraceConfig(auto_audit=False)

        with pytest.raises(RuntimeError):
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=mock_tracer,
                db_available=False,
            )

        mock_span.end.assert_called_once()

    def test_span_records_exception_on_error(self):
        """Exception is recorded on the span before cleanup."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        original = MagicMock(side_effect=ValueError("bad input"))
        config = TraceConfig(auto_audit=False)

        with pytest.raises(ValueError):
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=mock_tracer,
                db_available=False,
            )

        mock_span.record_exception.assert_called_once()

    def test_error_in_record_exception_does_not_crash(self):
        """If span.record_exception raises, cleanup still happens."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.record_exception.side_effect = TypeError("bad exception")
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        original = MagicMock(side_effect=RuntimeError("fail"))
        config = TraceConfig(auto_audit=False)

        with pytest.raises(RuntimeError):
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=mock_tracer,
                db_available=False,
            )

        mock_span.end.assert_called_once()

    def test_error_in_span_end_does_not_crash(self):
        """If span.end raises, _trace_call still returns the result."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.end.side_effect = RuntimeError("span end crash")
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": []},
            config=config,
            engine=None,
            tracer=mock_tracer,
            db_available=False,
        )
        assert result is response

    def test_persist_failure_is_caught(self):
        """If _persist_llm_call raises, it's caught and result still returned."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, capture_request=False)

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            mock_persist.side_effect = RuntimeError("DB full")
            result = _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=None,
                db_available=True,
            )
        assert result is response

    def test_span_set_attribute_exception_does_not_crash(self):
        """If span.set_attribute raises, it's caught."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.set_attribute.side_effect = TypeError("bad attr")
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": []},
            config=config,
            engine=None,
            tracer=mock_tracer,
            db_available=False,
        )
        assert result is response

    def test_span_get_span_context_exception_does_not_crash(self):
        """If get_span_context raises, trace_id/span_id default to empty."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.get_span_context.side_effect = RuntimeError("no ctx")
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False)

        result = _trace_call(
            original=original,
            args=(),
            kwargs={"model": "gpt-4o", "messages": []},
            config=config,
            engine=None,
            tracer=mock_tracer,
            db_available=False,
        )
        assert result is response

    def test_original_called_with_correct_args(self):
        """The original function receives the same args/kwargs."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        original = MagicMock(return_value="result")
        config = TraceConfig(auto_audit=False)

        _trace_call(
            original=original,
            args=(1, 2),
            kwargs={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
                "temperature": 0.7,
            },
            config=config,
            engine=None,
            tracer=None,
            db_available=False,
        )

        original.assert_called_once_with(
            1, 2, model="gpt-4o", messages=[{"role": "user", "content": "Hi"}], temperature=0.7
        )

    def test_openai_rate_limit_error_propagates(self):
        """APIError / RateLimitError from openai propagates correctly."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        class RateLimitError(Exception):
            pass

        original = MagicMock(side_effect=RateLimitError("rate limited"))
        config = TraceConfig(auto_audit=False)

        with pytest.raises(RateLimitError, match="rate limited"):
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=None,
                db_available=False,
            )

    def test_multiple_exceptions_do_not_mask_result(self):
        """Errors in span + persist + audit all caught, result still returned."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.set_attribute.side_effect = TypeError("bad attr")
        mock_span.get_span_context.side_effect = RuntimeError("no ctx")
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        engine = MagicMock()
        engine.log.side_effect = RuntimeError("audit busted")
        config = TraceConfig(auto_audit=True, capture_request=False)

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            mock_persist.side_effect = RuntimeError("DB full")
            result = _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=engine,
                tracer=mock_tracer,
                db_available=True,
            )

        assert result is response


# ═══════════════════════════════════════════════════════════════════
# 6. DB Persistence -- _persist_llm_call
# ═══════════════════════════════════════════════════════════════════


class TestDBPersistence:
    """_persist_llm_call behavior."""

    def test_persist_skips_when_no_db_url(self):
        """When db_url is empty, _persist_llm_call silently returns."""
        from agent_seal.tracing.openai_instrumentor import _persist_llm_call

        with patch("agent_seal.config.config") as mock_cfg:
            mock_cfg.db_url = ""
            _persist_llm_call(
                trace_id="abc",
                span_id="def",
                parent_span_id="",
                provider="openai",
                model="gpt-4o",
                request_tokens=10,
                response_tokens=20,
                total_tokens=30,
                latency_ms=100,
                cost_usd=0.001,
                request_body=None,
                response_body=None,
                session_id="sess-1",
                agent_id="agent-1",
                event_id=None,
            )

    def test_persist_sqlalchemy_error_is_caught(self):
        """If SQLAlchemy raises, _persist_llm_call catches it (verifies no crash)."""
        from agent_seal.tracing.openai_instrumentor import _persist_llm_call

        with patch("agent_seal.config.config") as mock_cfg:
            mock_cfg.db_url = "sqlite:///test.db"
            # The function imports create_engine inside a try/except,
            # so it gracefully degrades regardless
            _persist_llm_call(
                trace_id="abc",
                span_id="def",
                parent_span_id="",
                provider="openai",
                model="gpt-4o",
                request_tokens=10,
                response_tokens=20,
                total_tokens=30,
                latency_ms=100,
                cost_usd=0.001,
                request_body=None,
                response_body=None,
                session_id=None,
                agent_id=None,
                event_id=None,
            )

    def test_persist_import_error_llmcall_model(self):
        """If LLMCall model not importable, _persist_llm_call is no-op."""
        from agent_seal.tracing.openai_instrumentor import _persist_llm_call

        def mock_import(name, *args, **kwargs):
            if name == "agent_seal.models.llm_call":
                raise ImportError("no module")
            return __import__(name, *args, **kwargs)

        with patch("agent_seal.config.config") as mock_cfg:
            mock_cfg.db_url = "sqlite:///test.db"
            with patch("builtins.__import__", side_effect=mock_import):
                _persist_llm_call(
                    trace_id="abc",
                    span_id="def",
                    parent_span_id="",
                    provider="openai",
                    model="gpt-4o",
                    request_tokens=10,
                    response_tokens=20,
                    total_tokens=30,
                    latency_ms=100,
                    cost_usd=0.001,
                    request_body=None,
                    response_body=None,
                    session_id=None,
                    agent_id=None,
                    event_id=None,
                )


# ═══════════════════════════════════════════════════════════════════
# 7. Capture Flags -- request/response body control
# ═══════════════════════════════════════════════════════════════════


class TestCaptureFlags:
    """capture_request / capture_response flags."""

    def test_capture_request_skips_body_when_false(self):
        """When capture_request=False, request_body is None in persist."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, capture_request=False, capture_response=True)

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "secret"}]},
                config=config,
                engine=None,
                tracer=None,
                db_available=True,
            )

        persist_kw = mock_persist.call_args.kwargs
        assert persist_kw["request_body"] is None

    def test_capture_response_skips_body_when_false(self):
        """When capture_response=False, response_body is None in persist."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, capture_request=True, capture_response=False)

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
                config=config,
                engine=None,
                tracer=None,
                db_available=True,
            )

        persist_kw = mock_persist.call_args.kwargs
        assert persist_kw["response_body"] is None

    def test_capture_response_with_model_dump_error(self):
        """If model_dump raises, response_body is None."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []
        response.model_dump.side_effect = TypeError("cannot dump")

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, capture_request=False, capture_response=True)

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
                config=config,
                engine=None,
                tracer=None,
                db_available=True,
            )

        persist_kw = mock_persist.call_args.kwargs
        assert persist_kw["response_body"] is None

    def test_pii_redact_truncates_request_body(self):
        """When pii_redact=True and content long, request body is truncated."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, pii_redact=True, capture_request=True)

        long_msg = [{"role": "user", "content": "x" * 5000}]

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": long_msg},
                config=config,
                engine=None,
                tracer=None,
                db_available=True,
            )

        persist_kw = mock_persist.call_args.kwargs
        body = persist_kw["request_body"]
        assert body is not None
        assert len(body["messages"][0]["content"]) == 2000

    def test_pii_redact_false_preserves_full_content(self):
        """When pii_redact=False, request body content is not truncated."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, pii_redact=False, capture_request=True)

        long_msg = [{"role": "user", "content": "x" * 5000}]

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": long_msg},
                config=config,
                engine=None,
                tracer=None,
                db_available=True,
            )

        persist_kw = mock_persist.call_args.kwargs
        body = persist_kw["request_body"]
        assert body is not None
        assert len(body["messages"][0]["content"]) == 5000


# ═══════════════════════════════════════════════════════════════════
# 8. Span Handling -- trace_id, span_id, attributes
# ═══════════════════════════════════════════════════════════════════


class TestSpanHandling:
    """OpenTelemetry span lifecycle and attributes."""

    def test_span_attributes_set_correctly(self):
        """Span attributes include all llm.* fields."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.get_span_context.return_value.trace_id = 12345
        mock_span.get_span_context.return_value.span_id = 67890
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        usage = MagicMock()
        usage.prompt_tokens = 50
        usage.completion_tokens = 100
        usage.total_tokens = 150

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = usage
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, auto_cost=True)

        with patch("agent_seal.tracing.openai_instrumentor.estimate_cost") as mock_cost:
            mock_cost.return_value = Decimal("0.000750")
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]},
                config=config,
                engine=None,
                tracer=mock_tracer,
                db_available=False,
            )

        expected_attrs = {
            "llm.provider": "openai",
            "llm.model": "gpt-4o",
            "llm.request_tokens": 50,
            "llm.response_tokens": 100,
            "llm.total_tokens": 150,
            "llm.cost_usd": 0.00075,
        }
        for key, value in expected_attrs.items():
            mock_span.set_attribute.assert_any_call(key, value)

    def test_span_context_trace_id_formatted(self):
        """Trace ID is formatted as 32-char hex."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.get_span_context.return_value.trace_id = 0xABCDEF1234567890
        mock_span.get_span_context.return_value.span_id = 0xFFEEDDCCBBAA9988
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        response = MagicMock()
        response.model = "gpt-4o"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False)

        with patch("agent_seal.tracing.openai_instrumentor._persist_llm_call") as mock_persist:
            _trace_call(
                original=original,
                args=(),
                kwargs={"model": "gpt-4o", "messages": []},
                config=config,
                engine=None,
                tracer=mock_tracer,
                db_available=True,
            )

        persist_kw = mock_persist.call_args.kwargs
        assert persist_kw["trace_id"] == "0000000000000000abcdef1234567890"
        assert persist_kw["span_id"] == "ffeeddccbbaa9988"

    def test_span_name_uses_config_prefix(self):
        """Span name is '{config.span_prefix}/{model}'."""
        from agent_seal.tracing.config import TraceConfig
        from agent_seal.tracing.openai_instrumentor import _trace_call

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span

        response = MagicMock()
        response.model = "o3-mini"
        response.usage = MagicMock()
        response.usage.prompt_tokens = 1
        response.usage.completion_tokens = 1
        response.usage.total_tokens = 2
        response.choices = []

        original = MagicMock(return_value=response)
        config = TraceConfig(span_prefix="ai")

        _trace_call(
            original=original,
            args=(),
            kwargs={"model": "o3-mini", "messages": []},
            config=config,
            engine=None,
            tracer=mock_tracer,
            db_available=False,
        )

        mock_tracer.start_span.assert_called_once_with("ai/o3-mini")

    def test_tracer_resolution_fallback(self):
        """_resolve_tracer returns None when opentelemetry not installed."""
        from agent_seal.tracing.openai_instrumentor import _resolve_tracer

        with patch.dict(sys.modules, {"opentelemetry": None}):
            result = _resolve_tracer(None)
            assert result is None

    def test_tracer_resolution_passed_through(self):
        """_resolve_tracer returns the tracer if provided."""
        from agent_seal.tracing.openai_instrumentor import _resolve_tracer

        mock_tracer = MagicMock()
        result = _resolve_tracer(mock_tracer)
        assert result is mock_tracer


# ═══════════════════════════════════════════════════════════════════
# 9. Auto-tracing -- env-var activation
# ═══════════════════════════════════════════════════════════════════


class TestAutoTracingExtended:
    """Extended auto-tracing tests."""

    def test_auto_enabled_recognises_valid_values(self):
        """_auto_enabled returns True for 1/true/yes/on."""
        from agent_seal.tracing.auto import _auto_enabled

        for val in ("1", "true", "TRUE", "True", "yes", "YES", "on", "ON"):
            with patch.dict(os.environ, {"AGENT_SEAL_AUTO_TRACE": val}):
                assert _auto_enabled() is True, f"Value '{val}' should be True"

    def test_auto_enabled_rejects_invalid_values(self):
        """_auto_enabled returns False for other values."""
        from agent_seal.tracing.auto import _auto_enabled

        for val in ("0", "false", "no", "off", "maybe", "", "  "):
            with patch.dict(os.environ, {"AGENT_SEAL_AUTO_TRACE": val}):
                assert _auto_enabled() is False, f"Value '{val}' should be False"

    def test_auto_enabled_when_unset(self):
        """_auto_enabled returns False when env var not set."""
        from agent_seal.tracing.auto import _auto_enabled

        saved = os.environ.pop("AGENT_SEAL_AUTO_TRACE", None)
        try:
            assert _auto_enabled() is False
        finally:
            if saved is not None:
                os.environ["AGENT_SEAL_AUTO_TRACE"] = saved

    def test_install_auto_tracing_passes_engine(self):
        """install_auto_tracing passes engine to OpenAIInstrumentor."""
        import agent_seal.tracing.auto as auto_mod
        from agent_seal.tracing.auto import install_auto_tracing

        saved = auto_mod._OPENAI_INSTALLED
        auto_mod._OPENAI_INSTALLED = False
        try:
            engine = MagicMock()
            with patch("agent_seal.tracing.openai_instrumentor.OpenAIInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr_cls.return_value = mock_instr

                result = install_auto_tracing(engine=engine)
                assert result is True
                mock_instr_cls.assert_called_once()
                assert mock_instr_cls.call_args.kwargs.get("engine") is engine
        finally:
            auto_mod._OPENAI_INSTALLED = saved

    def test_install_auto_tracing_creates_traceconfig(self):
        """install_auto_tracing creates TraceConfig from app config."""
        import agent_seal.tracing.auto as auto_mod
        from agent_seal.tracing.auto import install_auto_tracing

        saved = auto_mod._OPENAI_INSTALLED
        auto_mod._OPENAI_INSTALLED = False
        try:
            with patch("agent_seal.tracing.openai_instrumentor.OpenAIInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr_cls.return_value = mock_instr

                result = install_auto_tracing()
                assert result is True

                call_config = mock_instr_cls.call_args.kwargs.get("config")
                assert call_config is not None
                assert call_config.auto_cost is True
        finally:
            auto_mod._OPENAI_INSTALLED = saved


# ═══════════════════════════════════════════════════════════════════
# 10. AuditSpanProcessor -- extended edge cases
# ═══════════════════════════════════════════════════════════════════


class TestAuditSpanProcessorExtended:
    """Extended AuditSpanProcessor edge cases."""

    def test_non_llm_span_ignored(self):
        """Span without llm.* attributes is skipped."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine)

        proc.on_end({"attributes": {"some.key": "val"}})
        engine.log.assert_not_called()

        span = MagicMock()
        span.attributes = {"some.key": "val"}
        proc.on_end(span)
        engine.log.assert_not_called()

    def test_processes_otel_sdk_span(self):
        """Processes a real OTel SDK-like span object."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine, auto_audit=True)

        class FakeSpanContext:
            trace_id = 0xABCD
            span_id = 0x1234

        class FakeSpan:
            attributes: dict[str, object] = {  # noqa: RUF012
                "llm.model": "gpt-4o",
                "llm.provider": "openai",
                "llm.request_tokens": 50,
                "llm.response_tokens": 100,
                "llm.total_tokens": 150,
                "llm.latency_ms": 500,
                "session.id": "sess-1",
                "agent.id": "agent-1",
                "audit.enabled": "true",
            }

            def get_span_context(self):
                return FakeSpanContext()

            @property
            def parent(self):
                return None

        proc.on_end(FakeSpan())

        engine.log.assert_called_once()
        kw = engine.log.call_args.kwargs
        assert kw["session_id"] == "sess-1"
        assert kw["agent_id"] == "agent-1"
        assert kw["metadata"]["model"] == "gpt-4o"
        assert kw["metadata"]["tokens"] == 150
        assert kw["metadata"]["latency_ms"] == 500

    def test_auto_cost_disabled_in_processor(self):
        """When auto_cost=False, cost stays 0.0."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        engine = MagicMock()
        proc = AuditSpanProcessor(engine=engine, auto_audit=True, auto_cost=False)

        span = {
            "attributes": {
                "llm.model": "gpt-4o",
                "llm.provider": "openai",
                "llm.request_tokens": 1000,
                "llm.response_tokens": 500,
                "session.id": "s",
                "agent.id": "a",
                "audit.enabled": "true",
            },
            "trace_id": "x",
            "span_id": "y",
            "parent_span_id": "",
        }

        proc.on_end(span)
        kw = engine.log.call_args.kwargs
        assert kw["metadata"]["cost_usd"] == 0.0

    def test_processor_get_parent_span_id(self):
        """_get_parent_span_id extracts correctly from OTel span."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        class FakeParentCtx:
            span_id = 0xFFEEDDCCBBAA9988

        class FakeParent:
            def get_span_context(self):
                return FakeParentCtx()

        class FakeSpan:
            attributes: dict[str, str] = {"llm.model": "gpt-4o"}  # noqa: RUF012
            parent = FakeParent()

            def get_span_context(self):
                class Ctx:
                    trace_id = 1
                    span_id = 2

                return Ctx()

        pid = AuditSpanProcessor._get_parent_span_id(FakeSpan())
        assert pid == "ffeeddccbbaa9988"

    def test_processor_handles_span_with_no_parent(self):
        """_get_parent_span_id returns '' when parent is None."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor

        span = MagicMock()
        span.parent = None
        pid = AuditSpanProcessor._get_parent_span_id(span)
        assert pid == ""

    def test_create_span_processor_factory(self):
        """create_span_processor returns a configured AuditSpanProcessor."""
        from agent_seal.tracing.opentelemetry import AuditSpanProcessor, create_span_processor

        engine = MagicMock()
        proc = create_span_processor(engine, auto_audit=False, auto_cost=False)
        assert isinstance(proc, AuditSpanProcessor)
        assert proc.engine is engine
        assert proc.auto_audit is False
        assert proc.auto_cost is False


# ═══════════════════════════════════════════════════════════════════
# 11. Anthropic Instrumentor — Comprehensive
# ═══════════════════════════════════════════════════════════════════


class TestAnthropicComprehensive:
    """Anthropic instrumentor: full install -> patch -> call -> trace -> uninstall flow."""

    def test_install_monkeypatches_anthropic(self):
        """After install, anthropic.messages.create is replaced."""
        mock_anthropic = MagicMock()
        original_fn = MagicMock(return_value="original")
        mock_anthropic.messages.create = original_fn

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            from agent_seal.tracing.anthropic import AnthropicInstrumentor

            instr = AnthropicInstrumentor()
            instr.install()

            assert instr._installed is True
            assert instr._original_create is original_fn
            assert mock_anthropic.messages.create is not original_fn

    def test_install_idempotent_preserves_first_original(self):
        """Calling install twice does not lose the original reference."""
        mock_anthropic = MagicMock()
        original_fn = MagicMock(return_value="original")
        mock_anthropic.messages.create = original_fn

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            from agent_seal.tracing.anthropic import AnthropicInstrumentor

            instr = AnthropicInstrumentor()
            instr.install()
            first_original = instr._original_create

            instr.install()
            assert instr._original_create is first_original

    def test_uninstall_restores_completely(self):
        """After uninstall, calling the original works normally."""
        mock_anthropic = MagicMock()
        original_fn = MagicMock(return_value="real-response")
        mock_anthropic.messages.create = original_fn

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            from agent_seal.tracing.anthropic import AnthropicInstrumentor

            instr = AnthropicInstrumentor()
            instr.install()
            instr.uninstall()

            assert mock_anthropic.messages.create is original_fn
            assert instr._installed is False
            assert instr._original_create is None

    def test_full_trace_flow_with_mock_response(self):
        """End-to-end: install -> call -> traced result returned."""
        from unittest.mock import PropertyMock

        mock_usage = MagicMock()
        mock_usage.input_tokens = 15
        mock_usage.output_tokens = 30

        content_block = MagicMock()
        content_block.text = "Hello from Claude!"

        mock_response = MagicMock()
        type(mock_response).model = PropertyMock(return_value="claude-sonnet-4")
        mock_response.usage = mock_usage
        mock_response.content = [content_block]
        mock_response.model_dump.return_value = {
            "model": "claude-sonnet-4",
            "content": [{"type": "text", "text": "Hello from Claude!"}],
            "usage": {"input_tokens": 15, "output_tokens": 30},
        }

        mock_anthropic = MagicMock()
        mock_original_create = MagicMock(return_value=mock_response)
        mock_anthropic.messages.create = mock_original_create

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            from agent_seal.tracing.anthropic import AnthropicInstrumentor
            from agent_seal.tracing.config import TraceConfig

            config = TraceConfig(auto_audit=False, auto_cost=True)
            instr = AnthropicInstrumentor(config=config)
            instr.install()

            result = mock_anthropic.messages.create(
                model="claude-sonnet-4",
                messages=[{"role": "user", "content": "Hi"}],
            )

            assert result is mock_response

    def test_trace_call_result_no_usage_field(self):
        """When result has no usage, tokens default to 0."""
        from agent_seal.tracing.anthropic import _trace_anthropic_call
        from agent_seal.tracing.config import TraceConfig

        response = MagicMock()
        response.model = "claude-haiku-3"
        del response.usage

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=False, capture_request=False, auto_cost=False)

        result = _trace_anthropic_call(
            original=original,
            args=(),
            kwargs={"model": "claude-haiku-3", "messages": []},
            config=config,
            engine=None,
            tracer=None,
            db_available=False,
        )
        assert result is response

    def test_audit_with_full_metadata_anthropic(self):
        """Audit event includes all expected fields for Anthropic."""
        from agent_seal.tracing.anthropic import _trace_anthropic_call
        from agent_seal.tracing.config import TraceConfig

        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 200

        content_block = MagicMock()
        content_block.text = "Claude output text"

        response = MagicMock()
        response.model = "claude-sonnet-4"
        response.usage = mock_usage
        response.content = [content_block]
        response.model_dump.return_value = {
            "content": [{"type": "text", "text": "Claude output text"}],
        }

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True, auto_cost=True)

        with patch("agent_seal.tracing.anthropic.estimate_cost") as mock_cost:
            mock_cost.return_value = Decimal("0.003000")
            _trace_anthropic_call(
                original=original,
                args=(),
                kwargs={
                    "model": "claude-sonnet-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "audit_session_id": "sess-abc",
                    "audit_agent_id": "agent-xyz",
                    "prompt_version": "v2.1",
                },
                config=config,
                engine=engine,
                tracer=None,
                db_available=False,
            )

        engine.log.assert_called_once()
        kw = engine.log.call_args.kwargs
        assert kw["session_id"] == "sess-abc"
        assert kw["event_type"] == "model_request"
        assert kw["agent_id"] == "agent-xyz"
        assert kw["prompt_version"] == "v2.1"
        assert kw["input_text"] == "Hello"
        assert kw["output_text"] == "Claude output text"
        assert kw["metadata"]["model"] == "claude-sonnet-4"
        assert kw["metadata"]["tokens"] == 300
        assert kw["metadata"]["cost_usd"] == 0.003

    def test_audit_not_called_when_auto_audit_false_anthropic(self):
        """auto_audit=False skips engine.log entirely for Anthropic."""
        from agent_seal.tracing.anthropic import _trace_anthropic_call
        from agent_seal.tracing.config import TraceConfig

        content_block = MagicMock()
        content_block.text = "out"

        response = MagicMock()
        response.model = "claude-haiku-3"
        response.usage = MagicMock()
        response.usage.input_tokens = 1
        response.usage.output_tokens = 1
        response.content = [content_block]

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=False)

        _trace_anthropic_call(
            original=original,
            args=(),
            kwargs={"model": "claude-haiku-3", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        engine.log.assert_not_called()

    def test_audit_with_no_engine_noop_anthropic(self):
        """When engine is None and auto_audit=True, no crash for Anthropic."""
        from agent_seal.tracing.anthropic import _trace_anthropic_call
        from agent_seal.tracing.config import TraceConfig

        response = MagicMock()
        response.model = "claude-sonnet-4"
        response.usage = MagicMock()
        response.usage.input_tokens = 1
        response.usage.output_tokens = 1
        response.content = [MagicMock()]
        response.content[0].text = "out"

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_audit=True)

        result = _trace_anthropic_call(
            original=original,
            args=(),
            kwargs={"model": "claude-sonnet-4", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=None,
            tracer=None,
            db_available=False,
        )
        assert result is response

    def test_audit_with_empty_content_anthropic(self):
        """When response has no content text, output_text is empty string."""
        from agent_seal.tracing.anthropic import _trace_anthropic_call
        from agent_seal.tracing.config import TraceConfig

        response = MagicMock()
        response.model = "claude-opus-4"
        response.usage = MagicMock()
        response.usage.input_tokens = 5
        response.usage.output_tokens = 5
        response.content = []

        original = MagicMock(return_value=response)
        engine = MagicMock()
        config = TraceConfig(auto_audit=True)

        _trace_anthropic_call(
            original=original,
            args=(),
            kwargs={"model": "claude-opus-4", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        engine.log.assert_called_once()
        assert engine.log.call_args.kwargs["output_text"] == ""

    def test_audit_exception_does_not_propagate_anthropic(self):
        """If engine.log raises, _trace_anthropic_call still returns the result."""
        from agent_seal.tracing.anthropic import _trace_anthropic_call
        from agent_seal.tracing.config import TraceConfig

        response = MagicMock()
        response.model = "claude-sonnet-4"
        response.usage = MagicMock()
        response.usage.input_tokens = 1
        response.usage.output_tokens = 1
        response.content = [MagicMock()]
        response.content[0].text = "out"

        original = MagicMock(return_value=response)
        engine = MagicMock()
        engine.log.side_effect = OSError("audit engine down")
        config = TraceConfig(auto_audit=True)

        result = _trace_anthropic_call(
            original=original,
            args=(),
            kwargs={"model": "claude-sonnet-4", "messages": [{"role": "user", "content": "Hi"}]},
            config=config,
            engine=engine,
            tracer=None,
            db_available=False,
        )

        assert result is response

    def test_auto_cost_true_estimates_anthropic_cost(self):
        """When auto_cost=True, estimate_cost is called with correct args."""
        from agent_seal.tracing.anthropic import _trace_anthropic_call
        from agent_seal.tracing.config import TraceConfig

        mock_usage = MagicMock()
        mock_usage.input_tokens = 1000
        mock_usage.output_tokens = 500

        content_block = MagicMock()
        content_block.text = "ok"

        response = MagicMock()
        response.model = "claude-sonnet-4"
        response.usage = mock_usage
        response.content = [content_block]

        original = MagicMock(return_value=response)
        config = TraceConfig(auto_cost=True, auto_audit=False)

        with patch("agent_seal.tracing.anthropic.estimate_cost") as mock_cost:
            mock_cost.return_value = Decimal("0.010500")
            _trace_anthropic_call(
                original=original,
                args=(),
                kwargs={
                    "model": "claude-sonnet-4",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
                config=config,
                engine=None,
                tracer=None,
                db_available=False,
            )

            mock_cost.assert_called_once_with("anthropic", "claude-sonnet-4", 1000, 500)

    def test_auto_anthropic_tracing_install(self):
        """install_auto_anthropic_tracing activates the instrumentor."""
        import agent_seal.tracing.auto as auto_mod

        saved = auto_mod._ANTHROPIC_INSTALLED
        auto_mod._ANTHROPIC_INSTALLED = False
        try:
            with patch("agent_seal.tracing.anthropic.AnthropicInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr_cls.return_value = mock_instr

                result = auto_mod.install_auto_anthropic_tracing()
                assert result is True
                mock_instr.install.assert_called_once()
        finally:
            auto_mod._ANTHROPIC_INSTALLED = saved

    def test_auto_anthropic_tracing_exception_returns_false(self):
        """install_auto_anthropic_tracing returns False on exception."""
        import agent_seal.tracing.auto as auto_mod

        saved = auto_mod._ANTHROPIC_INSTALLED
        auto_mod._ANTHROPIC_INSTALLED = False
        try:
            with patch("agent_seal.tracing.anthropic.AnthropicInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr.install.side_effect = RuntimeError("nope")
                mock_instr_cls.return_value = mock_instr

                result = auto_mod.install_auto_anthropic_tracing()
                assert result is False
        finally:
            auto_mod._ANTHROPIC_INSTALLED = saved
