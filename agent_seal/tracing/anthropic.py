"""
Anthropic auto-instrumentor — intercepts ``anthropic.messages.create``.

Monkey-patches the Anthropic Python SDK so that every message creation
is automatically wrapped in an OpenTelemetry span, recorded in the
``llm_calls`` table (SQLAlchemy), and pushed to the agent-seal hash-chain.

Shares the same ``TraceConfig``, ``AuditEngine`` interface, and persistence
helpers (``_persist_llm_call``, ``_redact_messages``) as the OpenAI instrumentor.
"""

from __future__ import annotations

import logging
import time
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.storage import AuditEngine

from .config import TraceConfig
from .cost import estimate_cost
from .openai_instrumentor import _persist_llm_call, _redact_messages

logger = logging.getLogger("agent_seal.tracing.anthropic")


class AnthropicInstrumentor:
    """Monkey-patch ``anthropic.messages.create`` for audit tracing.

    Parameters
    ----------
    config:
        Runtime configuration (truncation, redaction, cost model, …).
        If omitted a default ``TraceConfig`` is created.
    engine:
        Optional ``AuditEngine`` instance.  When provided every LLM call
        is also written to the audit trail hash-chain.
    tracer:
        OpenTelemetry tracer — auto-loaded if omitted.

    Usage::

        instr = AnthropicInstrumentor(config, engine=engine)
        instr.install()

        import anthropic
        resp = anthropic.messages.create(model="claude-sonnet-4", messages=[...])
    """

    def __init__(
        self,
        config: TraceConfig | None = None,
        engine: AuditEngine | None = None,
        tracer: Any = None,
    ):
        self.config = config or TraceConfig()
        self.engine = engine
        self._tracer = tracer
        self._installed = False
        self._original_create = None

    def install(self) -> None:
        """Activate the instrumentor (idempotent)."""
        if self._installed:
            logger.debug("AnthropicInstrumentor already installed — skipping")
            return

        try:
            import anthropic
        except ImportError:
            logger.warning(
                "anthropic package not installed — AnthropicInstrumentor.install() is a no-op"
            )
            return

        original = anthropic.messages.create
        config = self.config
        engine = self.engine
        _tracer = self._tracer
        _db_available = self._check_db_available()

        @wraps(original)
        def traced_create(*args: Any, **kwargs: Any) -> Any:
            return _trace_anthropic_call(
                original=original,
                args=args,
                kwargs=kwargs,
                config=config,
                engine=engine,
                tracer=_tracer,
                db_available=_db_available,
            )

        anthropic.messages.create = traced_create
        self._original_create = original
        self._installed = True
        logger.info("AnthropicInstrumentor installed — all anthropic.messages.create calls traced")

    def uninstall(self) -> None:
        """Restore the original ``anthropic.messages.create``."""
        if not self._installed or self._original_create is None:
            return
        try:
            import anthropic
        except ImportError:
            return
        anthropic.messages.create = self._original_create
        self._installed = False
        self._original_create = None
        logger.info("AnthropicInstrumentor uninstalled")

    @staticmethod
    def _check_db_available() -> bool:
        try:
            from ..config import config as app_cfg

            if app_cfg.db_url:
                return True
        except ImportError as exc:
            logger.debug("DB availability check failed: %s", exc)
        return False


# ── Standalone trace function ────────────────────────────────────


def _resolve_tracer(tracer: Any = None) -> Any:
    if tracer is not None:
        return tracer
    try:
        from opentelemetry import trace as otel_trace

        return otel_trace.get_tracer("agent-seal")
    except ImportError:
        logger.debug("opentelemetry not installed — spans disabled")
        return None


def _extract_content_text(content: Any) -> str:
    """Extract text from Anthropic's content blocks.

    Anthropic returns ``content`` as a list of ``ContentBlock`` objects
    (TextBlock, ToolUseBlock, etc.).  This extracts the text from the
    first TextBlock, or returns an empty string for non-text blocks.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # content is typically a list of ContentBlock objects
    if isinstance(content, list) and content:
        first_block = content[0]
        if isinstance(first_block, dict):
            return str(first_block.get("text", ""))
        if hasattr(first_block, "text"):
            return str(first_block.text or "")
    return ""


def _trace_anthropic_call(
    *,
    original: Any,
    args: tuple,
    kwargs: dict,
    config: TraceConfig,
    engine: AuditEngine | None,
    tracer: Any,
    db_available: bool,
) -> Any:
    """Core interception logic for a single ``anthropic.messages.create`` call."""

    tracer = _resolve_tracer(tracer)
    model = kwargs.get("model", "unknown")
    span_name = f"{config.span_prefix}/{model}"

    span = None
    if tracer is not None:
        try:
            span = tracer.start_span(span_name)
            if span is not None and hasattr(span, "__enter__"):
                span.__enter__()
        except AttributeError as exc:
            logger.debug("Span start failed: %s", exc)
            span = None

    start = time.time()
    result = None
    error = None

    try:
        result = original(*args, **kwargs)
    except Exception as exc:
        error = exc
        if span is not None and hasattr(span, "record_exception"):
            try:
                span.record_exception(exc)
            except AttributeError as exc:
                logger.debug("Span record_exception failed: %s", exc)
    finally:
        duration = time.time() - start

        # ── Span cleanup ──────────────────────────────────
        if span is not None:
            try:
                if hasattr(span, "end"):
                    span.end()
                elif hasattr(span, "__exit__"):
                    span.__exit__(None, None, None)
            except AttributeError as exc:
                logger.debug("Span cleanup failed: %s", exc)

    # ── Post-call processing (only for successful calls) ─
    if error is not None:
        raise error

    # ── Extract telemetry ──────────────────────────────
    # Anthropic response uses: result.model, result.usage.input_tokens,
    # result.usage.output_tokens, result.content (list of blocks)
    usage: dict[str, int] = {}
    model_actual = model
    if result is not None:
        try:
            if hasattr(result, "model"):
                model_actual = result.model or model
            if hasattr(result, "usage") and result.usage:
                usage = {
                    "prompt_tokens": getattr(result.usage, "input_tokens", 0) or 0,
                    "completion_tokens": getattr(result.usage, "output_tokens", 0) or 0,
                    "total_tokens": (
                        (getattr(result.usage, "input_tokens", 0) or 0)
                        + (getattr(result.usage, "output_tokens", 0) or 0)
                    ),
                }
        except AttributeError as exc:
            logger.debug("Usage extraction failed: %s", exc)

    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)

    # ── Cost ───────────────────────────────────────────
    cost_usd = 0.0
    if config.auto_cost:
        try:
            cost_decimal = estimate_cost(
                "anthropic", model_actual, prompt_tokens, completion_tokens
            )
            cost_usd = float(cost_decimal)
        except (ValueError, TypeError) as exc:
            logger.debug("Cost estimation failed: %s", exc)

    # ── Span attributes ────────────────────────────────
    latency_ms = int(duration * 1000)
    if span is not None and hasattr(span, "set_attribute"):
        try:
            span.set_attribute("llm.provider", "anthropic")
            span.set_attribute("llm.model", model_actual)
            span.set_attribute("llm.request_tokens", prompt_tokens)
            span.set_attribute("llm.response_tokens", completion_tokens)
            span.set_attribute("llm.total_tokens", total_tokens)
            span.set_attribute("llm.latency_ms", latency_ms)
            span.set_attribute("llm.cost_usd", cost_usd)
        except AttributeError as exc:
            logger.debug("Span attribute setting failed: %s", exc)

    # ── Extract trace IDs ──────────────────────────────
    trace_id = ""
    span_id_str = ""
    if span is not None:
        try:
            ctx = span.get_span_context()
            if hasattr(ctx, "trace_id"):
                trace_id = format(ctx.trace_id, "032x")
            if hasattr(ctx, "span_id"):
                span_id_str = format(ctx.span_id, "016x")
        except AttributeError as exc:
            logger.debug("Trace/Span ID extraction failed: %s", exc)

    # ── Session / agent from kwargs ────────────────────
    session_id = str(kwargs.get("audit_session_id", kwargs.get("user", "")) or "")
    agent_id = str(kwargs.get("audit_agent_id", "") or "")
    event_id = None

    # ── Prepare bodies ─────────────────────────────────
    messages = kwargs.get("messages", [])
    request_body: dict | None = None
    if config.capture_request:
        body = {"messages": messages}
        if config.pii_redact:
            body["messages"] = _redact_messages(messages)
        request_body = body

    response_body: dict | None = None
    if config.capture_response and result is not None:
        try:
            resp_dict = result.model_dump() if hasattr(result, "model_dump") else None
            if resp_dict is None and hasattr(result, "to_dict"):
                resp_dict = result.to_dict()
            response_body = resp_dict
        except AttributeError as exc:
            logger.debug("Response body serialization failed: %s", exc)

    # ── Persist to llm_calls ───────────────────────────
    if db_available:
        try:
            _persist_llm_call(
                trace_id=trace_id,
                span_id=span_id_str,
                parent_span_id="",
                provider="anthropic",
                model=model_actual,
                request_tokens=prompt_tokens,
                response_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                request_body=request_body,
                response_body=response_body,
                session_id=session_id or None,
                agent_id=agent_id or None,
                event_id=event_id,
            )
        except (OSError, ValueError) as exc:
            logger.warning("llm_calls persist failed: %s", exc)

    # ── Audit trail ────────────────────────────────────
    if config.auto_audit and engine is not None:
        try:
            last_msg = messages[-1] if messages else {}
            content = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
            output_text = ""
            if result is not None and hasattr(result, "content"):
                output_text = _extract_content_text(result.content)[: config.max_prompt_len]

            engine.log(
                session_id=session_id or "default",
                event_type="model_request",
                agent_id=agent_id or "anthropic",
                prompt_version=kwargs.get("prompt_version", "unknown"),
                input_text=str(content)[: config.max_prompt_len],
                output_text=output_text,
                metadata={
                    "model": model_actual,
                    "tokens": total_tokens,
                    "latency_ms": latency_ms,
                    "cost_usd": cost_usd,
                    "trace_id": trace_id,
                    "span_id": span_id_str,
                },
            )
        except (OSError, ValueError) as exc:
            logger.warning("Audit trail log failed: %s", exc)

    return result
