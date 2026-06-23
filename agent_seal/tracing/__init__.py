"""
agent-seal tracing — zero-invasion LLM call interception and audit.

Module responsibilities:
    1. Monkey-patch OpenAI / Anthropic SDKs to intercept ``chat.completions.create``
       and ``messages.create``
    2. Emit OpenTelemetry spans for each LLM call (trace_id, span_id)
    3. Write structured records to the ``llm_calls`` table (SQLAlchemy ORM)
    4. Push an audit event into the AuditEngine hash chain
    5. Estimate USD cost per call using provider-specific pricing tables

Quick start (one-liner)::

    import agent_seal.tracing.auto  # noqa: F401

Controlled activation::

    from agent_seal.tracing import TraceConfig, OpenAIInstrumentor, AnthropicInstrumentor

    config = TraceConfig(auto_audit=True, pii_redact=True)

    # OpenAI
    instr = OpenAIInstrumentor(config, engine=my_engine)
    instr.install()

    # Anthropic
    instr2 = AnthropicInstrumentor(config, engine=my_engine)
    instr2.install()

Environment-variable activation::

    AGENT_SEAL_AUTO_TRACE=1
"""

from .anthropic import AnthropicInstrumentor as AnthropicInstrumentor
from .auto import install_auto_tracing
from .config import TraceConfig as TraceConfig
from .cost import (
    estimate_anthropic_cost,
    estimate_cost,
    estimate_deepseek_cost,
    estimate_openai_cost,
)
from .openai_instrumentor import OpenAIInstrumentor as OpenAIInstrumentor
from .opentelemetry import AuditSpanProcessor as AuditSpanProcessor

__all__ = [
    "AnthropicInstrumentor",
    "AuditSpanProcessor",
    "OpenAIInstrumentor",
    "TraceConfig",
    "estimate_anthropic_cost",
    "estimate_cost",
    "estimate_deepseek_cost",
    "estimate_openai_cost",
    "install_auto_tracing",
]
