"""
OpenTelemetry bridging — AuditSpanProcessor + OTel SDK helpers.

Provides a custom ``SpanProcessor`` that funnels OTel spans into the
agent-audit pipeline (``llm_calls`` table + audit trail hash-chain).

This is the *long-term* integration path per architecture-v1.md §4.2.
For the immediate monkey-patch approach see ``openai_instrumentor.py``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.storage import AuditEngine

logger = logging.getLogger("agent_audit.tracing.otel")


class AuditSpanProcessor:
    """Bridge between OpenTelemetry spans and agent-audit storage.

    For each completed span the processor:

    1. Inspects ``llm.*`` attributes — if present, treats the span
       as an LLM call and persists to ``llm_calls``.
    2. If ``audit.enabled`` is True on the span, also pushes an event
       into the audit trail hash-chain.

    Usage::

        from opentelemetry.sdk.trace import TracerProvider
        from agent_audit.tracing import AuditSpanProcessor

        provider = TracerProvider()
        provider.add_span_processor(AuditSpanProcessor(engine=my_engine))
        trace.set_tracer_provider(provider)
    """

    def __init__(
        self,
        engine: AuditEngine | None = None,
        *,
        auto_audit: bool = True,
        auto_cost: bool = True,
        cost_model: str = "openai",
    ):
        self.engine = engine
        self.auto_audit = auto_audit
        self.auto_cost = auto_cost
        self.cost_model = cost_model

    # ── OTel SpanProcessor interface ───────────────────────────

    def on_start(self, span: Any, parent_context: Any | None = None) -> None:
        pass

    def on_end(self, span: Any) -> None:
        try:
            self._process_span(span)
        except Exception as exc:
            logger.warning("AuditSpanProcessor.on_end failed: %s", exc)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    # ── Internal ───────────────────────────────────────────────

    def _process_span(self, span: Any) -> None:
        attrs = self._get_attributes(span)
        model = attrs.get("llm.model")
        if not model:
            return

        provider = attrs.get("llm.provider", "unknown")
        trace_id = self._get_trace_id(span)
        span_id = self._get_span_id(span)
        parent_span_id = self._get_parent_span_id(span)

        request_tokens = int(attrs.get("llm.request_tokens", 0))
        response_tokens = int(attrs.get("llm.response_tokens", 0))
        total_tokens = int(attrs.get("llm.total_tokens", 0))
        latency_ms = int(attrs.get("llm.latency_ms", 0))

        cost_usd = 0.0
        if self.auto_cost:
            try:
                from .cost import estimate_cost

                cost_decimal = estimate_cost(provider, model, request_tokens, response_tokens)
                cost_usd = float(cost_decimal)
            except Exception as exc:
                logger.debug("Cost estimation skipped: %s", exc)

        # Persist to llm_calls (best-effort)
        try:
            from .openai_instrumentor import _persist_llm_call

            _persist_llm_call(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                provider=provider,
                model=model,
                request_tokens=request_tokens,
                response_tokens=response_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                request_body=attrs.get("llm.request_body"),
                response_body=attrs.get("llm.response_body"),
                session_id=attrs.get("session.id"),
                agent_id=attrs.get("agent.id"),
                event_id=None,
            )
        except Exception as exc:
            logger.debug("Failed to persist LLM call: %s", exc)

        # Audit trail
        if self.auto_audit and self.engine is not None:
            audit_enabled = str(attrs.get("audit.enabled", "true")).lower() in (
                "1",
                "true",
                "yes",
            )
            if audit_enabled:
                try:
                    self.engine.log(
                        session_id=attrs.get("session.id", "default"),
                        event_type="model_request",
                        agent_id=attrs.get("agent.id", provider),
                        prompt_version=attrs.get("prompt.version", "unknown"),
                        input_text=str(attrs.get("llm.input", ""))[:4000],
                        output_text=str(attrs.get("llm.output", ""))[:4000],
                        metadata={
                            "model": model,
                            "tokens": total_tokens,
                            "latency_ms": latency_ms,
                            "cost_usd": cost_usd,
                            "trace_id": trace_id,
                            "span_id": span_id,
                        },
                    )
                except Exception as exc:
                    logger.exception("Audit trail log failed: %s", exc)

    # ── Attribute extraction (duck-typed) ──────────────────────

    @staticmethod
    def _get_attributes(span: Any) -> dict[Any, Any]:
        if isinstance(span, dict):
            return dict(span.get("attributes", span))
        if hasattr(span, "attributes") and isinstance(span.attributes, dict):
            return span.attributes
        return {}

    @staticmethod
    def _get_trace_id(span: Any) -> str:
        if isinstance(span, dict):
            return str(span.get("trace_id", ""))
        try:
            ctx = span.get_span_context()
            return format(ctx.trace_id, "032x")
        except Exception as exc:
            logger.debug("Trace ID extraction failed: %s", exc)
            return ""

    @staticmethod
    def _get_span_id(span: Any) -> str:
        if isinstance(span, dict):
            return str(span.get("span_id", ""))
        try:
            ctx = span.get_span_context()
            return format(ctx.span_id, "016x")
        except Exception as exc:
            logger.debug("Span ID extraction failed: %s", exc)
            return ""

    @staticmethod
    def _get_parent_span_id(span: Any) -> str:
        if isinstance(span, dict):
            return str(span.get("parent_span_id", ""))
        try:
            if span.parent:
                ctx = span.parent.get_span_context()
                return format(ctx.span_id, "016x")
        except Exception as exc:
            logger.debug("Parent span ID extraction failed: %s", exc)
        return ""


def create_span_processor(
    engine: AuditEngine,
    *,
    auto_audit: bool = True,
    auto_cost: bool = True,
) -> AuditSpanProcessor:
    """Create an ``AuditSpanProcessor`` wired to *engine*."""
    return AuditSpanProcessor(engine=engine, auto_audit=auto_audit, auto_cost=auto_cost)
