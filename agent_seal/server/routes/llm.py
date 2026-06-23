"""
LLM tracing routes — view and control the LLM auto-tracing layer.

Endpoints:
    GET  /api/v1/llm/status       — current tracing status and configuration
    POST /api/v1/llm/enable       — enable auto-tracing
    POST /api/v1/llm/disable      — disable auto-tracing
    POST /api/v1/llm/log          — record an LLM call manually
    GET  /api/v1/llm/traces/{id}  — query calls by trace ID
    GET  /api/v1/llm/stats        — aggregate token/cost/latency statistics
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from ...config import config
from ...tracing.config import TraceConfig
from ..dependencies import llm_stats, query_llm_trace, store_llm_call

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


# ═══════════════════════ EXISTING ENDPOINTS ═══════════════════════════════


@router.get("/status")
async def llm_status():
    """Return current LLM tracing status and configuration."""
    trace_cfg = TraceConfig()

    return {
        "tracing": {
            "enabled": trace_cfg.auto_audit,
            "pii_redaction": trace_cfg.pii_redact,
            "auto_cost": trace_cfg.auto_cost,
            "max_prompt_len": trace_cfg.max_prompt_len,
            "cost_model": trace_cfg.cost_model,
            "capture_request": trace_cfg.capture_request,
            "capture_response": trace_cfg.capture_response,
        },
        "env_config": {
            "AGENT_SEAL_AUTO_TRACE": config.auto_trace,
            "AGENT_SEAL_TRACE_PII_REDACT": config.trace_pii_redact,
            "AGENT_SEAL_TRACE_MAX_LEN": config.trace_max_len,
            "AGENT_SEAL_TRACE_COST_MODEL": config.trace_cost_model,
        },
    }


@router.post("/enable")
async def llm_enable():
    """Enable LLM auto-tracing at runtime.

    This monkey-patches the OpenAI and Anthropic SDKs to intercept
    all LLM calls and log them to the audit trail.
    """
    from ...tracing.auto import install_auto_tracing
    from ..dependencies import get_engine

    try:
        engine = get_engine()
        installed = install_auto_tracing(engine=engine)
        if installed:
            return {"status": "ok", "message": "LLM tracing enabled"}
        return JSONResponse(
            {"status": "error", "message": "Failed to install tracing"},
            status_code=500,
        )
    except (OSError, ImportError) as exc:
        logger.exception("Failed to enable LLM tracing: %s", exc)
        return JSONResponse({"error": "enable failed", "detail": str(exc)}, status_code=500)


@router.post("/disable")
async def llm_disable():
    """Disable LLM auto-tracing.

    Note: this cannot fully un-monkey-patch the SDKs at runtime.
    The env var AGENT_SEAL_AUTO_TRACE must be set to 0 and the
    server restarted for a complete disable.
    """
    return {
        "status": "info",
        "message": (
            "LLM tracing cannot be fully disabled at runtime after monkey-patching. "
            "Set AGENT_SEAL_AUTO_TRACE=0 in .env and restart the server."
        ),
    }


# ═══════════════════════ LLM DATA ENDPOINTS ═══════════════════════════════


@router.post("/log")
async def llm_log(
    provider: str = Body(..., embed=True),
    model: str = Body(..., embed=True),
    trace_id: str = Body("", embed=True),
    span_id: str = Body("", embed=True),
    parent_span_id: str = Body("", embed=True),
    request_tokens: int = Body(0, embed=True),
    response_tokens: int = Body(0, embed=True),
    total_tokens: int = Body(0, embed=True),
    latency_ms: int = Body(0, embed=True),
    cost_usd: float = Body(0.0, embed=True),
    request_body: dict | None = Body(None, embed=True),
    response_body: dict | None = Body(None, embed=True),
    session_id: str = Body("", embed=True),
    agent_id: str = Body("", embed=True),
    event_id: str = Body("", embed=True),
):
    """Record an LLM call manually.

    This endpoint allows external systems to push LLM call telemetry
    into agent-seal for traceability and cost tracking.
    """
    timestamp = datetime.now(UTC).isoformat()

    # Auto-generate trace/span IDs if not provided
    import uuid

    if not trace_id:
        trace_id = uuid.uuid4().hex[:32]
    if not span_id:
        span_id = uuid.uuid4().hex[:16]

    call = {
        "provider": provider,
        "model": model,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "request_tokens": request_tokens,
        "response_tokens": response_tokens,
        "total_tokens": total_tokens or (request_tokens + response_tokens),
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "request_body": request_body,
        "response_body": response_body,
        "session_id": session_id,
        "agent_id": agent_id,
        "event_id": event_id,
        "timestamp": timestamp,
    }

    stored = store_llm_call(call)
    return stored


@router.get("/traces/{trace_id}")
async def llm_traces(trace_id: str):
    """Query all LLM calls belonging to a trace ID.

    Returns an ordered list of calls (by timestamp) that form the
    distributed trace, suitable for constructing a waterfall view.
    """
    calls = query_llm_trace(trace_id)
    if not calls:
        return JSONResponse(
            {"error": "trace not found", "trace_id": trace_id}, status_code=404
        )
    return {"trace_id": trace_id, "call_count": len(calls), "calls": calls}


@router.get("/stats")
async def llm_stats_endpoint():
    """Aggregate LLM usage statistics — tokens, cost, latency percentiles.

    Returns per-provider and per-model breakdowns in addition to
    global totals.
    """
    return llm_stats()
