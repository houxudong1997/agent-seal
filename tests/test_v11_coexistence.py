"""
Cross-module coexistence test for agent-audit v1.1.

Verifies that @observe + LangChain CallbackHandler + Hermes middleware
can coexist without conflicts.

Each test uses an isolated AuditEngine instance and verifies that all
three modules can log events independently without corrupting each
other's sessions or data.
"""

from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


# ======================================================================
#  Fixtures
# ======================================================================


@pytest.fixture
def real_engine():
    """A real JSONL AuditEngine for integration-level tests."""
    from agent_audit.engine import AuditEngine

    with tempfile.TemporaryDirectory() as tmpdir:
        uri = f"jsonl://{tmpdir}"
        engine = AuditEngine(uri)
        yield engine
        engine.close()


@pytest.fixture
def mock_engine():
    """A MagicMock AuditEngine for unit-level tests."""
    engine = MagicMock()
    engine.log.return_value = MagicMock(event_id="mock-event")
    return engine


# ======================================================================
#  1. Observe + CallbackHandler coexistence
# ======================================================================


class TestObserveAndCallback:
    """@observe and LangChain CallbackHandler should work together."""

    def test_both_log_to_same_engine(self, mock_engine):
        """Both @observe and CallbackHandler should log to the same engine."""
        from agent_audit.integrations import langchain_audit_callback
        from agent_audit.observe import observe, set_engine

        set_engine(mock_engine)

        @observe(name="helper")
        def helper(x: int) -> int:
            return x * 2

        handler = langchain_audit_callback(mock_engine)

        result = helper(5)
        assert result == 10

        handler.on_llm_start(
            serialized={"name": "gpt-4"},
            prompts=["test"],
        )

        assert mock_engine.log.call_count == 2

        calls = mock_engine.log.call_args_list
        # Observe uses function name as agent_id
        assert "helper" in str(calls[0])
        assert calls[1][1]["agent_id"] == "langchain-agent"
        assert calls[1][1]["event_type"] == "model_request"

    def test_no_event_type_conflict(self, mock_engine):
        """@observe and CallbackHandler use different event_types."""
        from agent_audit.integrations import langchain_audit_callback
        from agent_audit.observe import observe, set_engine

        set_engine(mock_engine)

        @observe(name="sync")
        def sync_fn() -> str:
            return "ok"

        handler = langchain_audit_callback(mock_engine)

        sync_fn()
        handler.on_tool_start(serialized={}, input_str="test")
        handler.on_tool_end(output="done")

        event_types = [call[1]["event_type"] for call in mock_engine.log.call_args_list]
        assert "observe" in event_types or "observe_error" in event_types
        assert "tool_call" in event_types
        assert "tool_result" in event_types


# ======================================================================
#  2. CallbackHandler + Hermes middleware coexistence
# ======================================================================


class TestCallbackAndMiddleware:
    """LangChain CallbackHandler and Hermes middleware should coexist."""

    def test_both_log_independently(self, mock_engine):
        """CallbackHandler and middleware should log separate events."""
        from agent_audit.integrations import langchain_audit_callback
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app = FastAPI()
        app.add_middleware(HermesAuditMiddleware, engine=mock_engine, agent_id="hermes-agent")

        @app.post("/api/v1/chat/completions")
        async def chat():
            handler = langchain_audit_callback(mock_engine)
            handler.on_llm_start(serialized={}, prompts=["hello"])
            return {"response": "Hi"}

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/chat/completions", json={"prompt": "hello"})
        assert resp.status_code == 200

        assert mock_engine.log.call_count >= 2

        event_types = [call[1]["event_type"] for call in mock_engine.log.call_args_list]
        assert "model_request" in event_types
        assert "llm_request" in event_types

    def test_no_session_collision(self, mock_engine):
        """Callback and middleware should use different session IDs."""
        from agent_audit.integrations import langchain_audit_callback
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        app = FastAPI()
        app.add_middleware(HermesAuditMiddleware, engine=mock_engine, agent_id="hermes-agent")

        @app.get("/api/v1/test")
        async def test():
            handler = langchain_audit_callback(mock_engine)
            handler.on_llm_start(serialized={}, prompts=["test"])
            return {"ok": True}

        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/v1/test")

        session_ids = set()
        for call in mock_engine.log.call_args_list:
            session_ids.add(call[1]["session_id"])

        assert len(session_ids) >= 2


# ======================================================================
#  3. All three modules together
# ======================================================================


class TestAllThreeTogether:
    """@observe + CallbackHandler + Hermes middleware — full coexistence."""

    def test_all_log_to_real_engine(self):
        """All three modules should log successfully to a real AuditEngine."""
        from agent_audit.engine import AuditEngine
        from agent_audit.integrations import langchain_audit_callback
        from agent_audit.observe import observe, set_engine
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        with tempfile.TemporaryDirectory() as tmpdir:
            uri = f"jsonl://{tmpdir}"
            engine = AuditEngine(uri)

            # 1. @observe
            set_engine(engine)
            @observe(name="add")
            def add(a: int, b: int) -> int:
                return a + b

            # 2. LangChain callback handler
            handler = langchain_audit_callback(engine)

            # 3. Hermes middleware
            app = FastAPI()
            app.add_middleware(
                HermesAuditMiddleware, engine=engine, agent_id="hermes"
            )

            @app.get("/api/v1/status")
            async def status():
                return {"status": "ok"}

            # Exercise all three
            add(1, 2)
            handler.on_llm_start(serialized={}, prompts=["test"])

            client = TestClient(app, raise_server_exceptions=False)
            client.get("/api/v1/status")

            assert engine.verify()

            sessions = engine.sessions()
            assert len(sessions) >= 2, f"Expected >=2 sessions, got {sessions}"

            total_events = sum(len(engine.read(s)) for s in sessions)
            assert total_events >= 2, f"Expected >=2 events, got {total_events} from {sessions}"

            engine.close()

    def test_no_engine_conflicts(self, mock_engine):
        """All three modules using same mock engine should not conflict."""
        from agent_audit.integrations import langchain_audit_callback
        from agent_audit.observe import observe, set_engine
        from agent_audit.server.hermes_middleware import HermesAuditMiddleware

        set_engine(mock_engine)

        @observe(name="fn")
        def fn() -> str:
            return "x"

        handler = langchain_audit_callback(mock_engine)

        app = FastAPI()
        app.add_middleware(
            HermesAuditMiddleware, engine=mock_engine, agent_id="hermes"
        )

        @app.get("/api/v1/ping")
        async def ping():
            return {"pong": True}

        fn()
        handler.on_tool_start(serialized={}, input_str="test")
        client = TestClient(app, raise_server_exceptions=False)
        client.get("/api/v1/ping")

        event_types = [call[1]["event_type"] for call in mock_engine.log.call_args_list]
        assert any("observe" in et for et in event_types)
        assert "tool_call" in event_types
        assert "api_request" in event_types

        # Check no unexpected errors in the logging chain
        for call in mock_engine.log.call_args_list:
            metadata = call[1].get("metadata", {})
            if "error" in metadata:
                pytest.fail(f"Unexpected error in metadata: {metadata['error']}")
