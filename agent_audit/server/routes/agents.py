"""
Agent routes — list known agents and get per-agent statistics.

Endpoints:
    GET /api/v1/agents            — list all agents with event counts
    GET /api/v1/agents/{id}/stats — per-agent aggregated statistics
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..dependencies import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["agents"])


# ═══════════════════════ ENDPOINTS ═══════════════════════════════════════


@router.get("/agents")
async def api_agents():
    """List all known agent IDs with event counts and last-seen timestamps."""
    engine = get_engine()
    agents: dict[str, dict] = {}

    for sid in engine.sessions():
        events = engine.read(sid)
        for ev in events:
            agent_id = ev.get("agent_id", "unknown")
            if agent_id not in agents:
                agents[agent_id] = {
                    "agent_id": agent_id,
                    "event_count": 0,
                    "session_count": 0,
                    "last_timestamp": 0,
                    "sessions": set(),
                }
            agents[agent_id]["event_count"] += 1
            agents[agent_id]["sessions"].add(sid)
            ts = ev.get("timestamp", 0)
            if isinstance(ts, (int, float)) and ts > agents[agent_id]["last_timestamp"]:
                agents[agent_id]["last_timestamp"] = ts

    result = []
    for entry in agents.values():
        entry["session_count"] = len(entry.pop("sessions"))
        result.append(entry)

    # Sort by event_count descending
    result.sort(key=lambda a: a["event_count"], reverse=True)
    return {"agents": result}


@router.get("/agents/{agent_id}/stats")
async def api_agent_stats(agent_id: str):
    """Get aggregated statistics for a specific agent.

    Returns event counts by type, session list, and integrity status
    for all sessions the agent participated in.
    """
    engine = get_engine()
    event_types: dict[str, int] = {}
    sessions: list[dict] = []
    total_events = 0
    found = False

    for sid in engine.sessions():
        events = engine.read(sid)
        agent_events = [e for e in events if e.get("agent_id") == agent_id]
        if not agent_events:
            continue
        found = True
        total_events += len(agent_events)

        for ev in agent_events:
            et = ev.get("event_type", "unknown")
            event_types[et] = event_types.get(et, 0) + 1

        from ..dependencies import safe_integrity

        sessions.append(
            {
                "session_id": sid,
                "event_count": len(agent_events),
                "integrity": safe_integrity(engine, sid),
            }
        )

    if not found:
        return JSONResponse(
            {"error": "agent not found", "agent_id": agent_id}, status_code=404
        )

    return {
        "agent_id": agent_id,
        "total_events": total_events,
        "sessions": len(sessions),
        "event_types": event_types,
        "session_list": sessions,
    }
