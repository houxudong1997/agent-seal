"""
@observe decorator — lightweight function tracing for agent-seal.

Inspired by LangFuse's @observe pattern, this decorator records every
decorated function call into the agent-seal event store, capturing:
  - function name, input parameters, return value, execution time, timestamp
  - nested trace: @observe inside @observe auto-forms parent-child spans
  - auto-writes to agent-seal event storage via ``get_engine()``

Independent of the existing SDK monkey-patch (tracing/); they coexist
without conflict.

Usage::

    from agent_seal import observe, set_engine
    from agent_seal.engine import AuditEngine

    engine = AuditEngine("sqlite://audit.db")
    set_engine(engine)

    @observe
    def my_tool(x: int) -> str:
        return f"result-{x}"

    @observe(name="call_llm", metadata={"model": "deepseek-v4-pro"})
    def call_llm(prompt: str) -> str: ...

    @observe(name="execute_tool", category="filesystem")
    def read_file(path: str) -> str: ...

    # Nested tracing — inner calls become child spans
    @observe(name="pipeline")
    def pipeline(data):
        return call_llm(my_tool(42))  # three nested spans
"""

from __future__ import annotations

import functools
import inspect
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════ TRACING CONTEXT ═══════════════════════
# Thread / async-safe context variables for span nesting.
# Uses Python's contextvars (stdlib) — no dependency on OpenTelemetry.

_current_span: ContextVar[Optional[str]] = ContextVar(
    "observe_current_span", default=None
)
"""Current span ID — set by each @observe wrapper during execution."""

_current_engine: ContextVar[Optional[Any]] = ContextVar(
    "observe_engine", default=None
)
"""Current AuditEngine instance for writing events."""


# ═══════════════════════ PUBLIC API ═══════════════════════


def set_engine(engine) -> None:
    """Set the current AuditEngine for all @observe decorators.

    Call once at application startup::

        from agent_seal.engine import AuditEngine
        from agent_seal import observe, set_engine

        engine = AuditEngine("sqlite://audit.db")
        set_engine(engine)

    When no engine is set, @observe creates a default JSONL-backed engine
    automatically on first use.
    """
    _current_engine.set(engine)
    logger.info("observe engine set: %s", type(engine).__name__)


def get_engine():
    """Get the current AuditEngine, or create a default one.

    Returns:
        AuditEngine — either the one set via ``set_engine()`` or
        a default JSONL-backed engine at ``./audit_logs``.
    """
    engine = _current_engine.get()
    if engine is None:
        from agent_seal.engine import AuditEngine

        engine = AuditEngine()
        _current_engine.set(engine)
        logger.info("observe engine auto-created (default JSONL backend)")
    return engine


# ═══════════════════════ HELPERS ═══════════════════════


def _summarize(obj: Any, max_len: int = 200) -> str:
    """Create a concise string summary of an object for audit logging.

    Handles None, exceptions during repr/str, and truncates long values.
    """
    if obj is None:
        return "None"
    try:
        s = repr(obj)
    except Exception:
        try:
            s = str(obj)
        except Exception:
            return f"<{type(obj).__name__}>"
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def _format_args(
    args: tuple, kwargs: dict, max_per_arg: int = 200
) -> str:
    """Format positional and keyword arguments into a single summary string."""
    parts: list[str] = []
    for i, a in enumerate(args):
        # Skip 'self' / 'cls' for bound methods
        if i == 0 and isinstance(a, object) and not isinstance(a, (int, float, str, bool, list, dict, tuple, set)):
            # Likely 'self' — show class name only
            parts.append(f"self={type(a).__name__}")
        else:
            parts.append(_summarize(a, max_per_arg))
    for k, v in kwargs.items():
        parts.append(f"{k}={_summarize(v, max_per_arg)}")
    return ", ".join(parts)


def _make_span_id() -> str:
    """Generate a short, unique span ID."""
    return str(uuid.uuid4())[:12]


# ═══════════════════════ @observe DECORATOR ═══════════════════════


class observe:
    """Decorator that traces function calls into the agent-seal trail.

    Supports both parameterless and parameterised usage::

        @observe
        def my_func(x): ...

        @observe(name="custom_name", metadata={"key": "value"})
        def my_func(x): ...

        @observe(name="tool_exec", category="filesystem")
        def read_file(path): ...

    Each invocation records an audit event with:
    - Function name (user-specified or auto-detected)
    - Summarised input arguments
    - Summarised return value
    - Execution time in milliseconds
    - Timestamp
    - Span ID + parent span ID (for nested tracing)
    - Custom metadata

    Nested tracing: when an @observe-decorated function calls another
    @observe-decorated function, the inner call automatically becomes a
    child span of the outer call.  Span nesting is managed through
    ``contextvars``, making it safe across threads and asyncio tasks.

    Error handling: if the decorated function raises an exception, the
    decorator records the error and re-raises — the audit trail captures
    the failure without swallowing the exception.
    """

    def __init__(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None,
    ):
        """Initialise the decorator.

        Called once at decoration time (import / definition).

        Args:
            func: The decorated function (only when used without parens).
            name: Custom display name for this span.
            metadata: Key-value pairs attached to every event.
            category: Logical grouping (e.g. "llm", "filesystem", "api").
        """
        self._metadata: Dict[str, Any] = dict(metadata or {})
        self._category: Optional[str] = category

        if func is not None and callable(func):
            # @observe — used without parentheses
            functools.update_wrapper(self, func)
            self._func: Optional[Callable] = func
            self._name: str = name or func.__name__
        else:
            # @observe(name=..., metadata=...) — used with parentheses
            self._func = None
            self._name: str = name or ""  # resolved when __call__ receives the function

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the decorated function.

        Two code paths:

        1. Direct call — when used as ``@observe`` (no parens):
           ``args[0]`` is ``self`` (bound method) or actual args.
           We check ``self._func is not None`` and invoke the trace logic.

        2. Decorator call — when used as ``@observe(name=...)``:
           ``args[0]`` is the function to wrap.
           We create a new ``observe`` instance for it and return it.
        """
        if self._func is not None:
            # Path 1: direct invocation of the decorated function
            return self._invoke(args, kwargs)

        # Path 2: @observe(...) — wrap the function
        if not args:
            raise TypeError(
                "@observe(...) expects a function to decorate, "
                "e.g. @observe(name='x')\\ndef f(): ..."
            )
        func = args[0]
        if not callable(func):
            raise TypeError(
                f"@observe(...) expects a callable, got {type(func).__name__}"
            )
        return observe(
            func,
            name=self._name or None,
            metadata=self._metadata or None,
            category=self._category,
        )

    def _invoke(self, args: tuple, kwargs: dict) -> Any:
        """Core tracing logic — invoked on every decorated function call."""
        func = self._func
        if func is None:
            raise RuntimeError("observe._invoke called with no wrapped function")

        # ── Pre-call setup ───────────────────────────────────
        parent_span_id: Optional[str] = _current_span.get()
        span_id: str = _make_span_id()
        start_time: float = time.monotonic()
        arg_summary: str = _format_args(args, kwargs)

        # Set current span for potential nested @observe calls
        token = _current_span.set(span_id)

        try:
            # ── Execute ──────────────────────────────────────
            result = func(*args, **kwargs)
            elapsed_ms: float = (time.monotonic() - start_time) * 1000
            output_summary: str = _summarize(result)

            # ── Build metadata ───────────────────────────────
            md: Dict[str, Any] = dict(self._metadata)
            md["span_id"] = span_id
            if parent_span_id:
                md["parent_span_id"] = parent_span_id
            if self._category:
                md["category"] = self._category
            md["elapsed_ms"] = round(elapsed_ms, 3)

            # ── Write success event ──────────────────────────
            self._write_event(
                engine=get_engine(),
                session_id=f"observe-{self._name}",
                event_type="observe",
                agent_id=self._name,
                input_text=arg_summary,
                output_text=output_summary,
                metadata=md,
            )

            logger.debug(
                "observe: %s span=%s parent=%s elapsed=%.1fms",
                self._name,
                span_id,
                parent_span_id or "-",
                elapsed_ms,
            )

            return result

        except Exception as exc:
            # ── Error handling ───────────────────────────────
            elapsed_ms = (time.monotonic() - start_time) * 1000

            md = dict(self._metadata)
            md["span_id"] = span_id
            if parent_span_id:
                md["parent_span_id"] = parent_span_id
            if self._category:
                md["category"] = self._category
            md["elapsed_ms"] = round(elapsed_ms, 3)
            md["error"] = f"{type(exc).__name__}: {str(exc)}"

            self._write_event(
                engine=get_engine(),
                session_id=f"observe-{self._name}",
                event_type="observe_error",
                agent_id=self._name,
                input_text=arg_summary,
                output_text=f"ERROR: {type(exc).__name__}: {str(exc)}"[:8000],
                metadata=md,
            )

            logger.debug(
                "observe: %s span=%s ERROR %s elapsed=%.1fms",
                self._name,
                span_id,
                type(exc).__name__,
                elapsed_ms,
            )

            raise

        finally:
            # ── Restore parent span ─────────────────────────
            _current_span.reset(token)

    @staticmethod
    def _write_event(
        engine,
        session_id: str,
        event_type: str,
        agent_id: str,
        input_text: str,
        output_text: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Write an observe event to the audit trail.

        Failures are logged but never raised — the decorator must not
        interfere with the decorated function's behaviour.
        """
        try:
            engine.log(
                session_id=session_id,
                event_type=event_type,
                agent_id=agent_id,
                prompt_version="",
                input_text=input_text[:8000],
                output_text=output_text[:8000],
                metadata=metadata,
            )
        except Exception:
            logger.exception(
                "observe: failed to write event for %s (session=%s)",
                agent_id,
                session_id,
            )
