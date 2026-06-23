"""
agent-seal FastAPI application — SPA Dashboard + REST API + SSE streaming.

Routes are organized into the ``routes/`` package:

    routes/admin      — /health, /ready, /metrics, / (dashboard), static assets
    routes/events     — /api/v1/events, /api/v1/stats, /api/v1/log, /api/v1/verify, SSE
    routes/sessions   — /api/v1/sessions, /api/v1/sessions/{id}
    routes/agents     — /api/v1/agents, /api/v1/agents/{id}/stats
    routes/prompts    — /api/v1/prompts  (prompt versioning API)
    routes/policy     — /api/v1/policy/rules, /api/v1/policy/evaluate
    routes/evidence   — /api/v1/evidence/export
    routes/compliance — /api/v1/compliance (EU AI Act reports)
    routes/llm        — /api/v1/llm  (LLM tracing, log, traces, stats)

Usage:
    uvicorn agent_seal.server.app:app --host 0.0.0.0 --port 8081
    or: agent-seal serve
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .dependencies import get_static_dir
from .middlewares import setup_all
from .routes import (
    admin_router,
    agents_router,
    compliance_router,
    events_legacy_router,
    events_router,
    evidence_router,
    llm_router,
    policy_router,
    prompts_router,
    sessions_legacy_router,
    sessions_router,
)

logger = logging.getLogger(__name__)

# ── App factory ──────────────────────────────────────────────────────────

app = FastAPI(
    title="agent-seal API",
    version="1.0.0",
    description="Tamper-evident audit trail for AI agents — EU AI Act ready",
)

# ── Middleware stack ─────────────────────────────────────────────────────
# CORS + GZip + API Key auth + Prometheus (see server/middlewares.py)

setup_all(app)

# ── Route registration ──────────────────────────────────────────────────
# Order matters: more specific routes should be registered before less
# specific ones so FastAPI's route resolution picks the right handler.

# API v1 domain routers (each handles its own prefixed routes)
app.include_router(events_router)
app.include_router(sessions_router)
app.include_router(agents_router)
app.include_router(prompts_router)
app.include_router(policy_router)
app.include_router(evidence_router)
app.include_router(compliance_router)
app.include_router(llm_router)

# Legacy compat routers (unprefixed, thin wrappers around v1)
app.include_router(events_legacy_router)
app.include_router(sessions_legacy_router)

# Admin / dashboard (unprefixed — handles /, /health, /ready, /metrics, favicon)
app.include_router(admin_router)

# ── Static assets mount ─────────────────────────────────────────────────
# Mounted after route registration so API routes take precedence over
# filesystem paths.

static_dir = get_static_dir()
if (static_dir / "assets").exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(static_dir / "assets")),
        name="spa_assets",
    )
