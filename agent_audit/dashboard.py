"""
DEPRECATED — Simple web dashboard for agent audit trails.

The Svelte SPA dashboard is now served by the FastAPI server (server/app.py).
Start with: agent-audit serve
Or: uvicorn agent_audit.server.app:app --host 0.0.0.0 --port 8081

This module is kept for backward compatibility.  Its serve() function
starts the FastAPI-based SPA server instead of the legacy http.server.
"""

import logging

from .config import config

logger = logging.getLogger(__name__)


def serve(port: int | None = None):
    """Start the dashboard web server (FastAPI + Svelte SPA)."""
    import uvicorn

    port = port or config.api_port
    host = config.api_host
    logger.info("Agent Audit Dashboard (FastAPI + Svelte SPA)")
    logger.info("Open: http://%s:%s", host, port)
    uvicorn.run(
        "agent_audit.server.app:app",
        host=host,
        port=port,
        log_level=config.log_level.lower(),
    )
