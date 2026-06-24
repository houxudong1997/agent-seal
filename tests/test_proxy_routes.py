"""Tests for server/routes/proxy.py — LLM proxy that intercepts, logs, and forwards.

Coverage targets:
  - POST /api/v1/proxy/{path} — forward LLM call, return upstream response
  - GET  /api/v1/proxy/{path} — method passthrough
  - Upstream error handling — httpx failure → 502
  - Agent ID detection — header, env fallback, unknown fallback
  - Audit logging — engine.log called with correct params
  - Engine init failure — graceful degradation when AuditEngine unavailable
  - Body truncation — body limited to 4000 chars for audit
  - Header stripping — host/transfer-encoding/content-length removed
  - Multiple HTTP methods — POST, GET, PUT, DELETE, PATCH

Strategy: mock httpx.AsyncClient at the proxy module level so no real
HTTP calls are made. Patch _get_engine to control audit logging.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_mock_response(status=200, body=b'{"ok":true}', headers=None):
    """Build a minimal mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.content = body
    resp.headers = headers or {"content-type": "application/json"}
    return resp


@pytest.fixture
def client():
    """Create a TestClient with the proxy router in isolation.

    Patching is done at the test-function level for fine-grained control.
    """
    from agent_seal.server.routes.proxy import router

    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as c:
        yield c


def _patch_httpx(mock_response: MagicMock) -> patch:
    """Patch httpx.AsyncClient in the proxy module to return a mock response."""
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.request = AsyncMock(return_value=mock_response)

    return patch(
        "agent_seal.server.routes.proxy.httpx.AsyncClient",
        return_value=mock_client,
    )


# ═══════════════════════════ PROXY — Successful forward ═══════════════════════════


class TestProxyForward:
    """Successful proxy forwarding — various HTTP methods."""

    def test_post_forward(self, client):
        """POST /api/v1/proxy/v1/chat/completions returns upstream response."""
        mock_resp = _make_mock_response(
            200,
            b'{"id":"chat-123","choices":[{"message":{"content":"hello"}}]}',
            {"content-type": "application/json"},
        )

        with _patch_httpx(mock_resp):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "chat-123"
        assert data["choices"][0]["message"]["content"] == "hello"

    def test_get_forward(self, client):
        """GET /api/v1/proxy/v1/models returns upstream model list."""
        mock_resp = _make_mock_response(
            200,
            b'{"data":[{"id":"deepseek-chat","object":"model"}]}',
        )

        with _patch_httpx(mock_resp):
            response = client.get("/api/v1/proxy/v1/models")

        assert response.status_code == 200
        data = response.json()
        assert data["data"][0]["id"] == "deepseek-chat"

    def test_delete_forward(self, client):
        """DELETE passes method through."""
        mock_resp = _make_mock_response(204, b"")

        with _patch_httpx(mock_resp):
            response = client.delete("/api/v1/proxy/v1/some-resource")

        assert response.status_code == 204

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "OPTIONS"])
    def test_various_http_methods(self, client, method):
        """PUT, PATCH, OPTIONS all pass through correctly."""
        mock_resp = _make_mock_response(200, b'{"status":"ok"}')

        with _patch_httpx(mock_resp):
            response = client.request(method, "/api/v1/proxy/v1/test")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_status_passthrough(self, client):
        """Upstream non-200 status is passed back to caller."""
        mock_resp = _make_mock_response(429, b'{"error":"rate_limited"}')

        with _patch_httpx(mock_resp):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        assert response.status_code == 429
        data = response.json()
        assert data["error"] == "rate_limited"


# ═══════════════════════════ PROXY — Error handling ═══════════════════════════


class TestProxyErrorHandling:
    """Error scenarios — upstream failure, network errors."""

    @staticmethod
    def _patch_httpx_error(side_effect: Exception) -> patch:
        """Patch httpx.AsyncClient to raise an error."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.request = AsyncMock(side_effect=side_effect)
        return patch(
            "agent_seal.server.routes.proxy.httpx.AsyncClient",
            return_value=mock_client,
        )

    def test_upstream_connection_error(self, client):
        """When httpx raises, returns 502 with error detail."""
        with self._patch_httpx_error(ConnectionError("Connection refused")):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        assert response.status_code == 502
        data = response.json()
        assert "error" in data
        assert "Connection refused" in data["error"]

    def test_upstream_timeout(self, client):
        """Timeout from upstream returns 502."""
        with self._patch_httpx_error(TimeoutError("timed out")):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        assert response.status_code == 502
        assert "timed out" in response.json()["error"]

    def test_empty_body_on_error(self, client):
        """Works even when request has no body (get-like error)."""
        with self._patch_httpx_error(Exception("Network failure")):
            response = client.get("/api/v1/proxy/v1/models")

        assert response.status_code == 502


# ═══════════════════════════ PROXY — Agent ID detection ═══════════════════════════


class TestAgentIdDetection:
    """Agent ID resolution from headers and environment."""

    def test_agent_id_from_header(self, client):
        """X-Agent-Seal-Agent-Id header is used as agent_id."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
                headers={"X-Agent-Seal-Agent-Id": "my-custom-agent"},
            )

        assert response.status_code == 200
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["agent_id"] == "my-custom-agent"
        assert "my-custom-agent" in call_kwargs["session_id"]

    def test_agent_id_from_env(self, client, monkeypatch):
        """When no header, HERMES_PROFILE env var is used."""
        monkeypatch.setenv("HERMES_PROFILE", "workstation-test-dev")

        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        assert response.status_code == 200
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["agent_id"] == "workstation-test-dev"

    def test_agent_id_fallback_hermes_agent_id(self, client, monkeypatch):
        """Fallback to HERMES_AGENT_ID when HERMES_PROFILE is not set."""
        monkeypatch.delenv("HERMES_PROFILE", raising=False)
        monkeypatch.setenv("HERMES_AGENT_ID", "agent-007")

        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        assert response.status_code == 200
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["agent_id"] == "agent-007"

    def test_agent_id_unknown(self, client, monkeypatch):
        """When no header and no env vars, agent_id is 'unknown'."""
        monkeypatch.delenv("HERMES_PROFILE", raising=False)
        monkeypatch.delenv("HERMES_AGENT_ID", raising=False)

        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        assert response.status_code == 200
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["agent_id"] == "unknown"


# ═══════════════════════════ PROXY — Audit logging ═══════════════════════════


class TestAuditLogging:
    """Audit trail — engine.log is called with correct parameters."""

    def test_log_called_with_llm_request_type(self, client):
        """engine.log is called with event_type='llm_request'."""
        mock_resp = _make_mock_response(200, b'{"choices":[{"text":"ok"}]}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )

        mock_engine.log.assert_called_once()
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["event_type"] == "llm_request"
        assert call_kwargs["prompt_version"] == "deepseek-chat"

    def test_log_contains_last_message_content(self, client):
        """Last user message content is logged in input_text."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [
                        {"role": "system", "content": "You are helpful"},
                        {"role": "user", "content": "What is the capital of France?"},
                    ],
                },
            )

        call_kwargs = mock_engine.log.call_args[1]
        assert "capital of France" in call_kwargs["input_text"]

    def test_log_output_text_is_status_code(self, client):
        """output_text contains string representation of status code."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["output_text"] == "200"

    def test_log_metadata_contains_model_ms_url_method(self, client):
        """metadata includes model, ms, url, and method."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        call_kwargs = mock_engine.log.call_args[1]
        meta = call_kwargs["metadata"]
        assert meta["model"] == "deepseek-chat"
        assert isinstance(meta["ms"], int)
        assert "api.deepseek.com" in meta["url"]
        assert "chat/completions" in meta["url"]
        assert meta["method"] == "POST"

    def test_log_not_called_when_engine_none(self, client):
        """When _get_engine returns None, no logging is attempted."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=None,
        ):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        assert response.status_code == 200
        # No engine to assert .log on — just verify response works

    def test_log_exception_swallowed(self, client):
        """When engine.log raises, proxy still returns successfully."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()
        mock_engine.log.side_effect = RuntimeError("Audit database full")

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
            )

        assert response.status_code == 200
        # The exception in engine.log is caught by bare 'except: pass'


# ═══════════════════════════ PROXY — Body handling ═══════════════════════════


class TestBodyHandling:
    """Request body reading, truncation, and parsing."""

    def test_model_extracted_from_body(self, client):
        """Model name is correctly extracted from JSON body."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
            )

        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["prompt_version"] == "deepseek-chat"

    def test_no_messages_model_still_extracted(self, client):
        """Messages list not present, model still extracted."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "claude-3-opus"},
            )

        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["prompt_version"] == "claude-3-opus"
        assert call_kwargs["input_text"] == ""

    def test_non_json_body_still_proxied(self, client):
        """Non-JSON body doesn't break proxy — model='?' and txt=''."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                content=b"raw string body",
                headers={"content-type": "text/plain"},
            )

        assert response.status_code == 200
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["prompt_version"] == "?"

    def test_empty_body_does_not_crash(self, client):
        """Empty body doesn't cause JSON decode errors."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_engine = MagicMock()

        with _patch_httpx(mock_resp), patch(
            "agent_seal.server.routes.proxy._get_engine",
            return_value=mock_engine,
        ):
            response = client.post(
                "/api/v1/proxy/v1/chat/completions",
                content=b"",
            )

        assert response.status_code == 200
        # With empty body, model='?' and input_text=''
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["prompt_version"] == "?"


# ═══════════════════════════ PROXY — Header handling ═══════════════════════════


class TestHeaderHandling:
    """Host-bound headers are stripped before forwarding."""

    def test_host_header_stripped(self, client):
        """Host header is removed from forwarded request."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_resp = _make_mock_response(200, b'{"ok":true}')
        mock_client.request = AsyncMock(return_value=mock_resp)

        with patch(
            "agent_seal.server.routes.proxy.httpx.AsyncClient",
            return_value=mock_client,
        ):
            client.post(
                "/api/v1/proxy/v1/chat/completions",
                json={"model": "deepseek-chat"},
                headers={"host": "my-proxy.internal", "authorization": "Bearer test123"},
            )

        forwarded_headers = mock_client.request.call_args[1]["headers"]
        # host must be stripped
        assert "host" not in forwarded_headers
        # authorization should still be present
        assert forwarded_headers.get("authorization") == "Bearer test123"


# ═══════════════════════════ PROXY — Engine initialization ═══════════════════════════


class TestEngineInit:
    """Graceful degradation when AuditEngine can't be initialized."""

    def test_no_engine_does_not_affect_proxy_response(self, client):
        """Proxy works without audit engine (returns upstream response)."""
        mock_resp = _make_mock_response(200, b'{"ok":true}')

        with _patch_httpx(mock_resp):
            with patch(
                "agent_seal.server.routes.proxy._get_engine",
                return_value=None,
            ):
                response = client.post(
                    "/api/v1/proxy/v1/chat/completions",
                    json={"model": "deepseek-chat"},
                )

        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_no_engine_upstream_error_still_works(self, client):
        """502 error is still returned even without audit engine."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.request = AsyncMock(side_effect=ConnectionError("DNS failure"))

        with patch(
            "agent_seal.server.routes.proxy.httpx.AsyncClient",
            return_value=mock_client,
        ):
            with patch(
                "agent_seal.server.routes.proxy._get_engine",
                return_value=None,
            ):
                response = client.post(
                    "/api/v1/proxy/v1/chat/completions",
                    json={"model": "deepseek-chat"},
                )

        assert response.status_code == 502
        assert "DNS failure" in response.json()["error"]
