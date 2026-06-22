"""
Tests for agent_audit.hooks.langchain — AuditCallbackHandler.

All tests mock the langchain-base interfaces WITHOUT requiring the
actual langchain package installed, per the spec: "模拟 langchain
回调接口，不依赖真实 langchain".
"""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ──────────────────────────────────────────────────────────


class FakeLangChainBase:
    """Stub for langchain_core.callbacks.base.BaseCallbackHandler."""

    def on_llm_start(self, *a: object, **kw: object) -> None: ...
    def on_llm_end(self, *a: object, **kw: object) -> None: ...
    def on_llm_error(self, *a: object, **kw: object) -> None: ...
    def on_tool_start(self, *a: object, **kw: object) -> None: ...
    def on_tool_end(self, *a: object, **kw: object) -> None: ...
    def on_tool_error(self, *a: object, **kw: object) -> None: ...
    def on_chain_start(self, *a: object, **kw: object) -> None: ...
    def on_chain_end(self, *a: object, **kw: object) -> None: ...
    def on_chain_error(self, *a: object, **kw: object) -> None: ...
    def on_agent_action(self, *a: object, **kw: object) -> None: ...
    def on_agent_finish(self, *a: object, **kw: object) -> None: ...


class FakeLLMResult:
    """Stub for langchain_core.outputs.LLMResult."""

    def __init__(self, generations=None, llm_output=None) -> None:
        self.generations = generations or []
        self.llm_output = llm_output or {}
        self.usage_metadata = None


class FakeGeneration:
    """Stub for langchain_core.outputs.Generation."""

    def __init__(self, text: str = "") -> None:
        self.text = text


class FakeAgentAction:
    """Stub for langchain_core.agents.AgentAction."""

    def __init__(self, tool: str = "search", tool_input: str = "query", log: str = ""):
        self.tool = tool
        self.tool_input = tool_input
        self.log = log


class FakeAgentFinish:
    """Stub for langchain_core.agents.AgentFinish."""

    def __init__(self, return_values=None, log: str = "") -> None:
        self.return_values = return_values or {"output": "final answer"}
        self.log = log


class FakeUsageMetadata:
    """Stub for langchain_core.outputs.usage_metadata."""

    def __init__(self, input_tokens=0, output_tokens=0, total_tokens=0) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _mock_langchain_import() -> None:
    """Patch sys.modules so the langchain import in langchain.py succeeds."""
    with patch.dict(
        sys.modules,
        {
            "langchain_core": MagicMock(),
            "langchain_core.callbacks": MagicMock(),
            "langchain_core.callbacks.base": MagicMock(),
        },
    ):
        sys.modules[
            "langchain_core.callbacks.base"
        ].BaseCallbackHandler = FakeLangChainBase
        yield


@pytest.fixture
def mock_engine():
    """Return a MagicMock that stands in for AuditEngine."""
    with patch(
        "agent_audit.hooks.langchain.get_engine", return_value=MagicMock()
    ) as mock_get:
        engine = mock_get.return_value
        yield engine


@pytest.fixture
def handler(mock_engine):
    """A fresh AuditCallbackHandler with a mock engine."""
    from agent_audit.hooks.langchain import AuditCallbackHandler

    return AuditCallbackHandler(agent_id="test-agent", session_id="test-sess-42")


# ── Module import tests ────────────────────────────────────────────


class TestLangChainUnavailable:
    """Behaviour when langchain-core is not installed."""

    def test_raise_on_missing_langchain(self):
        """Raises RuntimeError when langchain is absent and raise_on_import_error=True."""
        import agent_audit.hooks.langchain as lc_mod

        saved = lc_mod._HAS_LANGCHAIN
        try:
            lc_mod._HAS_LANGCHAIN = False

            with pytest.raises(RuntimeError, match="requires langchain-core"):
                lc_mod.AuditCallbackHandler(raise_on_import_error=True)

            # With raise_on_import_error=False it should NOT raise but log a warning
            with patch.object(lc_mod.logger, "warning") as mock_warn:
                h = lc_mod.AuditCallbackHandler(raise_on_import_error=False)
                mock_warn.assert_called_once()
        finally:
            lc_mod._HAS_LANGCHAIN = saved

    def test_base_class_fallback_on_missing_langchain(self):
        """BaseCallbackHandler falls back to object when langchain is absent."""
        import agent_audit.hooks.langchain as lc_mod

        saved = lc_mod._HAS_LANGCHAIN
        saved_base = lc_mod.BaseCallbackHandler
        try:
            lc_mod._HAS_LANGCHAIN = False
            lc_mod.BaseCallbackHandler = object
            # Raising should work
            with pytest.raises(RuntimeError, match="requires langchain-core"):
                lc_mod.AuditCallbackHandler(raise_on_import_error=True)
        finally:
            lc_mod._HAS_LANGCHAIN = saved
            lc_mod.BaseCallbackHandler = saved_base


# ── Core handler tests ──────────────────────────────────────────────


class TestAuditCallbackHandlerInit:
    """Constructor and session management."""

    def test_default_agent_id(self, mock_engine):
        from agent_audit.hooks.langchain import AuditCallbackHandler

        h = AuditCallbackHandler()
        assert h.agent_id == "langchain-agent"

    def test_custom_agent_id(self, mock_engine):
        from agent_audit.hooks.langchain import AuditCallbackHandler

        h = AuditCallbackHandler(agent_id="my-bot")
        assert h.agent_id == "my-bot"

    def test_auto_session_id(self, mock_engine):
        from agent_audit.hooks.langchain import AuditCallbackHandler

        h = AuditCallbackHandler(agent_id="b", session_id=None)
        assert h.session_id  # Should be a generated UUID string
        assert len(h.session_id) == 36  # Standard UUID format

    def test_explicit_session_id(self, mock_engine):
        from agent_audit.hooks.langchain import AuditCallbackHandler

        h = AuditCallbackHandler(agent_id="b", session_id="sess-001")
        assert h.session_id == "sess-001"

    def test_custom_prompt_version(self, mock_engine):
        from agent_audit.hooks.langchain import AuditCallbackHandler

        h = AuditCallbackHandler(prompt_version="v2.3")
        assert h._prompt_version == "v2.3"


# ── LLM callback tests ──────────────────────────────────────────────


class TestLLMCallbacks:
    """on_llm_start / on_llm_end / on_llm_error tests."""

    def test_llm_start_end_records_event(self, handler, mock_engine):
        serialized = {"name": "gpt-4", "_type": "chat"}
        handler.on_llm_start(serialized, ["What is AI?"], run_id="run-1")
        resp = FakeLLMResult(
            generations=[[FakeGeneration("AI is artificial intelligence")]],
            llm_output={"token_usage": {"input_tokens": 5, "output_tokens": 10}},
        )
        handler.on_llm_end(resp, run_id="run-1")

        mock_engine.log.assert_called_once()
        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "model_request"
        assert kwargs["agent_id"] == "test-agent"
        assert kwargs["session_id"] == "test-sess-42"
        assert kwargs["prompt_version"] == "langchain"
        assert kwargs["input_text"] == "What is AI?"
        assert "AI is artificial intelligence" in kwargs["output_text"]
        meta = kwargs["metadata"]
        assert meta["model"] == "gpt-4"
        assert meta["hook"] == "langchain"
        assert meta["callback"] == "on_llm_end"
        assert meta["latency_ms"] >= 0
        assert meta["token_usage"]["input_tokens"] == 5

    def test_llm_start_end_without_token_usage(self, handler, mock_engine):
        """LLMResult without token_usage still works."""
        serialized = {"name": "claude-3"}
        handler.on_llm_start(serialized, ["Hello"], run_id="run-2")
        resp = FakeLLMResult(
            generations=[[FakeGeneration("Hi there")]],
            llm_output={},
        )
        handler.on_llm_end(resp, run_id="run-2")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "model_request"
        # token_usage should be empty dict
        assert kwargs["metadata"]["token_usage"] == {}

    def test_llm_start_end_with_usage_metadata(self, handler, mock_engine):
        """LLMResult with usage_metadata attribute (LangChain v0.3+)."""
        serialized = {"name": "gpt-4o"}
        handler.on_llm_start(serialized, ["Test"], run_id="run-3")
        resp = FakeLLMResult(
            generations=[[FakeGeneration("Response")]],
        )
        resp.usage_metadata = FakeUsageMetadata(
            input_tokens=100, output_tokens=50, total_tokens=150
        )
        handler.on_llm_end(resp, run_id="run-3")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["metadata"]["token_usage"]["total_tokens"] == 150
        assert kwargs["metadata"]["token_usage"]["input_tokens"] == 100

    def test_llm_end_without_start_does_not_crash(self, handler, mock_engine):
        """Calling on_llm_end without a preceding on_llm_start is safe."""
        resp = FakeLLMResult(
            generations=[[FakeGeneration("text")]],
        )
        handler.on_llm_end(resp, run_id="orphan-run")

        mock_engine.log.assert_called_once()
        _, kwargs = mock_engine.log.call_args
        assert kwargs["metadata"]["model"] == "unknown"

    def test_llm_error_records_event(self, handler, mock_engine):
        serialized = {"name": "gpt-4"}
        handler.on_llm_start(serialized, ["Query"], run_id="run-e1")
        handler.on_llm_error(ValueError("Rate limit exceeded"), run_id="run-e1")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "error"
        assert "Rate limit exceeded" in kwargs["output_text"]
        assert kwargs["metadata"]["error_type"] == "ValueError"
        assert kwargs["metadata"]["callback"] == "on_llm_error"

    def test_llm_prompt_truncation(self, handler, mock_engine):
        """Very long prompts are truncated to 2000 chars."""
        long_prompt = "x" * 5000
        serialized = {"name": "test-model"}
        handler.on_llm_start(serialized, [long_prompt], run_id="run-t1")

        # Access the internal tracker to verify truncation
        ctx = handler._tracker._store.get("run-t1")
        assert ctx is not None
        assert len(ctx["meta"]["prompt_preview"]) <= 2000


# ── Tool callback tests ─────────────────────────────────────────────


class TestToolCallbacks:
    """on_tool_start / on_tool_end / on_tool_error tests."""

    def test_tool_start_end_records_event(self, handler, mock_engine):
        serialized = {"name": "calculator"}
        handler.on_tool_start(serialized, "2+2", run_id="run-4")
        handler.on_tool_end("4", run_id="run-4")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "tool_call"
        assert kwargs["input_text"] == "2+2"
        assert kwargs["output_text"] == "4"
        meta = kwargs["metadata"]
        assert meta["tool_name"] == "calculator"
        assert meta["hook"] == "langchain"
        assert meta["callback"] == "on_tool_end"
        assert meta["latency_ms"] >= 0

    def test_tool_input_truncation(self, handler, mock_engine):
        """Very long tool inputs are truncated."""
        long_input = "z" * 5000
        serialized = {"name": "big_tool"}
        handler.on_tool_start(serialized, long_input, run_id="run-ti1")

        ctx = handler._tracker._store.get("run-ti1")
        assert ctx is not None
        assert len(ctx["meta"]["input"]) <= 4000

    def test_tool_error_records_event(self, handler, mock_engine):
        serialized = {"name": "filesystem"}
        handler.on_tool_start(serialized, "/etc/passwd", run_id="run-e2")
        handler.on_tool_error(PermissionError("Access denied"), run_id="run-e2")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "error"
        assert kwargs["metadata"]["tool_name"] == "filesystem"
        assert kwargs["metadata"]["error_type"] == "PermissionError"

    def test_tool_end_without_start_does_not_crash(self, handler, mock_engine):
        handler.on_tool_end("result", run_id="ghost-run")

        mock_engine.log.assert_called_once()
        _, kwargs = mock_engine.log.call_args
        assert kwargs["metadata"]["tool_name"] == "unknown"


# ── Chain callback tests ────────────────────────────────────────────


class TestChainCallbacks:
    """on_chain_start / on_chain_end / on_chain_error tests."""

    def test_chain_start_end_records_event(self, handler, mock_engine):
        serialized = {"name": "MyRAGChain"}
        handler.on_chain_start(
            serialized, {"query": "what is AI?"}, run_id="run-5"
        )
        handler.on_chain_end({"answer": "It is..."}, run_id="run-5")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "chain_step"
        assert kwargs["metadata"]["chain_name"] == "MyRAGChain"
        assert kwargs["metadata"]["hook"] == "langchain"
        assert kwargs["metadata"]["callback"] == "on_chain_end"
        assert kwargs["metadata"]["latency_ms"] >= 0

    def test_chain_error_records_event(self, handler, mock_engine):
        serialized = {"name": "failing_chain"}
        handler.on_chain_start(serialized, {"x": 1}, run_id="run-e3")
        handler.on_chain_error(RuntimeError("Chain broke"), run_id="run-e3")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "error"
        assert kwargs["metadata"]["error_type"] == "RuntimeError"


# ── Agent callback tests ────────────────────────────────────────────


class TestAgentCallbacks:
    """on_agent_action / on_agent_finish tests."""

    def test_agent_action_records_decision(self, handler, mock_engine):
        action = FakeAgentAction(tool="google_search", tool_input="weather", log="Searching for weather")
        handler.on_agent_action(action, run_id="run-6")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "decision"
        assert "TOOL: google_search" in kwargs["output_text"]
        meta = kwargs["metadata"]
        assert meta["tool_name"] == "google_search"
        assert meta["hook"] == "langchain"
        assert meta["callback"] == "on_agent_action"

    def test_agent_finish_records_decision(self, handler, mock_engine):
        finish = FakeAgentFinish(
            return_values={"output": "The answer is 42"},
            log="Agent concluded",
        )
        handler.on_agent_finish(finish, run_id="run-7")

        _, kwargs = mock_engine.log.call_args
        assert kwargs["event_type"] == "decision"
        assert "The answer is 42" in kwargs["output_text"]
        assert kwargs["metadata"]["hook"] == "langchain"
        assert kwargs["metadata"]["callback"] == "on_agent_finish"
        assert "output" in kwargs["metadata"]["return_keys"]

    def test_agent_finish_no_return_values(self, handler, mock_engine):
        """AgentFinish with no return_values still works."""
        finish = FakeAgentFinish(return_values={})
        handler.on_agent_finish(finish, run_id="run-8")

        mock_engine.log.assert_called_once()


# ── Engine error tolerance tests ────────────────────────────────────


class TestEngineErrorTolerance:
    """Callbacks survive when the engine raises."""

    def test_engine_failure_does_not_propagate(self, handler, mock_engine):
        mock_engine.log.side_effect = RuntimeError("DB connection lost")

        serialized = {"name": "test-model"}
        # These should NOT raise — just log and swallow
        handler.on_llm_start(serialized, ["test"], run_id="r1")
        resp = FakeLLMResult(
            generations=[[FakeGeneration("ok")]],
        )
        handler.on_llm_end(resp, run_id="r1")

    def test_tool_callback_engine_failure(self, handler, mock_engine):
        mock_engine.log.side_effect = OSError("Disk full")

        serialized = {"name": "t"}
        handler.on_tool_start(serialized, "in", run_id="r2")
        handler.on_tool_end("out", run_id="r2")
        # Should not raise

    def test_agent_callback_engine_failure(self, handler, mock_engine):
        mock_engine.log.side_effect = RuntimeError("Dead")

        action = FakeAgentAction()
        handler.on_agent_action(action, run_id="r3")
        finish = FakeAgentFinish()
        handler.on_agent_finish(finish, run_id="r4")
        # Should not raise


# ── RunTracker unit tests ───────────────────────────────────────────


class TestRunTracker:
    """Tests for the internal _RunTracker helper."""

    def test_start_end_returns_ctx(self):
        from agent_audit.hooks.langchain import _RunTracker

        tracker = _RunTracker()
        tracker.start("abc", "llm", {"a": 1})
        ctx = tracker.end("abc")
        assert ctx is not None
        assert ctx["kind"] == "llm"
        assert ctx["meta"] == {"a": 1}
        assert "start_ts" in ctx

    def test_end_on_missing_key_returns_none(self):
        from agent_audit.hooks.langchain import _RunTracker

        tracker = _RunTracker()
        assert tracker.end("missing") is None

    def test_tracker_records_timing(self):
        from agent_audit.hooks.langchain import _RunTracker

        tracker = _RunTracker()
        tracker.start("run-x", "tool")
        time.sleep(0.01)
        ctx = tracker.end("run-x")
        assert ctx is not None
        assert ctx["start_ts"] > 0
        # Latency should be computed by the caller

    def test_clear_removes_all(self):
        from agent_audit.hooks.langchain import _RunTracker

        tracker = _RunTracker()
        tracker.start("a", "llm")
        tracker.start("b", "tool")
        assert len(tracker._store) == 2
        tracker.clear()
        assert len(tracker._store) == 0


# ── Event type mapping test ─────────────────────────────────────────


class TestEventTypeCorrectness:
    """Verify every callback produces the correct event_type."""

    EVENTS = [
        ("on_llm_end", "model_request"),
        ("on_tool_end", "tool_call"),
        ("on_chain_end", "chain_step"),
        ("on_agent_action", "decision"),
        ("on_agent_finish", "decision"),
        ("on_llm_error", "error"),
        ("on_tool_error", "error"),
        ("on_chain_error", "error"),
    ]

    @pytest.mark.parametrize("callback_name,expected_type", EVENTS)
    def test_callback_records_correct_event_type(
        self, callback_name, expected_type, mock_engine
    ):
        from agent_audit.hooks.langchain import AuditCallbackHandler

        h = AuditCallbackHandler(agent_id="a", session_id="s1")

        # Set up start data before calling end/action callbacks
        if "end" in callback_name or "error" in callback_name:
            if "llm" in callback_name:
                h.on_llm_start({"name": "m"}, [""], run_id="r1")
            elif "tool" in callback_name:
                h.on_tool_start({"name": "t"}, "", run_id="r1")
            elif "chain" in callback_name:
                h.on_chain_start({"name": "c"}, {}, run_id="r1")

        # Invoke the callback
        if callback_name == "on_llm_end":
            h.on_llm_end(
                FakeLLMResult(
                    generations=[[FakeGeneration("ok")]],
                ),
                run_id="r1",
            )
        elif callback_name == "on_tool_end":
            h.on_tool_end("out", run_id="r1")
        elif callback_name == "on_chain_end":
            h.on_chain_end({"k": "v"}, run_id="r1")
        elif callback_name == "on_llm_error":
            h.on_llm_error(ValueError("x"), run_id="r1")
        elif callback_name == "on_tool_error":
            h.on_tool_error(ValueError("x"), run_id="r1")
        elif callback_name == "on_chain_error":
            h.on_chain_error(ValueError("x"), run_id="r1")
        elif callback_name == "on_agent_action":
            h.on_agent_action(FakeAgentAction(), run_id="r1")
        elif callback_name == "on_agent_finish":
            h.on_agent_finish(FakeAgentFinish(), run_id="r1")

        _, kwargs = mock_engine.log.call_args
        assert (
            kwargs["event_type"] == expected_type
        ), f"{callback_name} should record {expected_type}, got {kwargs['event_type']}"
