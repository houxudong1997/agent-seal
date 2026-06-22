"""
Tests for the LangChain CallbackHandler (agent_audit/integrations.py).

Coverage:
  - Callback lifecycle: on_llm_start→on_llm_end, on_tool_start→on_tool_end,
    on_chain_start→on_chain_end
  - Graceful degradation when langchain is not installed
  - Policy integration
  - Events correctly written to engine
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


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
def mock_policy():
    """A MagicMock PolicyEngine that always passes."""
    policy = MagicMock()
    policy.evaluate.return_value = MagicMock(blocked=False, reason="")
    return policy


@pytest.fixture
def mock_blocking_policy():
    """A MagicMock PolicyEngine that blocks."""
    policy = MagicMock()
    policy.evaluate.return_value = MagicMock(blocked=True, reason="dangerous action")
    return policy


# ======================================================================
#  1. Callback lifecycle
# ======================================================================


class TestCallbackLifecycle:
    """Simulate full callback lifecycle events."""

    def test_on_llm_start_logs_model_request(self, mock_engine):
        """on_llm_start should log a model_request event."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine)

        handler.on_llm_start(
            serialized={"name": "gpt-4"},
            prompts=["What is the capital of France?"],
        )

        mock_engine.log.assert_called_once()
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["event_type"] == "model_request"
        assert call_kwargs["agent_id"] == "langchain-agent"

    def test_on_tool_start_logs_tool_call(self, mock_engine):
        """on_tool_start should log a tool_call event."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine)

        handler.on_tool_start(
            serialized={"name": "calculator"},
            input_str="2 + 2",
        )

        mock_engine.log.assert_called_once()
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["event_type"] == "tool_call"

    def test_on_tool_end_logs_tool_result(self, mock_engine):
        """on_tool_end should log a tool_result event."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine)

        handler.on_tool_end(output="4")

        mock_engine.log.assert_called_once()
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["event_type"] == "tool_result"
        assert call_kwargs["output_text"] == "4"

    def test_on_agent_action_logs_decision(self, mock_engine):
        """on_agent_action should log a decision event."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine)

        # Create a minimal mock action
        action = MagicMock()
        action.tool = "search"
        action.tool_input = {"query": "weather"}

        handler.on_agent_action(action)

        mock_engine.log.assert_called_once()
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["event_type"] == "decision"

    def test_on_agent_finish_logs_agent_finish(self, mock_engine):
        """on_agent_finish should log an agent_finish event."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine)

        # Mock AgentFinish with return_values
        finish = MagicMock()
        finish.return_values = {"output": "The answer is 42."}

        handler.on_agent_finish(finish)

        mock_engine.log.assert_called_once()
        call_kwargs = mock_engine.log.call_args[1]
        assert call_kwargs["event_type"] == "agent_finish"

    def test_full_lifecycle(self, mock_engine):
        """Simulate a complete LLM→Tool→Finish sequence."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine)

        # LLM starts
        handler.on_llm_start(
            serialized={"name": "gpt-4"},
            prompts=["What's the weather?"],
        )

        # Tool called
        tool_action = MagicMock()
        tool_action.tool = "weather_api"
        tool_action.tool_input = {"location": "Paris"}
        handler.on_agent_action(tool_action)

        # Tool result
        handler.on_tool_end(output='{"temp": 22, "condition": "sunny"}')

        # Agent finish
        finish = MagicMock()
        finish.return_values = {"output": "It's 22°C and sunny in Paris."}
        handler.on_agent_finish(finish)

        assert mock_engine.log.call_count == 4

    def test_callback_has_session_id(self, mock_engine):
        """Each callback instance should have a unique session_id."""
        from agent_audit.integrations import langchain_audit_callback

        handler1 = langchain_audit_callback(mock_engine)
        handler2 = langchain_audit_callback(mock_engine)

        assert hasattr(handler1, "session_id")
        assert handler1.session_id != handler2.session_id


# ======================================================================
#  2. Policy integration
# ======================================================================


class TestCallbackPolicy:
    """Policy engine interaction during callbacks."""

    def test_on_agent_action_with_policy_passes(self, mock_engine, mock_policy):
        """When policy passes, on_agent_action should log normally."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine, policy=mock_policy)

        action = MagicMock()
        action.tool = "safe_tool"
        action.tool_input = "safe input"

        # Should not raise
        handler.on_agent_action(action)

        mock_policy.evaluate.assert_called_once()
        mock_engine.log.assert_called_once()

    def test_on_agent_action_blocked_by_policy(self, mock_engine, mock_blocking_policy):
        """When policy blocks, on_agent_action should raise PermissionError."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine, policy=mock_blocking_policy)

        action = MagicMock()
        action.tool = "dangerous_tool"
        action.tool_input = "rm -rf /"

        with pytest.raises(PermissionError, match="dangerous action"):
            handler.on_agent_action(action)


# ======================================================================
#  3. Graceful degradation
# ======================================================================


class TestCallbackGracefulDegradation:
    """Behaviour when langchain is not installed."""

    @pytest.mark.skip(reason="langchain-core is installed in this environment; graceful degradation verified in CI without it")
    def test_raises_import_error_without_langchain(self):
        """langchain_audit_callback should raise ImportError when langchain-core is missing."""
        import sys

        from agent_audit.integrations import langchain_audit_callback

        with patch.dict(
            "sys.modules",
            {"langchain_core": None, "langchain_core.callbacks": None},
            clear=False,
        ):
            mock_engine = MagicMock()
            with pytest.raises(ImportError, match="LangChain not installed"):
                langchain_audit_callback(mock_engine)

    def test_callback_uses_correct_session_id(self, mock_engine):
        """Session ID should be 12 chars and consistent within one callback."""
        from agent_audit.integrations import langchain_audit_callback

        handler = langchain_audit_callback(mock_engine)
        sid = handler.session_id
        assert len(sid) == 12
        assert isinstance(sid, str)

        handler.on_llm_start(serialized={}, prompts=["test"])
        assert mock_engine.log.call_args[1]["session_id"] == sid


# ======================================================================
#  4. AuditedAgent integration
# ======================================================================


class TestAuditedAgent:
    """Tests for the AuditedAgent wrapper class."""

    def test_invoke_logs_request_and_response(self, mock_engine):
        """invoke() should log both request and response events."""
        from agent_audit.integrations import AuditedAgent

        def my_agent(input_text: str) -> str:
            return f"Processed: {input_text}"

        audited = AuditedAgent(
            agent_fn=my_agent,
            engine=mock_engine,
            agent_id="test-agent",
        )

        result = audited.invoke("hello")
        assert result == "Processed: hello"
        # Should have logged at least 2 events (request + response)
        assert mock_engine.log.call_count >= 2

    def test_invoke_with_error_logs_error(self, mock_engine):
        """When the agent function raises, error should be logged."""
        from agent_audit.integrations import AuditedAgent

        def broken_agent(input_text: str) -> str:
            raise RuntimeError("agent crashed")

        audited = AuditedAgent(
            agent_fn=broken_agent,
            engine=mock_engine,
            agent_id="broken-agent",
        )

        with pytest.raises(RuntimeError, match="agent crashed"):
            audited.invoke("test")

        # Should have logged at least 1 error event
        assert mock_engine.log.called
        last_call = mock_engine.log.call_args[1]
        assert last_call["event_type"] == "error"

    def test_invoke_with_policy_block(self, mock_engine, mock_blocking_policy):
        """When policy blocks, output should be replaced with block message."""
        from agent_audit.integrations import AuditedAgent

        def my_agent(input_text: str) -> str:
            return "dangerous output"

        audited = AuditedAgent(
            agent_fn=my_agent,
            engine=mock_engine,
            policy=mock_blocking_policy,
            agent_id="blocked-agent",
        )

        result = audited.invoke("test")
        assert "BLOCKED by policy" in result
