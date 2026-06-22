"""
Prompt versioning routes — expose the PromptRegistry via REST API.

Endpoints:
    GET  /api/v1/prompts                   — list all agents with prompt versions
    GET  /api/v1/prompts/{agent_id}         — get prompt history for an agent
    GET  /api/v1/prompts/{agent_id}/latest  — get latest prompt version
    GET  /api/v1/prompts/{agent_id}/diff    — unified diff between two versions
    POST /api/v1/prompts/{agent_id}         — save a new prompt version
    GET  /api/v1/prompts/{agent_id}/audit   — audit report for an agent
    POST /api/v1/prompts/verify             — verify all prompts haven't been tampered
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from ..dependencies import get_prompt_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


# ═══════════════════════ ENDPOINTS ═══════════════════════════════════════


@router.get("")
async def list_agents():
    """List all agents that have prompt versions, with version counts."""
    registry = get_prompt_registry()
    # Discover agents by scanning the cache keys
    agents: dict[str, int] = {}
    for key in registry._cache:
        agent_id = key.split(":", 1)[0]
        agents[agent_id] = agents.get(agent_id, 0) + 1

    return {
        "agents": [
            {
                "agent_id": agent_id,
                "version_count": count,
                "latest_version": _latest_version_id(registry, agent_id),
            }
            for agent_id, count in sorted(agents.items())
        ]
    }


@router.get("/{agent_id}")
async def get_history(agent_id: str):
    """Get the full prompt version history for an agent."""
    registry = get_prompt_registry()
    versions = registry.history(agent_id)
    if not versions:
        return JSONResponse({"error": "agent not found", "agent_id": agent_id}, status_code=404)

    return {
        "agent_id": agent_id,
        "total_versions": len(versions),
        "versions": [
            {
                "version_id": v.version_id,
                "changed_by": v.changed_by,
                "change_reason": v.change_reason,
                "timestamp": v.timestamp,
                "hash": v.hash,
                "prev_version": v.prev_version_id,
            }
            for v in versions
        ],
    }


@router.get("/{agent_id}/latest")
async def get_latest(agent_id: str):
    """Get the latest prompt version for an agent."""
    registry = get_prompt_registry()
    latest = registry.latest(agent_id)
    if latest is None:
        return JSONResponse({"error": "agent not found", "agent_id": agent_id}, status_code=404)

    return {
        "agent_id": agent_id,
        "version": {
            "version_id": latest.version_id,
            "prompt_text": latest.prompt_text,
            "changed_by": latest.changed_by,
            "change_reason": latest.change_reason,
            "timestamp": latest.timestamp,
            "hash": latest.hash,
            "prev_version": latest.prev_version_id,
        },
    }


@router.get("/{agent_id}/diff")
async def get_diff(
    agent_id: str,
    v1: str = Query(..., description="Source version ID (e.g. 'v1')"),
    v2: str = Query(..., description="Target version ID (e.g. 'v2')"),
):
    """Get a unified diff between two prompt versions."""
    registry = get_prompt_registry()
    diff_text = registry.diff(agent_id, v1, v2)
    return {"agent_id": agent_id, "v1": v1, "v2": v2, "diff": diff_text}


@router.post("/{agent_id}")
async def save_prompt(
    agent_id: str,
    prompt_text: str = Body(..., embed=True),
    changed_by: str = Body(..., embed=True),
    change_reason: str = Body(..., embed=True),
):
    """Save a new prompt version for an agent."""
    registry = get_prompt_registry()
    try:
        version = registry.save(
            agent_id=agent_id,
            prompt_text=prompt_text,
            changed_by=changed_by,
            change_reason=change_reason,
        )
    except (OSError, ValueError) as exc:
        logger.exception("Failed to save prompt for agent %s: %s", agent_id, exc)
        return JSONResponse({"error": "save failed", "detail": str(exc)}, status_code=500)

    return {
        "agent_id": agent_id,
        "version": {
            "version_id": version.version_id,
            "hash": version.hash,
            "changed_by": version.changed_by,
            "change_reason": version.change_reason,
            "timestamp": version.timestamp,
            "prev_version": version.prev_version_id,
        },
    }


@router.get("/{agent_id}/audit")
async def get_audit_report(agent_id: str):
    """Get a prompt version audit report for an agent."""
    registry = get_prompt_registry()
    report = registry.audit_report(agent_id)
    if report["total_versions"] == 0:
        return JSONResponse({"error": "agent not found", "agent_id": agent_id}, status_code=404)
    return report


@router.post("/verify")
async def verify_prompts():
    """Verify all stored prompts haven't been tampered with."""
    registry = get_prompt_registry()
    try:
        registry.verify()
        return {"status": "ok", "message": "All prompt versions verified"}
    except (OSError, ValueError) as exc:
        logger.exception("Prompt verification failed: %s", exc)
        return JSONResponse({"status": "broken", "error": str(exc)}, status_code=409)


# ── Helpers ──────────────────────────────────────────────────────────────


def _latest_version_id(registry, agent_id: str) -> str | None:
    """Get the latest version ID string for an agent, or None."""
    latest = registry.latest(agent_id)
    return latest.version_id if latest else None
