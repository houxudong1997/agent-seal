"""
Policy routes — list rules and evaluate agent output against policy engine.

Endpoints:
    GET  /api/v1/policy/rules     — list all loaded policy rules
    POST /api/v1/policy/evaluate   — evaluate an event against all rules
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from ...policy.engine import PolicyEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/policy", tags=["policy"])

# Lazy-init singleton — loads default rules from policy/rules/*.yaml
_policy_engine: PolicyEngine | None = None


def _get_policy_engine() -> PolicyEngine:
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine()
    return _policy_engine


# ═══════════════════════ ENDPOINTS ═══════════════════════════════════════


@router.get("/rules")
async def api_policy_rules():
    """List all loaded policy rules with their configuration."""
    engine = _get_policy_engine()
    rules = []
    for rule in engine.rules:
        rules.append(
            {
                "name": rule.name,
                "priority": rule.priority,
                "description": rule.description,
                "action": rule.action,
                "condition": rule.condition,
                "enabled": rule.enabled,
            }
        )
    return {"rule_count": len(rules), "rules": rules}


@router.post("/evaluate")
async def api_policy_evaluate(
    event_type: str = Body(..., embed=True),
    output: str = Body(..., embed=True),
    input: str = Body("", embed=True),
    session_id: str = Body("", embed=True),
    agent_id: str = Body("", embed=True),
    prompt_version: str = Body("", embed=True),
):
    """Evaluate an agent output against all loaded policy rules.

    Returns the final verdict (allow/deny/warn/approval) and a list of
    triggered rule names.
    """
    engine = _get_policy_engine()
    try:
        result = engine.evaluate(
            event_type=event_type,
            output_snapshot=output,
            input_snapshot=input,
            session_id=session_id,
            agent_id=agent_id,
            prompt_version=prompt_version,
        )
    except (OSError, ValueError) as exc:
        logger.exception("Policy evaluation failed: %s", exc)
        return JSONResponse(
            {"error": "evaluation failed", "detail": str(exc)}, status_code=500
        )

    return {
        "verdict": result.verdict.value,
        "blocked": result.blocked,
        "triggered_rules": result.triggered,
        "reason": result.reason or "",
    }
