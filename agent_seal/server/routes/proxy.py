"""
agent-seal LLM proxy — intercepts LLM API calls, logs to audit.db, forwards to provider.

URL pattern: /api/v1/proxy/{agent_id}/{path}
  agent_id → used for event attribution
  path     → forwarded to the real provider
"""
from __future__ import annotations

import json
import logging
import time
import os
from typing import Any

import httpx
from fastapi import APIRouter, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/proxy", tags=["proxy"])

# ── Resolve real API base from env ─────────────────────────────────────

_REAL_BASE = os.environ.get(
    "AGENT_SEAL_PROXY_BASE",
    "https://api.deepseek.com",
).rstrip("/")

# ── Lazy engine init ────────────────────────────────────────────────────

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        try:
            import sys
            sys.path.insert(0, os.environ.get(
                "AGENT_SEAL_PROJECT",
                "F:/workstation/projects/agent-seal",
            ))
            from agent_seal.engine import AuditEngine

            db_url = os.environ.get(
                "AGENT_SEAL_DB",
                "sqlite:///F:/workstation/projects/agent-seal/audit.db",
            )
            _engine = AuditEngine(db_url)
        except Exception as e:
            logger.warning("AuditEngine init failed: %s", e)
            _engine = False
    return _engine if _engine is not False else None


# ── Agent-resolved proxy route ──────────────────────────────────────────


@router.api_route("/{agent_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_request_with_agent(request: Request, agent_id: str, path: str):
    """Proxy route with agent_id embedded in URL path."""
    return await _proxy_core(request, path, agent_id)


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_request_legacy(request: Request, path: str):
    """Legacy route — agent_id from header or env."""
    agent_id = request.headers.get("x-agent-seal-agent-id", "")
    if not agent_id:
        agent_id = os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_AGENT_ID") or "unknown"
    return await _proxy_core(request, path, agent_id)


async def _proxy_core(request: Request, path: str, agent_id: str) -> Response:
    started = time.monotonic()

    # Read body
    try:
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8", errors="replace")[:4000]
    except Exception:
        body_bytes = b""
        body_text = ""

    # Build forwarded request
    target_url = f"{_REAL_BASE}/{path}"
    headers = dict(request.headers)
    for h in ("host", "transfer-encoding", "content-length"):
        headers.pop(h, None)

    # Forward
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body_bytes,
            )
        status_code = resp.status_code
        resp_body = resp.content
        resp_headers = dict(resp.headers)
        for h in ("transfer-encoding", "content-encoding", "content-length"):
            resp_headers.pop(h, None)
    except Exception as e:
        import traceback
        logger.error("Proxy forward failed: %s\n%s", e, traceback.format_exc())
        status_code = 502
        resp_body = json.dumps({"error": f"Proxy error: {e}"}).encode()
        resp_headers = {"content-type": "application/json"}

    elapsed = int((time.monotonic() - started) * 1000)

    # Log to audit
    engine = _get_engine()
    if engine:
        try:
            body_json = json.loads(body_text) if body_text else {}
            model = body_json.get("model", "?")
            msgs = body_json.get("messages", [])
            txt = ""
            if msgs and isinstance(msgs[-1], dict):
                txt = (msgs[-1].get("content", "") or "")[:200]
        except Exception:
            model = "?"
            txt = ""

        try:
            engine.log(
                session_id=f"proxy-{agent_id}",
                event_type="llm_request",
                agent_id=agent_id,
                prompt_version=model,
                input_text=txt,
                output_text=str(status_code),
                metadata={
                    "model": model,
                    "ms": elapsed,
                    "url": target_url[:80],
                    "method": request.method,
                },
            )
        except Exception:
            pass

    return Response(
        content=resp_body,
        status_code=status_code,
        headers=resp_headers,
    )
