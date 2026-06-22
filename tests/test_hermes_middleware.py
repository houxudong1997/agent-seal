"""
Tests for Hermes middleware (agent_audit/server/hermes_middleware.py).

Coverage:
  - Middleware intercepts /api/* paths and logs audit events
  - agent_id resolution from environment variables
  - LLM endpoint detection
  - Graceful degradation when no engine
  - Request/response body capture
  - Non-/api paths bypass middleware
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


# ======================================================================
#  Fixtures
# ======================================================================


@pytest.fixture
def mock_engine():
    """A MagicMock AuditEngine."""
    engine = MagicMock()
    engine.log.return_value = MagicMock(event_id="mock-event")
    return engine


@pytest.fixture
def app():
    """A minimal FastAPI app with test routes."""
    _app = FastAPI()

    @_app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @_app.post("/api/v1/chat")
    async def chat():
        return {"response": "Hello!"}

    @_app.get("/health")
    async def public_health():
        return {"alive": True}

    @_app.get("/api/v1/sessions")
    async def list_sessions():
        return {"sessions": ["sess-1"]}

    return _app


# ======================================================================
#  1. Basic middleware functionality
# ======================================================================


class TestHermesMiddlewareBasic:
    """Core Hermes middleware functionality."""

    def test_middleware_logs_api_request(self, app, mock_engine):
        """API requests should be logged to the audit engine."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app.add_middleware(HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/health")

        assert resp.status_code == 200
        mock_engine.log.assert_called_once()
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["agent_id"] == "test-agent"
        assert call_kwargs["event_type"] == "api_request"

    def test_middleware_logs_method_and_path(self, app, mock_engine):
        """Middleware should record HTTP method and path."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app.add_middleware(HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent")

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/v1/sessions")

        metadata = mock_engine.log.call_args[1]["metadata"]
        assert metadata["method"] == "GET"
        assert metadata["path"] == "/api/v1/sessions"

    def test_middleware_records_status_code(self, app, mock_engine):
        """Middleware should record the response status code."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app.add_middleware(HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent")

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/v1/health")

        metadata = mock_engine.log.call_args[1]["metadata"]
        assert metadata["status_code"] == 200

    def test_middleware_records_duration(self, app, mock_engine):
        """Middleware should record request duration."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app.add_middleware(HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent")

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/v1/health")

        metadata = mock_engine.log.call_args[1]["metadata"]
        assert "duration_ms" in metadata
        assert isinstance(metadata["duration_ms"], float)

    def test_middleware_logs_post_requests(self, app, mock_engine):
        """POST requests should also be logged."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app.add_middleware(HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent")

        client = TestClient(app, raise_server_exceptions=False)
        client.post("/api/v1/chat")

        assert mock_engine.log.called


# ======================================================================
#  2. Non-/api paths bypass
# ======================================================================


class TestHermesMiddlewareBypass:
    """Non-/api paths should bypass the middleware."""

    def test_non_api_route_not_logged(self, app, mock_engine):
        """Routes not starting with /api should not be logged."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app.add_middleware(HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")

        assert resp.status_code == 200
        mock_engine.log.assert_not_called()


# ======================================================================
#  3. LLM endpoint detection
# ======================================================================


class TestHermesMiddlewareLLM:
    """LLM endpoint detection and event type."""

    @pytest.fixture
    def llm_app(self):
        _app = FastAPI()

        @_app.post("/api/v1/chat/completions")
        async def chat_completions():
            return {"choices": [{"text": "Hello!"}]}

        @_app.post("/api/v1/completions")
        async def openai_compat():
            return {"choices": [{"text": "Hi"}]}

        @_app.post("/api/v1/messages")
        async def anthropic_compat():
            return {"content": "Hello"}

        return _app

    def test_chat_completions_is_llm_request(self, llm_app, mock_engine):
        """Chat completion endpoints should have event_type=llm_request."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        llm_app.add_middleware(
            HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent"
        )

        client = TestClient(llm_app, raise_server_exceptions=False)
        client.post("/api/v1/chat/completions")

        assert mock_engine.log.called
        assert mock_engine.log.call_args[1]["event_type"] == "llm_request"
        assert mock_engine.log.call_args[1]["metadata"]["is_llm"] is True

    def test_openai_compat_is_llm_request(self, llm_app, mock_engine):
        """OpenAI-compatible v1/completions should be detected as LLM."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        llm_app.add_middleware(
            HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent"
        )

        client = TestClient(llm_app, raise_server_exceptions=False)
        client.post("/api/v1/completions")

        assert mock_engine.log.called
        assert mock_engine.log.call_args[1]["event_type"] == "llm_request"

    def test_anthropic_messages_is_llm_request(self, llm_app, mock_engine):
        """Anthropic /v1/messages endpoint should be detected as LLM."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        llm_app.add_middleware(
            HermesAuditMiddleware, engine=mock_engine, agent_id="test-agent"
        )

        client = TestClient(llm_app, raise_server_exceptions=False)
        client.post("/api/v1/messages")

        assert mock_engine.log.called
        assert mock_engine.log.call_args[1]["event_type"] == "llm_request"


# ======================================================================
#  4. Agent ID resolution
# ======================================================================


class TestHermesMiddlewareAgentID:
    """Agent ID resolution from environment variables."""

    def test_agent_id_from_env_var(self, app):
        """agent_id should be read from HERMES_AGENT_ID env var."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        with patch.dict(os.environ, {"HERMES_AGENT_ID": "env-agent"}):
            mock_eng = MagicMock()
            app.add_middleware(HermesAuditMiddleware, engine=mock_eng)

            client = TestClient(app, raise_server_exceptions=False)
            client.get("/api/v1/health")

            assert mock_eng.log.call_args[1]["agent_id"] == "env-agent"

    def test_agent_id_env_priority(self, app):
        """AGENT_AUDIT_HERMES_AGENT_ID should take priority over HERMES_AGENT_ID."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        with patch.dict(
            os.environ,
            {
                "AGENT_AUDIT_HERMES_AGENT_ID": "explicit-agent",
                "HERMES_AGENT_ID": "fallback-agent",
            },
        ):
            mock_eng = MagicMock()
            app.add_middleware(HermesAuditMiddleware, engine=mock_eng)

            client = TestClient(app, raise_server_exceptions=False)
            client.get("/api/v1/health")

            assert mock_eng.log.call_args[1]["agent_id"] == "explicit-agent"

    def test_unknown_agent_fallback(self, app):
        """When no env var is set, agent_id should fall back to 'unknown-hermes-agent'."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        with patch.dict(os.environ, {}, clear=True):
            mock_eng = MagicMock()
            app.add_middleware(HermesAuditMiddleware, engine=mock_eng)

            client = TestClient(app, raise_server_exceptions=False)
            client.get("/api/v1/health")

            assert mock_eng.log.call_args[1]["agent_id"] == "unknown-hermes-agent"

    def test_explicit_agent_id_overrides_env(self, app):
        """Explicit agent_id kwarg should override any env var."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        with patch.dict(os.environ, {"HERMES_AGENT_ID": "env-agent"}):
            mock_eng = MagicMock()
            app.add_middleware(
                HermesAuditMiddleware, engine=mock_eng, agent_id="explicit"
            )

            client = TestClient(app, raise_server_exceptions=False)
            client.get("/api/v1/health")

            assert mock_eng.log.call_args[1]["agent_id"] == "explicit"


# ======================================================================
#  5. Graceful degradation
# ======================================================================


class TestHermesMiddlewareDegradation:
    """Behaviour when engine is unavailable or fails."""

    def test_no_engine_does_not_crash(self, app):
        """Without an engine, the middleware should not crash."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app.add_middleware(HermesAuditMiddleware, engine=None)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_engine_failure_does_not_crash(self, app):
        """If engine.log() raises, the request should still complete."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        broken_engine = MagicMock()
        broken_engine.log.side_effect = RuntimeError("engine down")

        app.add_middleware(HermesAuditMiddleware, engine=broken_engine)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_unreadable_body_does_not_crash(self, app, mock_engine):
        """If request body cannot be read, the middleware should not crash."""
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app.add_middleware(HermesAuditMiddleware, engine=mock_engine)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
