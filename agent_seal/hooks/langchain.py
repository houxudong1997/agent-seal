"""
LangChain / LangChain-compatible CallbackHandler for agent-seal.

Records every LLM call, tool invocation, chain step, and agent decision
into the agent-seal hash-chained audit trail via the AuditEngine singleton.

Usage::

    from agent_seal.hooks.langchain import AuditCallbackHandler
    handler = AuditCallbackHandler(agent_id="my-agent")
    # Pass handler to your LangChain executor / agent / chain

Dependencies:
    langchain is an **optional** dependency — not listed in requirements.txt.
    Install it yourself:  pip install langchain langchain-core

    When langchain is unavailable the module still imports, but
    AuditCallbackHandler raises a friendly RuntimeError on instantiation.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import suppress
from typing import Any

from agent_seal.server.dependencies import get_engine

logger = logging.getLogger(__name__)

# ── Optional langchain import ────────────────────────────────────────────
# langchain is NOT a hard dependency. If absent, AuditCallbackHandler
# will still be importable but raises a helpful error on instantiation.
_HAS_LANGCHAIN = False
try:
    from langchain_core.callbacks.base import BaseCallbackHandler  # type: ignore[import-untyped]

    _HAS_LANGCHAIN = True
except ImportError:
    BaseCallbackHandler = object  # type: ignore[assignment,misc]


# ── Internal state tracking ──────────────────────────────────────────────
# Stores per-run_id timing/context between on_*_start and on_*_end calls.
# Keys are run_id (UUID string), values are dicts with start-time etc.


class _RunTracker:
    """Thread-safe mini store for correlating start → end callbacks."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def start(self, run_id: str, kind: str, meta: dict[str, Any] | None = None) -> None:
        self._store[run_id] = {
            "kind": kind,
            "start_ts": time.time(),
            "meta": meta or {},
        }

    def end(self, run_id: str) -> dict[str, Any] | None:
        return self._store.pop(run_id, None)

    def clear(self) -> None:
        self._store.clear()


# ── CallbackHandler ──────────────────────────────────────────────────────


class AuditCallbackHandler(BaseCallbackHandler):  # type: ignore[valid-type,misc]
    """LangChain callback handler that records all activity into agent-seal.

    Auto-connects to the AuditEngine singleton (configures via environment
    variables / ``.env``).  Each callback writes a hash-chained audit event
    with the appropriate event_type:

    ===================== =================== ===========================
    Callback               Event Type          Data logged
    ===================== =================== ===========================
    on_llm_start/end       ``model_request``   model, prompt, tokens, latency
    on_tool_start/end      ``tool_call``       tool_name, input, output, latency
    on_chain_start/end     ``chain_step``      chain_name, inputs, outputs
    on_agent_action/finish ``decision``        tool decision / final answer
    ===================== =================== ===========================

    Parameters:
        agent_id: Identifier for the agent whose activity is being recorded.
        session_id: Audit session id.  Auto-generated (uuid4) when omitted.
        prompt_version: Prompt version tag (default ``"langchain"``).
        raise_on_import_error: Silently pass or raise when ``langchain`` is
            absent (default ``True`` raises a helpful RuntimeError).

    Raises:
        RuntimeError: If ``langchain-core`` is not installed AND
            ``raise_on_import_error`` is ``True`` (the default).
    """

    def __init__(
        self,
        agent_id: str = "langchain-agent",
        session_id: str | None = None,
        prompt_version: str = "langchain",
        raise_on_import_error: bool = True,
    ) -> None:
        if not _HAS_LANGCHAIN:
            msg = (
                "AuditCallbackHandler requires langchain-core. "
                "Install it with:  pip install langchain langchain-core"
            )
            if raise_on_import_error:
                raise RuntimeError(msg)
            logger.warning(msg)

        self._agent_id = agent_id
        self._session_id = session_id or str(uuid.uuid4())
        self._prompt_version = prompt_version
        self._tracker = _RunTracker()
        self._engine = get_engine()

    # ── LLM callbacks ────────────────────────────────────────────────

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs: Any,
    ) -> None:
        """Record the start of an LLM call."""
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        model = serialized.get("name", serialized.get("id", serialized.get("_type", "unknown")))
        self._tracker.start(
            run_id,
            "llm",
            {
                "model": model,
                "prompt_count": len(prompts),
                "prompt_preview": prompts[0][:2000] if prompts else "",
            },
        )

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """Record the end of an LLM call."""
        run_id = str(kwargs.get("run_id", ""))
        ctx = self._tracker.end(run_id) or {}
        meta = ctx.get("meta", {})
        start_ts = ctx.get("start_ts", time.time())
        latency_ms = int((time.time() - start_ts) * 1000)

        # Extract token counts from the response (LLMResult)
        token_usage: dict[str, int] = {}
        result_text = ""
        with suppress(Exception):
            generations = getattr(response, "generations", None)
            if generations:
                for gen_list in generations or []:
                    for gen in gen_list or []:
                        result_text += str(getattr(gen, "text", gen))
            # llm_output often carries token_usage
            llm_output = getattr(response, "llm_output", None) or {}
            token_usage = llm_output.get("token_usage", {}) or {}
            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                if usage:
                    token_usage = {
                        "input_tokens": getattr(usage, "input_tokens", 0),
                        "output_tokens": getattr(usage, "output_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                    }

        try:
            self._engine.log(
                session_id=self._session_id,
                event_type="model_request",
                agent_id=self._agent_id,
                prompt_version=self._prompt_version,
                input_text=meta.get("prompt_preview", ""),
                output_text=result_text[:4000],
                metadata={
                    "model": meta.get("model", "unknown"),
                    "prompt_count": meta.get("prompt_count", 0),
                    "latency_ms": latency_ms,
                    "token_usage": token_usage,
                    "hook": "langchain",
                    "callback": "on_llm_end",
                },
            )
        except Exception:
            logger.exception("Failed to record LLM call audit event")

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        """Record an LLM error."""
        run_id = str(kwargs.get("run_id", ""))
        ctx = self._tracker.end(run_id) or {}
        start_ts = ctx.get("start_ts", time.time())
        latency_ms = int((time.time() - start_ts) * 1000)
        try:
            self._engine.log(
                session_id=self._session_id,
                event_type="error",
                agent_id=self._agent_id,
                prompt_version=self._prompt_version,
                input_text="",
                output_text=str(error)[:2000],
                metadata={
                    "latency_ms": latency_ms,
                    "error_type": type(error).__name__,
                    "hook": "langchain",
                    "callback": "on_llm_error",
                },
            )
        except Exception:
            logger.exception("Failed to record LLM error audit event")

    # ── Tool callbacks ───────────────────────────────────────────────

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Record the start of a tool invocation."""
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        tool_name = serialized.get("name", "unknown_tool")
        self._tracker.start(
            run_id,
            "tool",
            {"tool_name": tool_name, "input": input_str[:4000]},
        )

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Record the end of a tool invocation."""
        run_id = str(kwargs.get("run_id", ""))
        ctx = self._tracker.end(run_id) or {}
        meta = ctx.get("meta", {})
        start_ts = ctx.get("start_ts", time.time())
        latency_ms = int((time.time() - start_ts) * 1000)
        try:
            self._engine.log(
                session_id=self._session_id,
                event_type="tool_call",
                agent_id=self._agent_id,
                prompt_version=self._prompt_version,
                input_text=meta.get("input", ""),
                output_text=str(output)[:4000],
                metadata={
                    "tool_name": meta.get("tool_name", "unknown"),
                    "latency_ms": latency_ms,
                    "hook": "langchain",
                    "callback": "on_tool_end",
                },
            )
        except Exception:
            logger.exception("Failed to record tool call audit event")

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        """Record a tool error."""
        run_id = str(kwargs.get("run_id", ""))
        ctx = self._tracker.end(run_id) or {}
        meta = ctx.get("meta", {})
        start_ts = ctx.get("start_ts", time.time())
        latency_ms = int((time.time() - start_ts) * 1000)
        try:
            self._engine.log(
                session_id=self._session_id,
                event_type="error",
                agent_id=self._agent_id,
                prompt_version=self._prompt_version,
                input_text=str(meta.get("input", "")),
                output_text=str(error)[:2000],
                metadata={
                    "tool_name": meta.get("tool_name", "unknown"),
                    "latency_ms": latency_ms,
                    "error_type": type(error).__name__,
                    "hook": "langchain",
                    "callback": "on_tool_error",
                },
            )
        except Exception:
            logger.exception("Failed to record tool error audit event")

    # ── Chain callbacks ──────────────────────────────────────────────

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """Record the start of a chain step."""
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        chain_name = serialized.get("name", serialized.get("id", "unknown_chain"))
        self._tracker.start(
            run_id,
            "chain",
            {"chain_name": chain_name, "input_keys": list(inputs.keys())},
        )

    def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any) -> None:
        """Record the end of a chain step."""
        run_id = str(kwargs.get("run_id", ""))
        ctx = self._tracker.end(run_id) or {}
        meta = ctx.get("meta", {})
        start_ts = ctx.get("start_ts", time.time())
        latency_ms = int((time.time() - start_ts) * 1000)
        try:
            self._engine.log(
                session_id=self._session_id,
                event_type="chain_step",
                agent_id=self._agent_id,
                prompt_version=self._prompt_version,
                input_text=str(meta.get("input_keys", [])),
                output_text=str(list(outputs.keys()))[:4000],
                metadata={
                    "chain_name": meta.get("chain_name", "unknown"),
                    "latency_ms": latency_ms,
                    "hook": "langchain",
                    "callback": "on_chain_end",
                },
            )
        except Exception:
            logger.exception("Failed to record chain step audit event")

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> None:
        """Record a chain error."""
        run_id = str(kwargs.get("run_id", ""))
        ctx = self._tracker.end(run_id) or {}
        meta = ctx.get("meta", {})
        start_ts = ctx.get("start_ts", time.time())
        latency_ms = int((time.time() - start_ts) * 1000)
        try:
            self._engine.log(
                session_id=self._session_id,
                event_type="error",
                agent_id=self._agent_id,
                prompt_version=self._prompt_version,
                input_text=str(meta.get("chain_name", "")),
                output_text=str(error)[:2000],
                metadata={
                    "latency_ms": latency_ms,
                    "error_type": type(error).__name__,
                    "hook": "langchain",
                    "callback": "on_chain_error",
                },
            )
        except Exception:
            logger.exception("Failed to record chain error audit event")

    # ── Agent callbacks ──────────────────────────────────────────────

    def on_agent_action(
        self,
        action: Any,
        **kwargs: Any,
    ) -> None:
        """Record an agent's decision to use a tool."""
        tool_name = getattr(action, "tool", "unknown")
        tool_input = getattr(action, "tool_input", "")
        run_id = str(kwargs.get("run_id", uuid.uuid4()))
        try:
            self._engine.log(
                session_id=self._session_id,
                event_type="decision",
                agent_id=self._agent_id,
                prompt_version=self._prompt_version,
                input_text=str(getattr(action, "log", ""))[:4000],
                output_text=f"TOOL: {tool_name}",
                metadata={
                    "tool_name": tool_name,
                    "tool_input": str(tool_input)[:2000],
                    "hook": "langchain",
                    "callback": "on_agent_action",
                },
            )
        except Exception:
            logger.exception("Failed to record agent action audit event")

    def on_agent_finish(
        self,
        finish: Any,
        **kwargs: Any,
    ) -> None:
        """Record an agent's final answer."""
        return_values = getattr(finish, "return_values", {}) or {}
        output_text = return_values.get("output", str(finish))
        log_text = getattr(finish, "log", "")
        try:
            self._engine.log(
                session_id=self._session_id,
                event_type="decision",
                agent_id=self._agent_id,
                prompt_version=self._prompt_version,
                input_text=str(log_text)[:4000],
                output_text=str(output_text)[:4000],
                metadata={
                    "hook": "langchain",
                    "callback": "on_agent_finish",
                    "return_keys": list(return_values.keys()),
                },
            )
        except Exception:
            logger.exception("Failed to record agent finish audit event")

    # ── Public helpers ───────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        """The audit session id being recorded."""
        return self._session_id

    @property
    def agent_id(self) -> str:
        """The agent identifier."""
        return self._agent_id
