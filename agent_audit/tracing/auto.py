"""
Auto-tracing entry point — one import, all LLM calls traced.

Usage::

    import agent_audit.tracing.auto  # noqa: F401

Respects the ``AGENT_AUDIT_AUTO_TRACE`` environment variable.
When ``1``/``true``/``yes``/``on``, the instrumentor is activated
at import time; otherwise a no-op until ``install_auto_tracing()``
is called explicitly.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.storage import AuditEngine

logger = logging.getLogger("agent_audit.tracing.auto")

_OPENAI_INSTALLED = False
_ANTHROPIC_INSTALLED = False


def install_auto_tracing(engine: AuditEngine | None = None) -> bool:
    """One-shot activation: install the OpenAI instrumentor globally.

    Args:
        engine: Optional ``AuditEngine`` instance for audit trail logging.

    Returns:
        ``True`` if installed (or already installed), ``False`` on error.
    """
    global _OPENAI_INSTALLED
    if _OPENAI_INSTALLED:
        logger.debug("Auto-tracing (OpenAI) already installed")
        return True

    from ..config import config as app_cfg
    from .config import TraceConfig
    from .openai_instrumentor import OpenAIInstrumentor

    config = TraceConfig(
        auto_audit=app_cfg.auto_trace,
        auto_cost=True,
        pii_redact=app_cfg.trace_pii_redact,
        max_prompt_len=app_cfg.trace_max_len,
        cost_model=app_cfg.trace_cost_model,
    )

    instr = OpenAIInstrumentor(config=config, engine=engine)

    try:
        instr.install()
    except Exception as exc:
        logger.warning("Auto-tracing install failed: %s", exc)
        return False

    _OPENAI_INSTALLED = True
    return True


def install_auto_anthropic_tracing(engine: AuditEngine | None = None) -> bool:
    """One-shot activation: install the Anthropic instrumentor globally.

    Args:
        engine: Optional ``AuditEngine`` instance for audit trail logging.

    Returns:
        ``True`` if installed (or already installed), ``False`` on error.
    """
    global _ANTHROPIC_INSTALLED
    if _ANTHROPIC_INSTALLED:
        logger.debug("Auto-tracing (Anthropic) already installed")
        return True

    from ..config import config as app_cfg
    from .anthropic import AnthropicInstrumentor
    from .config import TraceConfig

    config = TraceConfig(
        auto_audit=app_cfg.auto_trace,
        auto_cost=True,
        pii_redact=app_cfg.trace_pii_redact,
        max_prompt_len=app_cfg.trace_max_len,
        cost_model=app_cfg.trace_cost_model,
    )

    instr = AnthropicInstrumentor(config=config, engine=engine)

    try:
        instr.install()
    except Exception as exc:
        logger.warning("Auto-Anthropic-tracing install failed: %s", exc)
        return False

    _ANTHROPIC_INSTALLED = True
    return True


def _auto_enabled() -> bool:
    val = os.getenv("AGENT_AUDIT_AUTO_TRACE", "").strip().lower()
    return val in ("1", "true", "yes", "on")


if _auto_enabled():
    install_auto_tracing()
    install_auto_anthropic_tracing()
