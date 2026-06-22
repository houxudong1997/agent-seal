"""
Hermes middleware — captures agent-audit events from Hermes agent interactions.

This FastAPI middleware intercepts requests routed through agent-audit's
FastAPI server and records audit events for Hermes agent activity.

Features:
  - Intercepts requests to LLM API endpoints and records them
  - Maps agent_id from environment variables (HERMES_AGENT_ID)
  - Communicates with agent-audit's own AuditEngine for recording
  - Graceful degradation when AuditEngine is unavailable

Usage::

    from agent_audit.server.hermes_middleware import HermesAuditMiddleware

    app.add_middleware(HermesAuditMiddleware, engine=my_engine)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


def _resolve_agent_id() -> str:
    """Resolve the Hermes agent ID from environment variables.

    Priority:
        1. AGENT_AUDIT_HERMES_AGENT_ID
        2. HERMES_AGENT_ID
        3. HERMES_PROFILE
        4. "unknown-hermes-agent" (fallback)
    """
    return (
        os.environ.get("AGENT_AUDIT_HERMES_AGENT_ID")
        or os.environ.get("HERMES_AGENT_ID")
        or os.environ.get("HERMES_PROFILE", "unknown-hermes-agent")
    )


def _is_llm_endpoint(path: str) -> bool:
    """Check if a path corresponds to an LLM API endpoint."""
    llm_patterns = (
        "/v1/chat/completions",
        "/v1/completions",
        "/v1/embeddings",
        "/chat/completions",
        "/completions",
        "/v1/messages",  # Anthropic
    )
    return any(pattern in path for pattern in llm_patterns)


class HermesAuditMiddleware(BaseHTTPMiddleware):
    """Starlette/FastAPI middleware that captures Hermes agent audit events.

    Records:
      - Request method, path, and summary
      - Response status code
      - Duration
      - Agent ID (from environment or config)
    """

    def __init__(
        self,
        app: Any,
        engine: Any = None,
        agent_id: str | None = None,
        capture_request_body: bool = True,
        capture_response_body: bool = False,
        max_body_len: int = 2000,
    ):
        super().__init__(app)
        self._engine = engine
        self._agent_id = agent_id or _resolve_agent_id()
        self._capture_request_body = capture_request_body
        self._capture_response_body = capture_response_body
        self._max_body_len = max_body_len

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only intercept /api/* paths
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        started = time.monotonic()

        # Capture request body (can only be read once)
        request_body = None
        if self._capture_request_body:
            try:
                body_bytes = await request.body()
                request_body = body_bytes.decode("utf-8", errors="replace")[: self._max_body_len]
            except Exception:
                request_body = "<unreadable>"

        response = await call_next(request)

        elapsed = time.monotonic() - started

        self._record(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration=elapsed,
            request_body=request_body or "",
            is_llm=_is_llm_endpoint(request.url.path),
        )

        return response

    def _record(
        self,
        method: str,
        path: str,
        status_code: int,
        duration: float,
        request_body: str,
        is_llm: bool,
    ) -> None:
        """Record the request/response pair to the audit engine."""
        if self._engine is None:
            logger.debug("HermesAuditMiddleware: no engine configured, skipping")
            return

        event_type = "llm_request" if is_llm else "api_request"
        session_id = f"hermes-{self._agent_id}"

        metadata = {
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration * 1000, 2),
            "is_llm": is_llm,
        }

        try:
            self._engine.log(
                session_id=session_id,
                event_type=event_type,
                agent_id=self._agent_id,
                prompt_version="hermes-v1",
                input_text=request_body[:500],
                output_text=f"HTTP {status_code} on {method} {path}",
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("HermesAuditMiddleware: failed to record event: %s", exc)
