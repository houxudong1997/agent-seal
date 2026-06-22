"""
Session routes — list all sessions and get session detail.

Includes v1 REST API endpoints and legacy compatibility wrappers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..dependencies import get_engine, safe_integrity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["sessions"])

# Separate router without the /api/v1 prefix for legacy compat
legacy_router = APIRouter(tags=["sessions-legacy"])


# ═══════════════════════ V1 ENDPOINTS ════════════════════════════════════


@router.get("/sessions")
async def api_sessions():
    """List all session IDs with summary stats."""
    engine = get_engine()
    sessions = engine.sessions()
    result = []
    for sid in sessions:
        events = engine.read(sid)
        if events:
            last = events[-1]
            result.append(
                {
                    "session_id": sid,
                    "event_count": len(events),
                    "last_event_type": last.get("event_type", ""),
                    "last_timestamp": last.get("timestamp", 0),
                    "agent_id": last.get("agent_id", ""),
                    "integrity": safe_integrity(engine, sid),
                }
            )
    return {"sessions": result}


@router.get("/sessions/{session_id}")
async def api_session_detail(session_id: str):
    """Full event list for a single session."""
    engine = get_engine()
    events = engine.read(session_id)
    if not events:
        return JSONResponse({"error": "session not found"}, status_code=404)
    integrity = safe_integrity(engine, session_id)
    return {
        "session_id": session_id,
        "event_count": len(events),
        "integrity": integrity,
        "events": events,
    }


@router.get("/sessions/{session_id}/events")
async def api_session_events(session_id: str):
    """List all events for a session (dedicated endpoint)."""
    engine = get_engine()
    events = engine.read(session_id)
    if not events:
        return JSONResponse({"error": "session not found"}, status_code=404)
    return {"session_id": session_id, "event_count": len(events), "events": events}


@router.get("/sessions/{session_id}/verify")
async def api_session_verify(session_id: str):
    """Verify the hash-chain integrity of a single session."""
    engine = get_engine()
    events = engine.read(session_id)
    if not events:
        return JSONResponse({"error": "session not found"}, status_code=404)
    result = safe_integrity(engine, session_id)
    return {"session_id": session_id, "integrity": result}


# ═══════════════════════ LEGACY COMPAT ═══════════════════════════════════


@legacy_router.get("/sessions")
async def legacy_sessions():
    """Legacy endpoint — redirects to v1."""
    return await api_sessions()


@legacy_router.get("/session/{session_id}")
async def legacy_session(session_id: str):
    """Legacy endpoint — redirects to v1."""
    return await api_session_detail(session_id)
