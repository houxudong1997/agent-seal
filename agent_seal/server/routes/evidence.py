"""
Evidence export routes — create signed, tamper-evident audit bundles.

Endpoints:
    POST /api/v1/evidence/export — export evidence bundle for an agent
"""

from __future__ import annotations

import logging
import os
import tempfile

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from ...evidence import EvidenceExporter
from ..dependencies import get_engine, get_prompt_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


# ═══════════════════════ ENDPOINTS ═══════════════════════════════════════


@router.post("/export")
async def api_evidence_export(
    agent_id: str = Body(..., embed=True),
    session_filter: list[str] | None = Body(None, embed=True),
    sign_key: str | None = Body(None, embed=True),
):
    """Export a signed evidence bundle for an agent.

    Creates a .zip bundle containing:
      - metadata.json — bundle description
      - events.json — complete audit trail (hash-chained)
      - prompts.json — prompt version history
      - bundle.json — bundle hash and signature
      - README.txt — verification instructions

    The bundle can be verified offline with:
        agent-seal verify-bundle <file.zip>
    """
    engine = get_engine()
    registry = get_prompt_registry()

    try:
        exporter = EvidenceExporter(engine, registry)

        # Create a temporary file for the bundle
        with tempfile.NamedTemporaryFile(
            suffix=".zip", prefix=f"evidence_{agent_id}_", delete=False
        ) as tf:
            output_path = tf.name

        bundle = exporter.export(
            agent_id=agent_id,
            output_path=output_path,
            sign_key=sign_key,
            session_filter=session_filter,
        )
    except (OSError, ValueError) as exc:
        logger.exception("Evidence export failed for agent %s: %s", agent_id, exc)
        # Clean up temp file on error
        try:
            os.unlink(output_path)
        except (OSError, FileNotFoundError):
            pass
        return JSONResponse(
            {"error": "export failed", "detail": str(exc)}, status_code=500
        )

    # Return the bundle as a download — clean up temp file after sending
    from fastapi.responses import FileResponse

    return FileResponse(
        output_path,
        media_type="application/zip",
        filename=f"evidence_{agent_id}.zip",
        headers={
            "X-Bundle-ID": bundle.bundle_id,
            "X-Bundle-SHA256": bundle.sha256,
            "X-Integrity": "ok" if bundle.integrity_verified else "broken",
        },
        background=BackgroundTask(os.unlink, output_path),
    )
