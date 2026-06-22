"""
Admin routes — health checks, metrics, dashboard, and static assets.

Endpoints:
    GET /              — SPA dashboard
    GET /health        — health check
    GET /ready         — readiness probe
    GET /metrics       — Prometheus metrics
    GET /favicon.svg   — favicon
    GET /icons.svg     — SVG icons sprite
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)

from ..dependencies import (
    get_engine,
    get_static_dir,
    load_dashboard_html,
)
from ..metrics import generate as metrics_generate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


# ═══════════════════════ HEALTH & READINESS ══════════════════════════════


@router.get("/health")
async def health():
    """Liveness probe — always returns ok if the server is running."""
    return {"status": "ok", "version": "1.0.0"}


@router.get("/ready")
async def ready():
    """Readiness probe — verifies the database is accessible."""
    try:
        get_engine().stats()
        return {"status": "ready"}
    except (OSError, ValueError) as e:
        return JSONResponse({"status": "not_ready", "error": str(e)}, status_code=503)


@router.get("/metrics")
async def metrics():
    """Prometheus-format metrics endpoint.

    Aggregates business-level metrics (events, sessions, policy
    decisions) and request-level metrics (when
    prometheus-fastapi-instrumentator is active) into a single
    scrape text output.
    """
    return PlainTextResponse(metrics_generate())


# ═══════════════════════ DASHBOARD ═══════════════════════════════════════


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the SPA dashboard."""
    return HTMLResponse(load_dashboard_html())


# ═══════════════════════ STATIC ASSETS ═══════════════════════════════════

static_dir = get_static_dir()


@router.get("/favicon.svg")
async def serve_favicon():
    """Serve the favicon."""
    from fastapi.responses import FileResponse

    favicon = static_dir / "favicon.svg"
    if favicon.exists():
        return FileResponse(favicon)
    return JSONResponse({"error": "not found"}, status_code=404)


@router.get("/icons.svg")
async def serve_icons():
    """Serve the SVG icons sprite."""
    from fastapi.responses import FileResponse

    icons = static_dir / "icons.svg"
    if icons.exists():
        return FileResponse(icons)
    return JSONResponse({"error": "not found"}, status_code=404)
