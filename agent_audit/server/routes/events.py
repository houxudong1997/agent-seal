"""
Event routes — logging, querying, SSE streaming, stats, and integrity verification.

Includes v1 REST API endpoints and legacy compatibility wrappers.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from ..dependencies import (
    get_engine,
    notify_stream_listeners,
    register_stream_listener,
    safe_integrity,
    unregister_stream_listener,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["events"])

# Also expose a separate router without the /api/v1 prefix for legacy compat
legacy_router = APIRouter(tags=["events-legacy"])


# ═══════════════════════ V1 ENDPOINTS ════════════════════════════════════


@router.get("/events/{event_id}")
async def api_event_detail(event_id: str):
    """Get a single audit event by its event_id."""
    engine = get_engine()
    # Scan sessions for the event — the storage layer doesn't support
    # direct event_id lookup, so we iterate sessions. This is acceptable
    # for moderate session counts; a production PostgreSQL backend would
    # use a SELECT by event_id directly.
    for sid in engine.sessions():
        events = engine.read(sid)
        for ev in events:
            if ev.get("event_id") == event_id:
                return ev
    return JSONResponse({"error": "event not found", "event_id": event_id}, status_code=404)


@router.get("/stats")
async def api_stats():
    """Aggregate statistics: total events, sessions, event types, integrity."""
    engine = get_engine()
    stats = engine.stats()
    # Add integrity check summary via safe helper
    integrity = "ok"
    for sid in engine.sessions():
        result = safe_integrity(engine, sid)
        if result == "broken":
            integrity = "broken"
            break
        if result == "unknown":
            integrity = "unknown"
    stats["integrity"] = integrity
    stats["agents"] = stats.get("agents", [])
    return stats


@router.get("/events")
async def api_events(
    session_id: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Query events with optional filters. Returns paginated results.

    Filters (session_id, event_type) are pushed down to the storage layer
    (SQL WHERE clauses for SQL-based backends) instead of loading every
    event into memory and filtering in Python — avoiding the O(n²) pattern.
    """
    engine = get_engine()
    events, total = engine.query(
        session_id=session_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return {"events": events, "total": total, "limit": limit, "offset": offset}


@router.get("/events/stream")
async def api_events_stream(request: Request):
    """Server-Sent Events endpoint — pushes new events in real time."""

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        register_stream_listener(queue)
        try:
            # Send initial connection event
            yield {
                "event": "connected",
                "data": json.dumps({"message": "Stream connected"}),
            }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {
                        "event": "new_event",
                        "data": json.dumps(event, default=str),
                    }
                except TimeoutError:
                    # Send keepalive ping
                    yield {"event": "ping", "data": ""}
        finally:
            unregister_stream_listener(queue)

    return EventSourceResponse(event_generator())


@router.post("/log")
async def api_log(request: Request):
    """Record a new audit event. Notifies SSE listeners."""
    engine = get_engine()
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        logger.exception("Failed to parse JSON in /api/v1/log: %s", exc)
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    event = engine.log(
        session_id=data.get("session_id", "default"),
        event_type=data.get("event_type", "unknown"),
        agent_id=data.get("agent_id", "unknown"),
        prompt_version=data.get("prompt_version", "v1"),
        input_text=data.get("input", ""),
        output_text=data.get("output", ""),
        metadata=data.get("metadata"),
    )

    result = {
        "event_id": event.event_id,
        "hash": event.hash[:16],
        "session_id": event.session_id,
        "sequence": event.sequence,
        "timestamp": event.timestamp,
        "event_type": event.event_type,
        "agent_id": event.agent_id,
        "prompt_version": event.prompt_version,
    }

    # Notify SSE stream listeners
    await notify_stream_listeners(result)

    return result


@router.post("/log/batch")
async def api_log_batch(request: Request):
    """Record multiple audit events in a single request.

    The request body must be a JSON array of event objects, each with
    the same fields as the single POST /api/v1/log endpoint.
    """
    engine = get_engine()
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        logger.exception("Failed to parse JSON in /api/v1/log/batch: %s", exc)
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    if not isinstance(data, list):
        return JSONResponse(
            {"error": "request body must be a JSON array of events"},
            status_code=400,
        )

    results = []
    for item in data:
        event = engine.log(
            session_id=item.get("session_id", "default"),
            event_type=item.get("event_type", "unknown"),
            agent_id=item.get("agent_id", "unknown"),
            prompt_version=item.get("prompt_version", "v1"),
            input_text=item.get("input", ""),
            output_text=item.get("output", ""),
            metadata=item.get("metadata"),
        )
        result = {
            "event_id": event.event_id,
            "hash": event.hash[:16],
            "session_id": event.session_id,
            "sequence": event.sequence,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "agent_id": event.agent_id,
            "prompt_version": event.prompt_version,
        }
        results.append(result)
        # Notify SSE stream listeners
        await notify_stream_listeners(result)

    return {"events": results, "count": len(results)}


@router.post("/verify")
async def api_verify(request: Request):
    """Verify integrity — global or per-session."""
    engine = get_engine()
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        logger.exception("Failed to parse JSON in /api/v1/verify: %s", exc)
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    session_id = data.get("session_id", "")
    if session_id:
        result = safe_integrity(engine, session_id)
        return {"integrity": result, "session_id": session_id}
    # Global verify
    sessions = engine.sessions()
    results = {}
    all_ok = True
    for sid in sessions:
        result = safe_integrity(engine, sid)
        results[sid] = result
        if result == "broken":
            all_ok = False
    return {"integrity": "ok" if all_ok else "broken", "sessions": results}


# ═══════════════════════ LEGACY COMPAT ═══════════════════════════════════
# Thin wrappers that delegate to v1 handlers.  Kept here so the events
# module owns its full routing surface, past and present.


@legacy_router.get("/api/stats")
async def legacy_stats():
    """Legacy endpoint — redirects to v1."""
    return await api_stats()


@legacy_router.get("/api/events")
async def legacy_events():
    """Legacy endpoint — redirects to v1."""
    return await api_events(limit=20)


@legacy_router.post("/log")
async def legacy_log(request: Request):
    """Legacy endpoint — redirects to v1."""
    return await api_log(request)


@legacy_router.post("/verify")
async def legacy_verify(request: Request):
    """Legacy endpoint — redirects to v1."""
    return await api_verify(request)
