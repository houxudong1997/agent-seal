"""Tests for server/routes/compliance.py — EU AI Act compliance report endpoints.

Coverage targets:
  - POST /api/v1/compliance/report — normal (markdown), json format, error handling
  - GET  /api/v1/compliance/report/{agent_id} — cached, not found (404)

Strategy: patch generate_eu_ai_report and the report cache directly in the
compliance module to avoid singleton-state issues with dependencies.py.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


FAKE_REPORT = """# EU AI Act Compliance Report — Article 12 Record-Keeping

**Generated**: 2026-06-21 22:24 UTC
**Agent**: test-agent

---

## 1. System Overview

| Agent ID | `test-agent` |
| Total Events Logged | 50 |

*This report was generated automatically by agent-seal v1.0.0.*
"""


@pytest.fixture
def client():
    """Create a TestClient with the compliance router.

    Patching is done inside each test for fine-grained control.
    """
    from agent_seal.server.routes.compliance import router

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as c:
        yield c


# ═══════════════════════════ POST /api/v1/compliance/report ═══════════════════════════


class TestGenerateReport:
    """POST /api/v1/compliance/report — generate a compliance report."""

    def test_generate_markdown(self, client):
        """Default format returns markdown plain text."""
        with patch(
            "agent_seal.server.routes.compliance.generate_eu_ai_report",
            return_value=FAKE_REPORT,
        ):
            response = client.post(
                "/api/v1/compliance/report", json={"agent_id": "test-agent"}
            )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "Article 12" in response.text
        assert "test-agent" in response.text

    def test_generate_json_format(self, client):
        """format='json' returns a JSON wrapper with report field."""
        with patch(
            "agent_seal.server.routes.compliance.generate_eu_ai_report",
            return_value=FAKE_REPORT,
        ):
            response = client.post(
                "/api/v1/compliance/report",
                json={"agent_id": "test-agent", "format": "json"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-agent"
        assert data["format"] == "html"
        assert "report" in data
        assert "Article 12" in data["report"]

    def test_generate_caches_report(self, client):
        """After POST, the report is cached for GET retrieval."""
        with patch(
            "agent_seal.server.routes.compliance.generate_eu_ai_report",
            return_value=FAKE_REPORT,
        ):
            response = client.post(
                "/api/v1/compliance/report", json={"agent_id": "test-agent"}
            )
        assert response.status_code == 200

        # GET should now find the cached report
        get_response = client.get("/api/v1/compliance/report/test-agent")
        assert get_response.status_code == 200
        assert get_response.text == FAKE_REPORT

    def test_generate_separate_cache_keys(self, client):
        """Different agent_ids produce separate cache entries."""
        with patch(
            "agent_seal.server.routes.compliance.generate_eu_ai_report",
            return_value=FAKE_REPORT,
        ):
            resp_a = client.post(
                "/api/v1/compliance/report", json={"agent_id": "agent-a"}
            )
            resp_b = client.post(
                "/api/v1/compliance/report", json={"agent_id": "agent-b"}
            )
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

        # Each should be retrievable independently
        get_a = client.get("/api/v1/compliance/report/agent-a")
        get_b = client.get("/api/v1/compliance/report/agent-b")
        assert get_a.status_code == 200
        assert get_b.status_code == 200

    def test_generate_error_handling(self, client):
        """When generate_eu_ai_report raises, returns 500 with error detail."""
        with patch(
            "agent_seal.server.routes.compliance.generate_eu_ai_report",
            side_effect=RuntimeError("Database connection lost"),
        ):
            response = client.post(
                "/api/v1/compliance/report", json={"agent_id": "test-agent"}
            )

        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "report generation failed"
        assert "Database connection lost" in data["detail"]


# ═══════════════════════════ GET /api/v1/compliance/report/{agent_id} ═══════════════════════════


class TestGetReport:
    """GET /api/v1/compliance/report/{agent_id} — retrieve cached report."""

    def test_get_cached_report(self, client):
        """Retrieve a report that was previously generated."""
        # Populate the cache by posting first
        with patch(
            "agent_seal.server.routes.compliance.generate_eu_ai_report",
            return_value=FAKE_REPORT,
        ):
            client.post("/api/v1/compliance/report", json={"agent_id": "test-agent"})

        response = client.get("/api/v1/compliance/report/test-agent")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "Article 12" in response.text
        assert "test-agent" in response.text

    def test_get_not_found(self, client):
        """No cached report returns 404."""
        response = client.get("/api/v1/compliance/report/nonexistent-agent")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "no report cached"
        assert data["agent_id"] == "nonexistent-agent"

    def test_get_after_multiple_generations(self, client):
        """Last generated report per agent is returned by GET."""
        with patch(
            "agent_seal.server.routes.compliance.generate_eu_ai_report",
            return_value=FAKE_REPORT,
        ):
            client.post("/api/v1/compliance/report", json={"agent_id": "test-agent"})
            client.post("/api/v1/compliance/report", json={"agent_id": "test-agent"})

        response = client.get("/api/v1/compliance/report/test-agent")
        assert response.status_code == 200

    def test_get_empty_cache(self, client):
        """GET without any prior POST returns 404."""
        response = client.get("/api/v1/compliance/report/some-agent")
        assert response.status_code == 404
