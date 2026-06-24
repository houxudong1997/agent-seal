"""
Route modules for the agent-seal FastAPI server.

Each sub-module exposes one or more APIRouter instances that are
mounted on the main FastAPI app in app.py.

Modules:
    admin      — /health, /ready, /metrics, / (dashboard), static assets
    events     — /api/v1/events, /api/v1/stats, /api/v1/log, /api/v1/verify, SSE
    sessions   — /api/v1/sessions, /api/v1/sessions/{id}
    agents     — /api/v1/agents, /api/v1/agents/{id}/stats
    prompts    — /api/v1/prompts  (prompt versioning API)
    policy     — /api/v1/policy/rules, /api/v1/policy/evaluate
    evidence   — /api/v1/evidence/export
    compliance — /api/v1/compliance (EU AI Act reports)
    llm        — /api/v1/llm  (LLM tracing control, log, traces, stats)
"""

from .admin import router as admin_router
from .agents import router as agents_router
from .compliance import router as compliance_router
from .events import legacy_router as events_legacy_router
from .events import router as events_router
from .evidence import router as evidence_router
from .llm import router as llm_router
from .policy import router as policy_router
from .prompts import router as prompts_router
from .proxy import router as proxy_router
from .sessions import legacy_router as sessions_legacy_router
from .sessions import router as sessions_router

__all__ = [
    "admin_router",
    "agents_router",
    "compliance_router",
    "events_legacy_router",
    "events_router",
    "evidence_router",
    "llm_router",
    "policy_router",
    "prompts_router",
    "proxy_router",
    "sessions_legacy_router",
    "sessions_router",
]
