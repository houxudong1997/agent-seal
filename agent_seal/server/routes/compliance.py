"""
Compliance routes — EU AI Act compliance report generation and evidence export.

Endpoints:
    POST /api/v1/compliance/report          — generate EU AI Act report for an agent
    GET  /api/v1/compliance/report/{agent_id} — retrieve last generated report (cached)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, PlainTextResponse

from ...report import generate_eu_ai_report
from ..dependencies import get_engine, get_prompt_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/compliance", tags=["compliance"])

# Simple in-memory cache for the last generated report per agent
_report_cache: dict[str, str] = {}


# ═══════════════════════ ENDPOINTS ═══════════════════════════════════════


@router.post("/report")
async def generate_report(
    agent_id: str = Body(..., embed=True),
    format: str = Body("markdown", embed=True),
):
    """Generate an EU AI Act Article 12 compliance report for an agent.

    Returns the report in the requested format (markdown or json).
    The report is cached in memory and available via GET /report/{agent_id}.
    """
    engine = get_engine()
    registry = get_prompt_registry()

    try:
        report_md = generate_eu_ai_report(
            agent_id=agent_id,
            engine=engine,
            registry=registry,
        )
    except Exception as exc:
        logger.exception("Failed to generate compliance report for %s: %s", agent_id, exc)
        return JSONResponse(
            {"error": "report generation failed", "detail": str(exc)},
            status_code=500,
        )

    # Cache for later retrieval
    _report_cache[agent_id] = report_md

    if format == "json":
        return {
            "agent_id": agent_id,
            "format": "html",  # markdown is returned as plain text
            "report": report_md,
        }

    return PlainTextResponse(report_md, media_type="text/markdown; charset=utf-8")


@router.get("/report/{agent_id}")
async def get_report(agent_id: str):
    """Retrieve the last generated compliance report for an agent."""
    report_md = _report_cache.get(agent_id)
    if report_md is None:
        return JSONResponse(
            {"error": "no report cached", "agent_id": agent_id},
            status_code=404,
        )
    return PlainTextResponse(report_md, media_type="text/markdown; charset=utf-8")
