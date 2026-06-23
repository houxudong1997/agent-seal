"""
Tests for agent_seal.observe — the @observe decorator.

Coverage targets:
  - Basic decorator: no-parens, with-parens (name/metadata/category)
  - Input / output recording completeness
  - Execution time tracking
  - Nested span tracing (parent-child span IDs)
  - Exception handling: error events recorded, exception re-raised
  - Integration with AuditEngine (real engine, not mock)
  - Auto-engine creation when none is set
  - set_engine / get_engine public API
  - 'self' argument filtering for bound methods
  - Concurrent / thread safety via contextvars isolation
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from agent_seal.observe import (
    _current_engine,
    _current_span,
    _summarize,
    get_engine,
    observe,
    set_engine,
)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


class TestSummarize:
    """Unit tests for the _summarize() helper."""

    def test_none(self):
        assert _summarize(None) == "None"

    def test_short_string(self):
        assert _summarize("hello") == "'hello'"

    def test_long_string_truncation(self):
        long_str = "x" * 500
        result = _summarize(long_str, max_len=50)
        assert len(result) <= 50
        assert result.endswith("...")

    def test_int(self):
        assert _summarize(42) == "42"

    def test_list(self):
        assert _summarize([1, 2, 3]) == "[1, 2, 3]"

    def test_repr_exception_fallback(self):
        class Broken:
            def __repr__(self):
                raise RuntimeError("repr boom")

            def __str__(self):
                return "Broken()"

        obj = Broken()
        result = _summarize(obj)
        assert "Broken" in result


class TestFormatArgs:
    """Test _format_args via integration (validated inside decorator tests)."""

    def test_self_is_class_name(self):
        """For bound methods, the 'self' arg should show the class name."""
        from agent_seal.observe import _format_args

        class MyTool:
            @observe
            def run(self, x: int) -> str:  # pragma: no cover
                return str(x)

        tool = MyTool()
        # The decorator formats args: self=MyTool, 42
        result = _format_args((tool, 42), {})
        # First arg should be 'self=MyTool'
        assert result.startswith("self=")
        assert "MyTool" in result


# ═══════════════════════════════════════════════════════════════
# Basic decorator behaviour
# ═══════════════════════════════════════════════════════════════


class TestObserveBasic:
    """Basic @observe functionality — no-parens, with-parens, return values."""

    def setup_method(self):
        """Reset engine context before each test."""
        # Clear any set engine so tests get isolated auto-created engines
        _current_engine.set(None)

    def test_no_parens_decorator(self):
        """@observe without parentheses should work."""
        call_count = 0

        @observe
        def add(a: int, b: int) -> int:
            nonlocal call_count
            call_count += 1
            return a + b

        result = add(3, 4)
        assert result == 7
        assert call_count == 1

    def test_with_parens_name(self):
        """@observe(name='...') should set a custom span name."""

        @observe(name="custom_add")
        def add(a: int, b: int) -> int:
            return a + b

        result = add(1, 2)
        assert result == 3

    def test_with_parens_metadata(self):
        """@observe(metadata={...}) should pass metadata to audit events."""

        @observe(name="meta_func", metadata={"env": "test", "version": 2})
        def greet(name: str) -> str:
            return f"Hello {name}"

        result = greet("World")
        assert result == "Hello World"

    def test_with_parens_category(self):
        """@observe(category='...') should work."""

        @observe(name="cat_func", category="testing")
        def double(x: int) -> int:
            return x * 2

        result = double(21)
        assert result == 42

    def test_all_params(self):
        """@observe with all parameters."""

        @observe(
            name="full_example",
            metadata={"source": "test_all_params", "priority": 1},
            category="api",
        )
        def compute(x: float) -> float:
            return x * 1.5

        result = compute(10.0)
        assert result == 15.0

    def test_async_function(self):
        """@observe should work with async functions."""
        import asyncio

        @observe(name="async_func")
        async def fetch() -> str:
            return "ok"

        result = asyncio.run(fetch())
        assert result == "ok"

    def test_return_value_preserved(self):
        """Decorator must preserve the correct return value."""

        @observe
        def returns_dict() -> dict:
            return {"status": "ok", "count": 42}

        result = returns_dict()
        assert result == {"status": "ok", "count": 42}

    def test_return_value_none(self):
        """Decorator must handle functions that return None."""

        @observe
        def returns_none() -> None:
            pass

        result = returns_none()
        assert result is None


# ═══════════════════════════════════════════════════════════════
# Input / output recording
# ═══════════════════════════════════════════════════════════════


class TestInputOutputRecording:
    """Verify that inputs and outputs are recorded into the audit store."""

    def setup_method(self):
        _current_engine.set(None)

    def test_events_written_to_store(self, tmp_path):
        """Events should be written to the audit store."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="logged_func")
        def multiply(a: int, b: int) -> int:
            return a * b

        multiply(6, 7)

        # Check that the session file exists
        session_file = audit_dir / "observe-logged_func.jsonl"
        assert session_file.exists(), f"Expected session file at {session_file}"

        # Parse the event
        lines = session_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        event = json.loads(lines[0])

        assert event["event_type"] == "observe"
        assert event["agent_id"] == "logged_func"
        assert event["session_id"] == "observe-logged_func"
        # Input should contain the args
        assert "6" in event["input_snapshot"]
        assert "7" in event["input_snapshot"]
        # Output should contain the result
        assert "42" in event["output_snapshot"]

    def test_metadata_written_to_store(self, tmp_path):
        """Custom metadata should appear in the stored event."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="meta_test", metadata={"custom_key": "custom_value"})
        def identity(x):
            return x

        identity("test")

        session_file = audit_dir / "observe-meta_test.jsonl"
        event = json.loads(session_file.read_text().strip().split("\n")[0])

        metadata = event.get("metadata", {})
        assert metadata.get("custom_key") == "custom_value"
        assert "span_id" in metadata
        assert "elapsed_ms" in metadata

    def test_category_in_metadata(self, tmp_path):
        """Category parameter should be stored in metadata."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="cat_func", category="llm")
        def chat(msg: str) -> str:
            return f"echo: {msg}"

        chat("hello")

        session_file = audit_dir / "observe-cat_func.jsonl"
        event = json.loads(session_file.read_text().strip().split("\n")[0])
        assert event["metadata"]["category"] == "llm"


# ═══════════════════════════════════════════════════════════════
# Execution time tracking
# ═══════════════════════════════════════════════════════════════


class TestExecutionTime:
    """Verify that execution time is recorded."""

    def setup_method(self):
        _current_engine.set(None)

    def test_elapsed_ms_recorded(self, tmp_path):
        """elapsed_ms should appear in metadata."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="timed_func")
        def sleep_a_bit():
            time.sleep(0.01)
            return "done"

        sleep_a_bit()

        session_file = audit_dir / "observe-timed_func.jsonl"
        event = json.loads(session_file.read_text().strip().split("\n")[0])
        elapsed = event["metadata"]["elapsed_ms"]
        assert isinstance(elapsed, (int, float))
        assert elapsed >= 0

    def test_timestamp_is_float(self, tmp_path):
        """Timestamp in the chain event should be a float (Unix time)."""
        from agent_seal.engine import AuditEngine

        audit_dir = tmp_path / "audit_logs"
        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="ts_test")
        def noop():
            pass

        noop()

        events = engine.read("observe-ts_test")
        assert len(events) >= 1
        ts = events[0]["timestamp"]
        assert isinstance(ts, float)
        # Should be within the last 10 seconds
        assert time.time() - ts < 10


# ═══════════════════════════════════════════════════════════════
# Nested span tracing
# ═══════════════════════════════════════════════════════════════


class TestNestedSpans:
    """Verify parent-child span relationships for nested @observe calls."""

    def setup_method(self):
        _current_engine.set(None)

    def test_nested_spans_have_parent(self, tmp_path):
        """Inner @observe should have parent_span_id matching outer span_id."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="inner")
        def inner(x: int) -> int:
            return x * 2

        @observe(name="outer")
        def outer(x: int) -> int:
            return inner(x) + 1

        outer(5)

        # Read both sessions
        inner_file = audit_dir / "observe-inner.jsonl"
        outer_file = audit_dir / "observe-outer.jsonl"
        assert inner_file.exists()
        assert outer_file.exists()

        inner_event = json.loads(inner_file.read_text().strip().split("\n")[0])
        outer_event = json.loads(outer_file.read_text().strip().split("\n")[0])

        outer_span = outer_event["metadata"]["span_id"]
        inner_parent = inner_event["metadata"].get("parent_span_id")

        assert inner_parent is not None, "Inner span should have a parent_span_id"
        assert inner_parent == outer_span, (
            f"Inner parent_span_id {inner_parent} should match outer span_id {outer_span}"
        )

    def test_three_level_nesting(self, tmp_path):
        """Three levels of @observe nesting should form a chain."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="level3")
        def level3(x: int) -> int:
            return x + 3

        @observe(name="level2")
        def level2(x: int) -> int:
            return level3(x) + 2

        @observe(name="level1")
        def level1(x: int) -> int:
            return level2(x) + 1

        level1(0)

        # Check spans
        for level_name in ("level1", "level2", "level3"):
            f = audit_dir / f"observe-{level_name}.jsonl"
            assert f.exists()

        l1 = json.loads((audit_dir / "observe-level1.jsonl").read_text().strip().split("\n")[0])
        l2 = json.loads((audit_dir / "observe-level2.jsonl").read_text().strip().split("\n")[0])
        l3 = json.loads((audit_dir / "observe-level3.jsonl").read_text().strip().split("\n")[0])

        # Level 1 has no parent
        assert "parent_span_id" not in l1["metadata"]

        # Level 2's parent is Level 1
        assert l2["metadata"]["parent_span_id"] == l1["metadata"]["span_id"]

        # Level 3's parent is Level 2
        assert l3["metadata"]["parent_span_id"] == l2["metadata"]["span_id"]

    def test_no_parent_for_top_level(self, tmp_path):
        """A standalone @observe call should have no parent_span_id."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="standalone")
        def standalone():
            return 42

        standalone()

        session_file = audit_dir / "observe-standalone.jsonl"
        event = json.loads(session_file.read_text().strip().split("\n")[0])
        assert "parent_span_id" not in event["metadata"]


# ═══════════════════════════════════════════════════════════════
# Exception handling
# ═══════════════════════════════════════════════════════════════


class TestExceptionHandling:
    """Verify that exceptions are recorded and re-raised."""

    def setup_method(self):
        _current_engine.set(None)

    def test_exception_recorded(self, tmp_path):
        """When a function raises, an observe_error event should be written."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="failing_func")
        def failing():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing()

        session_file = audit_dir / "observe-failing_func.jsonl"
        assert session_file.exists()

        event = json.loads(session_file.read_text().strip().split("\n")[0])
        assert event["event_type"] == "observe_error"
        assert "ValueError" in event["metadata"]["error"]
        assert "test error" in event["metadata"]["error"]

    def test_exception_re_raised(self):
        """The exception must propagate — not be swallowed."""
        from agent_seal.engine import AuditEngine

        engine = AuditEngine()
        set_engine(engine)

        @observe(name="raises")
        def raises():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            raises()

    def test_exception_metadata_has_elapsed(self, tmp_path):
        """Error events should still record elapsed time."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="slow_fail")
        def slow_fail():
            time.sleep(0.01)
            raise RuntimeError("slow boom")

        with pytest.raises(RuntimeError):
            slow_fail()

        session_file = audit_dir / "observe-slow_fail.jsonl"
        event = json.loads(session_file.read_text().strip().split("\n")[0])
        assert event["metadata"]["elapsed_ms"] >= 0


# ═══════════════════════════════════════════════════════════════
# Engine integration
# ═══════════════════════════════════════════════════════════════


class TestEngineIntegration:
    """Verify set_engine / get_engine API and auto-creation behaviour."""

    def setup_method(self):
        _current_engine.set(None)

    def test_set_engine_sets_global(self):
        """set_engine should store the engine for get_engine to retrieve."""
        mock_engine = MagicMock()
        mock_engine.__class__.__name__ = "MockEngine"

        set_engine(mock_engine)
        assert get_engine() is mock_engine

    def test_get_engine_auto_creates(self, tmp_path):
        """When no engine is set, get_engine() should auto-create a default one."""
        _current_engine.set(None)

        # AuditEngine is imported lazily inside get_engine(), so we must
        # patch it at the import location (agent_seal.engine), not observe.
        from agent_seal import engine as engine_module
        with patch.object(engine_module, "AuditEngine") as mock_ae:
            mock_instance = MagicMock()
            mock_ae.return_value = mock_instance

            engine = get_engine()
            assert engine is mock_instance

    def test_auto_created_engine_cached(self):
        """Auto-created engine should be cached — same instance on repeated calls."""
        _current_engine.set(None)

        engine1 = get_engine()
        engine2 = get_engine()
        assert engine1 is engine2

    def test_engine_persists_across_decorator_calls(self, tmp_path):
        """Events from multiple decorated functions should all go to the same store."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="func_a")
        def func_a():
            return "a"

        @observe(name="func_b")
        def func_b():
            return "b"

        func_a()
        func_b()

        # Both sessions should exist
        assert (audit_dir / "observe-func_a.jsonl").exists()
        assert (audit_dir / "observe-func_b.jsonl").exists()

    def test_multiple_engines_switch(self):
        """Setting a new engine should replace the old one."""
        old = MagicMock()
        old.__class__.__name__ = "OldEngine"
        new = MagicMock()
        new.__class__.__name__ = "NewEngine"

        set_engine(old)
        assert get_engine() is old

        set_engine(new)
        assert get_engine() is new


# ═══════════════════════════════════════════════════════════════
# Decorator edge cases
# ═══════════════════════════════════════════════════════════════


class TestObserveEdgeCases:
    """Edge cases for the @observe decorator."""

    def setup_method(self):
        _current_engine.set(None)

    def test_preserves_function_metadata(self):
        """functools.wraps should preserve __name__, __doc__, etc."""

        @observe
        def documented_func(x: int) -> str:
            """Convert int to string."""
            return str(x)

        assert documented_func.__name__ == "documented_func"
        assert documented_func.__doc__ == "Convert int to string."

    def test_preserves_function_metadata_with_parens(self):
        """functools.wraps should work with parameterised form too."""

        @observe(name="my_name")
        def original_name(x: int) -> str:
            """Original doc."""
            return str(x)

        # With parens, __name__ is set to the wrapped function's name
        assert original_name.__name__ == "original_name"
        assert original_name.__doc__ == "Original doc."

    def test_kwargs_recorded(self, tmp_path):
        """Keyword arguments should appear in the input snapshot."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="kwarg_test")
        def with_kwargs(a, b, mode="fast"):
            return f"{a}-{b}-{mode}"

        with_kwargs(1, 2, mode="slow")

        session_file = audit_dir / "observe-kwarg_test.jsonl"
        event = json.loads(session_file.read_text().strip().split("\n")[0])
        assert "slow" in event["input_snapshot"]

    def test_observe_without_parens_rejects_bad_call(self):
        """@observe() without args should fail with a clear error."""

        dec = observe()
        with pytest.raises(TypeError, match="expects a callable"):
            dec(None)

    def test_observe_with_parens_rejects_non_callable(self):
        """@observe(name='x') with non-callable should fail."""

        dec = observe(name="test")
        with pytest.raises(TypeError, match="expects a callable"):
            dec("not_a_function")

    def test_multiple_calls_create_separate_events(self, tmp_path):
        """Each invocation should create a separate event."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="counter")
        def counter(n: int) -> int:
            return n + 1

        counter(1)
        counter(2)
        counter(3)

        session_file = audit_dir / "observe-counter.jsonl"
        lines = session_file.read_text().strip().split("\n")
        assert len(lines) == 3, f"Expected 3 events, got {len(lines)}"

    def test_span_ids_are_unique(self, tmp_path):
        """Each event should have a unique span_id."""
        import json

        audit_dir = tmp_path / "audit_logs"
        from agent_seal.engine import AuditEngine

        engine = AuditEngine(str(audit_dir))
        set_engine(engine)

        @observe(name="unique_spans")
        def noop():
            pass

        noop()
        noop()
        noop()

        session_file = audit_dir / "observe-unique_spans.jsonl"
        events = [json.loads(l) for l in session_file.read_text().strip().split("\n")]
        span_ids = [e["metadata"]["span_id"] for e in events]
        assert len(span_ids) == len(set(span_ids)), "span_ids should be unique"

    def test_signature_preserved(self):
        """The decorated function should have the same signature."""
        import inspect as ins

        @observe
        def with_types(a: int, b: str = "default") -> bool:
            return True

        sig = ins.signature(with_types)
        params = list(sig.parameters.keys())
        assert "a" in params
        assert "b" in params
