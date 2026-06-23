"""Verify integrations.py .trail -> .engine migration."""
import pytest
from unittest.mock import MagicMock, patch

# ---- Step 1: Import check ----
from agent_seal.integrations import langchain_audit_callback, AuditedAgent
from agent_seal.engine import AuditEngine


def test_audited_agent_engine_field():
    """AuditedAgent dataclass accepts engine field."""
    engine = AuditEngine("jsonl:///tmp/test-audit-test-inline")
    agent = AuditedAgent(
        agent_fn=lambda x: f"echo: {x}",
        engine=engine,
        agent_id="test-agent",
    )
    assert agent.engine is engine
    assert agent.agent_id == "test-agent"


def test_langchain_callback_engine_param():
    """langchain_audit_callback() accepts engine parameter."""
    engine = AuditEngine("jsonl:///tmp/test-audit-lc-cb")
    callback = langchain_audit_callback(engine)
    # The callback is an AuditCallback instance — we can't easily assert on private
    # state from here, but the fact it didn't raise means engine param was accepted.
    assert callback is not None
    # Clean up
    if hasattr(engine, "_storage"):
        engine._storage = None


@pytest.mark.skip(reason="Requires langchain-core installed")
def test_langchain_callback_happy_path():
    """Full langchain integration — logging through engine."""
    import langchain_core  # noqa
    engine = AuditEngine("jsonl:///tmp/test-audit-lc-path")
    callback = langchain_audit_callback(engine)
    # LangChain callback handler instantiation
    from langchain_core.callbacks import BaseCallbackHandler
    assert isinstance(callback, BaseCallbackHandler)


def test_audited_agent_invoke_logs_through_engine():
    """AuditedAgent.invoke() logs request and response via engine.log()."""
    engine = AuditEngine("jsonl:///tmp/test-audit-invoke-logs")
    with patch.object(engine, "log") as mock_log:
        agent = AuditedAgent(
            agent_fn=lambda x: f"Hello, {x}!",
            engine=engine,
            agent_id="invoke-test",
        )
        result = agent.invoke("World")

    assert result == "Hello, World!"
    # Should have been called for request + response
    assert mock_log.call_count >= 2
    # Verify first call is the request
    first_call = mock_log.call_args_list[0]
    assert first_call.kwargs["event_type"] == "request"
    # Verify engine object isn't None and is the right type
    assert isinstance(agent.engine, AuditEngine)
