"""
OpenAI auto-instrumentor — intercepts ``openai.chat.completions.create``.

Monkey-patches the OpenAI Python SDK (>=1.0) so that every chat completion
is automatically wrapped in an OpenTelemetry span, recorded in the
``llm_calls`` table (SQLAlchemy), and pushed to the agent-seal hash-chain.
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

logger = logging.getLogger("agent_seal.tracing.openai")


class OpenAIInstrumentor:
    """Monkey-patch ``openai.chat.completions.create`` for audit tracing.

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

        instr = OpenAIInstrumentor(config, engine=engine)
        instr.install()

        import openai
        resp = openai.chat.completions.create(model="gpt-4o", messages=[...])
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
            logger.debug("OpenAIInstrumentor already installed — skipping")
            return

        try:
            import openai
        except ImportError:
            logger.warning("openai package not installed — OpenAIInstrumentor.install() is a no-op")
            return

        original = openai.chat.completions.create
        config = self.config
        engine = self.engine
        _tracer = self._tracer
        _db_available = self._check_db_available()

        @wraps(original)
        def traced_create(*args: Any, **kwargs: Any) -> Any:
            return _trace_call(
                original=original,
                args=args,
                kwargs=kwargs,
                config=config,
                engine=engine,
                tracer=_tracer,
                db_available=_db_available,
            )

        openai.chat.completions.create = traced_create
        self._original_create = original
        self._installed = True
        logger.info("OpenAIInstrumentor installed — all chat.completions.create calls traced")

    def uninstall(self) -> None:
        """Restore the original ``openai.chat.completions.create``."""
        if not self._installed or self._original_create is None:
            return
        try:
            import openai
        except ImportError:
            return
        openai.chat.completions.create = self._original_create
        self._installed = False
        self._original_create = None
        logger.info("OpenAIInstrumentor uninstalled")

    @staticmethod
    def _check_db_available() -> bool:
        try:
            from ..config import config as app_cfg

            if app_cfg.db_url:
                return True
        except Exception as exc:
            logger.debug("DB availability check failed: %s", exc)
        return False


# ── Shared persistence helper ────────────────────────────────────

_orm_engine = None


def _persist_llm_call(
    *,
    trace_id: str,
    span_id: str,
    parent_span_id: str,
    provider: str,
    model: str,
    request_tokens: int,
    response_tokens: int,
    total_tokens: int,
    latency_ms: int,
    cost_usd: float,
    request_body: dict | None,
    response_body: dict | None,
    session_id: str | None,
    agent_id: str | None,
    event_id: str | None,
) -> None:
    """Write a row to the ``llm_calls`` table via SQLAlchemy ORM.

    Silently skips when DB is not configured (no-op).
    """
    try:
        from decimal import Decimal

        from ..models.llm_call import LLMCall
    except Exception as exc:
        logger.debug("LLMCall model not importable — skip DB write: %s", exc)
        return

    try:
        from sqlalchemy.orm import Session as SASession

        from ..config import config as app_cfg

        db_url = app_cfg.db_url
        if not db_url:
            logger.debug("AGENT_SEAL_DB_URL not set — skipping llm_calls write")
            return

        global _orm_engine
        if _orm_engine is None:
            from sqlalchemy import create_engine

            _orm_engine = create_engine(db_url, pool_size=5, max_overflow=10)

        with SASession(_orm_engine) as session:
            call = LLMCall(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                provider=provider,
                model=model,
                request_tokens=request_tokens,
                response_tokens=response_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                cost_usd=Decimal(str(cost_usd)),
                request_body=request_body,
                response_body=response_body,
                session_id=session_id,
                agent_id=agent_id,
                event_id=event_id,
            )
            session.add(call)
            session.commit()
    except Exception as exc:
        logger.warning("Failed to persist LLM call: %s", exc)


def _redact_messages(messages: Any) -> Any:
    """Strip PII from message content (basic truncation-based implementation)."""
    if not isinstance(messages, list):
        return messages
    redacted = []
    for msg in messages:
        if not isinstance(msg, dict):
            redacted.append(msg)
            continue
        copy = dict(msg)
        content = copy.get("content", "")
        if isinstance(content, str) and len(content) > 2000:
            copy["content"] = content[:1997] + "..."
        redacted.append(copy)
    return redacted


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


def _trace_call(
    *,
    original: Any,
    args: tuple,
    kwargs: dict,
    config: TraceConfig,
    engine: AuditEngine | None,
    tracer: Any,
    db_available: bool,
) -> Any:
    """Core interception logic for a single ``chat.completions.create`` call."""

    tracer = _resolve_tracer(tracer)
    model = kwargs.get("model", "unknown")
    span_name = f"{config.span_prefix}/{model}"

    span = None
    if tracer is not None:
        try:
            span = tracer.start_span(span_name)
            if span is not None and hasattr(span, "__enter__"):
                span.__enter__()
        except Exception as exc:
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
            except Exception as exc:
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
            except Exception as exc:
                logger.debug("Span cleanup failed: %s", exc)

    # ── Post-call processing (only for successful calls) ─
    if error is not None:
        raise error

    # ── Extract telemetry ──────────────────────────────
    usage: dict[str, int] = {}
    model_actual = model
    if result is not None:
        try:
            if hasattr(result, "model"):
                model_actual = result.model or model
            if hasattr(result, "usage") and result.usage:
                usage = {
                    "prompt_tokens": getattr(result.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(result.usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(result.usage, "total_tokens", 0) or 0,
                }
        except Exception as exc:
            logger.debug("Usage extraction failed: %s", exc)

    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)

    # ── Cost ───────────────────────────────────────────
    cost_usd = 0.0
    if config.auto_cost:
        try:
            cost_decimal = estimate_cost("openai", model_actual, prompt_tokens, completion_tokens)
            cost_usd = float(cost_decimal)
        except Exception as exc:
            logger.debug("Cost estimation failed: %s", exc)

    # ── Span attributes ────────────────────────────────
    latency_ms = int(duration * 1000)
    if span is not None and hasattr(span, "set_attribute"):
        try:
            span.set_attribute("llm.provider", "openai")
            span.set_attribute("llm.model", model_actual)
            span.set_attribute("llm.request_tokens", prompt_tokens)
            span.set_attribute("llm.response_tokens", completion_tokens)
            span.set_attribute("llm.total_tokens", total_tokens)
            span.set_attribute("llm.latency_ms", latency_ms)
            span.set_attribute("llm.cost_usd", cost_usd)
        except Exception as exc:
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
        except Exception as exc:
            logger.debug("Trace ID extraction failed: %s", exc)

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
        except Exception as exc:
            logger.debug("Response body serialization failed: %s", exc)

    # ── Persist to llm_calls ───────────────────────────
    if db_available:
        try:
            _persist_llm_call(
                trace_id=trace_id,
                span_id=span_id_str,
                parent_span_id="",
                provider="openai",
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
        except Exception as exc:
            logger.warning("llm_calls persist failed: %s", exc)

    # ── Audit trail ────────────────────────────────────
    if config.auto_audit and engine is not None:
        try:
            last_msg = messages[-1] if messages else {}
            content = last_msg.get("content", "") if isinstance(last_msg, dict) else str(last_msg)
            output_text = ""
            if result is not None and hasattr(result, "choices") and result.choices:
                output_text = str(result.choices[0].message.content or "")[: config.max_prompt_len]

            engine.log(
                session_id=session_id or "default",
                event_type="model_request",
                agent_id=agent_id or "openai",
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
        except Exception as exc:
            logger.warning("Audit trail log failed: %s", exc)

    return result
