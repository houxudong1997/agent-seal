"""
TraceConfig — runtime configuration for the tracing layer.

Most fields are sourced from AGENT_SEAL_TRACE_* env vars and can be
overridden per-instrumentor for fine-grained control.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import config as _app_config


@dataclass
class TraceConfig:
    """Configuration for an OpenAI / Anthropic instrumentor.

    Defaults are read from the application-wide ``Config`` singleton
    (``AGENT_SEAL_*`` environment variables).  Every field can be
    overridden at construction time.
    """

    auto_audit: bool = field(
        default_factory=lambda: _app_config.auto_trace,
    )
    """If True, also record an audit trail event via ``engine.log()``
    for every intercepted LLM call."""

    auto_cost: bool = True
    """If True, estimate USD cost from token usage."""

    pii_redact: bool = field(
        default_factory=lambda: _app_config.trace_pii_redact,
    )
    """If True, strip known PII patterns from request / response bodies."""

    max_prompt_len: int = field(
        default_factory=lambda: _app_config.trace_max_len,
    )
    """Maximum characters to store for prompt / response text (0 = no limit)."""

    cost_model: str = field(
        default_factory=lambda: _app_config.trace_cost_model,
    )
    """Cost estimation provider: 'openai', 'anthropic', 'deepseek'."""

    span_prefix: str = "llm"
    """Prefix applied to OTel span names, e.g. ``llm/gpt-4``."""

    capture_request: bool = True
    """Store the request body in the llm_calls row."""

    capture_response: bool = True
    """Store the response body in the llm_calls row."""
