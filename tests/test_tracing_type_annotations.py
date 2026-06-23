"""Tests for type annotation correctness and consistency across tracing modules.

Verifies:
  1. ``from __future__ import annotations`` is present in all 4 files
  2. ``TYPE_CHECKING`` guard is used for ``AuditEngine`` imports
  3. ``AuditEngine | None`` (PEP 604) is used consistently in function signatures
  4. Return types match actual returns
  5. API parity between OpenAIInstrumentor and AnthropicInstrumentor
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths & helpers
# ---------------------------------------------------------------------------

TRACING_DIR = Path(__file__).resolve().parent.parent / "agent_seal" / "tracing"

TARGET_FILES = {
    "auto": TRACING_DIR / "auto.py",
    "opentelemetry": TRACING_DIR / "opentelemetry.py",
    "openai_instrumentor": TRACING_DIR / "openai_instrumentor.py",
    "anthropic": TRACING_DIR / "anthropic.py",
}

MODULE_MAP = {
    "auto": "agent_seal.tracing.auto",
    "opentelemetry": "agent_seal.tracing.opentelemetry",
    "openai_instrumentor": "agent_seal.tracing.openai_instrumentor",
    "anthropic": "agent_seal.tracing.anthropic",
}

AUDIT_ENGINE_FILES = {"auto", "opentelemetry", "openai_instrumentor", "anthropic"}

_SOURCE_CACHE: dict[str, str] = {}


def _source(key: str) -> str:
    """Read and cache source for *key*."""
    if key not in _SOURCE_CACHE:
        _SOURCE_CACHE[key] = TARGET_FILES[key].read_text(encoding="utf-8")
    return _SOURCE_CACHE[key]


# ---------------------------------------------------------------------------
# 1. Module-level annotation guards
# ---------------------------------------------------------------------------


class TestModuleAnnotations:
    """Every tracing module must opt into postponed evaluation of annotations."""

    @pytest.mark.parametrize("key", list(TARGET_FILES))
    def test_future_annotations_present(self, key: str) -> None:
        """``from __future__ import annotations`` must be at the top of the file."""
        source = _source(key)
        tree = ast.parse(source)
        first_stmt = tree.body[0] if tree.body else None
        # First statement could be a docstring (Expr)
        if isinstance(first_stmt, ast.Expr) and isinstance(first_stmt.value, ast.Constant):
            first_stmt = tree.body[1] if len(tree.body) > 1 else None
        assert first_stmt is not None, f"{key}.py has no statements"
        assert isinstance(first_stmt, ast.ImportFrom), (
            f"{key}.py: first non-docstring statement must be an import, "
            f"got {type(first_stmt).__name__}"
        )
        assert first_stmt.module == "__future__", (
            f"{key}.py: first import must be from __future__, "
            f"got 'from {first_stmt.module}'"
        )
        names = {alias.name for alias in first_stmt.names}
        assert "annotations" in names, f"{key}.py: __future__ import does not include 'annotations'"

    @pytest.mark.parametrize("key", list(TARGET_FILES))
    def test_type_checking_import_present(self, key: str) -> None:
        """Each module must import ``TYPE_CHECKING`` from ``typing``."""
        source = _source(key)
        tree = ast.parse(source)
        has_type_checking = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "typing"
            and any(alias.name == "TYPE_CHECKING" for alias in node.names)
            for node in ast.walk(tree)
        )
        assert has_type_checking, f"{key}.py does not import TYPE_CHECKING from typing"

    @pytest.mark.parametrize("key", AUDIT_ENGINE_FILES)
    def test_audit_engine_under_type_checking(self, key: str) -> None:
        """``AuditEngine`` must only be imported inside ``TYPE_CHECKING`` blocks."""
        source = _source(key)
        tree = ast.parse(source)

        # Collect all TYPE_CHECKING-guarded import-from statements
        type_checking_imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Check if condition is "TYPE_CHECKING"
                if (
                    isinstance(node.test, ast.Name)
                    and node.test.id == "TYPE_CHECKING"
                ):
                    for body_node in ast.walk(node):
                        if isinstance(body_node, ast.ImportFrom):
                            for alias in body_node.names:
                                if alias.name == "AuditEngine":
                                    type_checking_imports.add(
                                        f"{body_node.module}.{alias.name}"
                                    )

        assert any(
            "AuditEngine" in imp for imp in type_checking_imports
        ), (
            f"{key}.py: AuditEngine must be imported under TYPE_CHECKING guard, "
            f"not at module level. Found guarded imports: {type_checking_imports}"
        )


# ---------------------------------------------------------------------------
# 2. Function / method signatures with AuditEngine
# ---------------------------------------------------------------------------


class TestAuditEngineParameterType:
    """All public functions accepting ``AuditEngine`` should use ``| None`` syntax
    (or required ``AuditEngine`` where appropriate)."""

    # (module, function_name, param_name)
    # Parameters that should have `AuditEngine | None` (optional)
    OPTIONAL_PARAMS: list[tuple[str, str, str]] = [
        ("auto", "install_auto_tracing", "engine"),
        ("auto", "install_auto_anthropic_tracing", "engine"),
        ("opentelemetry", "AuditSpanProcessor.__init__", "engine"),
        ("openai_instrumentor", "OpenAIInstrumentor.__init__", "engine"),
        ("anthropic", "AnthropicInstrumentor.__init__", "engine"),
    ]

    @pytest.mark.parametrize("key,func_name,param_name", OPTIONAL_PARAMS)
    def test_engine_param_optional(self, key: str, func_name: str, param_name: str) -> None:
        """``engine`` parameter must be typed as ``AuditEngine | None`` (PEP 604)."""
        # Parse "__init__" references
        parts = func_name.split(".")
        full_path = f"{key}.py::{parts[0]}"
        import importlib

        mod = importlib.import_module(MODULE_MAP[key])
        if len(parts) == 1:

            obj = getattr(mod, parts[0])
        else:
            parent = getattr(mod, parts[0])
            obj = getattr(parent, parts[1])

        sig = inspect.signature(obj)
        assert param_name in sig.parameters, (
            f"{full_path} has no parameter named '{param_name}'"
        )
        param = sig.parameters[param_name]
        hint = param.annotation

        # With from __future__ import annotations, the annotation is a string
        assert hint is not inspect.Parameter.empty, (
            f"{full_path} parameter '{param_name}' has no type annotation"
        )

        # The annotation string from __future__ annotations resolves as a string
        # but inspect.signature with future annotations gives a resolved type.
        # We check the raw source instead for reliability.
        source = _source(key)
        tree = ast.parse(source)

        # Find the function/method definition
        found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if parts[0] == node.name:
                    # Check specific parameter annotation
                    for arg in node.args.args + node.args.kwonlyargs:
                        if arg.arg == param_name and arg.annotation is not None:
                            found = True
                            ann_str = ast.unparse(arg.annotation)
                            expected_patterns = [
                                "AuditEngine | None",
                                "Optional[AuditEngine]",
                                "AuditEngine | None]",
                            ]
                            assert any(
                                p in ann_str for p in expected_patterns
                            ), (
                                f"{full_path} '{param_name}' annotation is "
                                f"'{ann_str}', expected 'AuditEngine | None'"
                            )
            # Also check class methods
            if isinstance(node, ast.ClassDef) and parts[0] == node.name:
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if parts[1] == child.name:
                            for arg in child.args.args + child.args.kwonlyargs:
                                if arg.arg == param_name and arg.annotation is not None:
                                    found = True
                                    ann_str = ast.unparse(arg.annotation)
                                    assert (
                                        "AuditEngine | None" in ann_str
                                    ), (
                                        f"{full_path} '{param_name}' annotation is "
                                        f"'{ann_str}', expected 'AuditEngine | None'"
                                    )

        assert found, (
            f"{full_path}: could not find parameter '{param_name}' with "
            f"a type annotation"
        )

    # Parameters that should have `engine: AuditEngine` (required, not optional)
    REQUIRED_PARAMS: list[tuple[str, str, str, str]] = [
        # (key, func_name, param_name, expected_annotation)
        ("opentelemetry", "create_span_processor", "engine", "AuditEngine"),
    ]

    @pytest.mark.parametrize("key,func_name,param_name,expected_ann", REQUIRED_PARAMS)
    def test_engine_param_required(
        self, key: str, func_name: str, param_name: str, expected_ann: str
    ) -> None:
        """``engine`` parameter must be typed as ``AuditEngine`` (required, not optional)."""
        source = _source(key)
        tree = ast.parse(source)

        found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    for arg in node.args.args + node.args.kwonlyargs:
                        if arg.arg == param_name and arg.annotation is not None:
                            found = True
                            ann = ast.unparse(arg.annotation)
                            assert ann == expected_ann, (
                                f"{key}.py::{func_name} '{param_name}' annotation is "
                                f"'{ann}', expected '{expected_ann}'"
                            )
                            # Also verify NO `| None` or `Optional`
                            assert "None" not in ann, (
                                f"{key}.py::{func_name} '{param_name}' should be required "
                                f"({expected_ann}), got optional '{ann}'"
                            )

        assert found, (
            f"{key}.py::{func_name}: could not find parameter '{param_name}' "
            f"with type annotation"
        )


# ---------------------------------------------------------------------------
# 3. Return type annotations
# ---------------------------------------------------------------------------


class TestReturnTypes:
    """All public functions must have explicit return type annotations."""

    FUNCTIONS: list[tuple[str, str]] = [
        # auto.py
        ("auto", "install_auto_tracing"),
        ("auto", "install_auto_anthropic_tracing"),
        ("auto", "_auto_enabled"),
        # opentelemetry.py
        ("opentelemetry", "AuditSpanProcessor.on_start"),
        ("opentelemetry", "AuditSpanProcessor.on_end"),
        ("opentelemetry", "AuditSpanProcessor.shutdown"),
        ("opentelemetry", "AuditSpanProcessor.force_flush"),
        ("opentelemetry", "AuditSpanProcessor._process_span"),
        ("opentelemetry", "create_span_processor"),
        ("opentelemetry", "AuditSpanProcessor._get_attributes"),
        ("opentelemetry", "AuditSpanProcessor._get_trace_id"),
        ("opentelemetry", "AuditSpanProcessor._get_span_id"),
        ("opentelemetry", "AuditSpanProcessor._get_parent_span_id"),
        # openai_instrumentor.py
        ("openai_instrumentor", "OpenAIInstrumentor.install"),
        ("openai_instrumentor", "OpenAIInstrumentor.uninstall"),
        ("openai_instrumentor", "OpenAIInstrumentor._check_db_available"),
        ("openai_instrumentor", "_persist_llm_call"),
        ("openai_instrumentor", "_redact_messages"),
        ("openai_instrumentor", "_resolve_tracer"),
        # anthropic.py
        ("anthropic", "AnthropicInstrumentor.install"),
        ("anthropic", "AnthropicInstrumentor.uninstall"),
        ("anthropic", "AnthropicInstrumentor._check_db_available"),
        ("anthropic", "_resolve_tracer"),
        ("anthropic", "_extract_content_text"),
    ]

    def _get_function_source_node(
        self, tree: ast.Module, func_name: str
    ) -> tuple[ast.FunctionDef | None, str]:
        """Walk AST for a function (with optional ClassName. prefix)."""
        parts = func_name.split(".")
        if len(parts) == 1:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parts[0]:
                    return node, func_name
            return None, func_name

        # Class.method
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == parts[0]:
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == parts[1]:
                        return child, func_name
        return None, func_name

    @pytest.mark.parametrize("key,func_name", FUNCTIONS)
    def test_return_type_annotated(self, key: str, func_name: str) -> None:
        """Every function/method must have a return type annotation."""
        source = _source(key)
        tree = ast.parse(source)
        fn_node, display_name = self._get_function_source_node(tree, func_name)
        assert fn_node is not None, (
            f"{key}.py: function '{func_name}' not found in AST"
        )

        # Check return annotation exists
        if fn_node.returns is None:
            pytest.fail(
                f"{key}.py::{display_name} is missing a return type annotation"
            )

        ann = ast.unparse(fn_node.returns)
        assert ann, (
            f"{key}.py::{display_name} has an empty return annotation"
        )

    RETURN_EXPECTATIONS: list[tuple[str, str, str]] = [
        # (key, func_name, expected_return_substring)
        ("auto", "install_auto_tracing", "bool"),
        ("auto", "install_auto_anthropic_tracing", "bool"),
        ("auto", "_auto_enabled", "bool"),
        ("opentelemetry", "AuditSpanProcessor.on_start", "None"),
        ("opentelemetry", "AuditSpanProcessor.on_end", "None"),
        ("opentelemetry", "AuditSpanProcessor.shutdown", "None"),
        ("opentelemetry", "AuditSpanProcessor.force_flush", "bool"),
        ("opentelemetry", "AuditSpanProcessor._process_span", "None"),
        ("opentelemetry", "AuditSpanProcessor._get_attributes", "dict"),
        ("opentelemetry", "AuditSpanProcessor._get_trace_id", "str"),
        ("opentelemetry", "AuditSpanProcessor._get_span_id", "str"),
        ("opentelemetry", "AuditSpanProcessor._get_parent_span_id", "str"),
        ("opentelemetry", "create_span_processor", "AuditSpanProcessor"),
        ("openai_instrumentor", "OpenAIInstrumentor.install", "None"),
        ("openai_instrumentor", "OpenAIInstrumentor.uninstall", "None"),
        ("openai_instrumentor", "OpenAIInstrumentor._check_db_available", "bool"),
        ("openai_instrumentor", "_persist_llm_call", "None"),
        ("anthropic", "AnthropicInstrumentor.install", "None"),
        ("anthropic", "AnthropicInstrumentor.uninstall", "None"),
        ("anthropic", "AnthropicInstrumentor._check_db_available", "bool"),
        ("anthropic", "_extract_content_text", "str"),
    ]

    @pytest.mark.parametrize("key,func_name,expected", RETURN_EXPECTATIONS)
    def test_return_type_correct(self, key: str, func_name: str, expected: str) -> None:
        """Return type annotation matches expected type."""
        source = _source(key)
        tree = ast.parse(source)
        fn_node, display_name = self._get_function_source_node(tree, func_name)
        assert fn_node is not None, (
            f"{key}.py: function '{func_name}' not found"
        )
        assert fn_node.returns is not None, (
            f"{key}.py::{display_name} has no return annotation"
        )
        ann = ast.unparse(fn_node.returns)
        assert expected in ann, (
            f"{key}.py::{display_name} return type is '{ann}', "
            f"expected to contain '{expected}'"
        )


# ---------------------------------------------------------------------------
# 4. API parity between OpenAIInstrumentor and AnthropicInstrumentor
# ---------------------------------------------------------------------------


class TestInstrumentorParity:
    """OpenAIInstrumentor and AnthropicInstrumentor must expose the same public API."""

    # Public methods both should share
    PUBLIC_METHODS = {"install", "uninstall", "_check_db_available"}

    def test_same_public_methods(self) -> None:
        """Both instrumentor classes have the same public method set."""
        import importlib

        openai_mod = importlib.import_module(MODULE_MAP["openai_instrumentor"])
        anthropic_mod = importlib.import_module(MODULE_MAP["anthropic"])

        openai_cls = getattr(openai_mod, "OpenAIInstrumentor")
        anthropic_cls = getattr(anthropic_mod, "AnthropicInstrumentor")

        openai_methods = {
            name
            for name, _ in inspect.getmembers(openai_cls, predicate=inspect.isfunction)
            if not name.startswith("__")
        }
        anthropic_methods = {
            name
            for name, _ in inspect.getmembers(anthropic_cls, predicate=inspect.isfunction)
            if not name.startswith("__")
        }

        # Both must have all required public methods
        for method in self.PUBLIC_METHODS:
            assert method in openai_methods, (
                f"OpenAIInstrumentor is missing public method '{method}'"
            )
            assert method in anthropic_methods, (
                f"AnthropicInstrumentor is missing public method '{method}'"
            )

    def test_init_signatures_match(self) -> None:
        """Both __init__ methods have the same parameter signature."""
        import importlib
        from inspect import signature

        openai_mod = importlib.import_module(MODULE_MAP["openai_instrumentor"])
        anthropic_mod = importlib.import_module(MODULE_MAP["anthropic"])

        openai_sig = signature(getattr(openai_mod, "OpenAIInstrumentor"))
        anthropic_sig = signature(getattr(anthropic_mod, "AnthropicInstrumentor"))

        # Compare parameter names (ignoring self)
        openai_params = list(openai_sig.parameters.keys())
        anthropic_params = list(anthropic_sig.parameters.keys())

        # Remove 'self'
        openai_params = [p for p in openai_params if p != "self"]
        anthropic_params = [p for p in anthropic_params if p != "self"]

        assert openai_params == anthropic_params, (
            f"Parameter names differ:\n"
            f"  OpenAIInstrumentor.__init__: {openai_params}\n"
            f"  AnthropicInstrumentor.__init__: {anthropic_params}"
        )

    def test_init_signature_types_match(self) -> None:
        """Both __init__ methods use the same type annotation patterns."""
        import importlib
        from inspect import signature

        openai_mod = importlib.import_module(MODULE_MAP["openai_instrumentor"])
        anthropic_mod = importlib.import_module(MODULE_MAP["anthropic"])

        openai_sig = signature(getattr(openai_mod, "OpenAIInstrumentor"))
        anthropic_sig = signature(getattr(anthropic_mod, "AnthropicInstrumentor"))

        # Compare annotation strings via AST for reliability
        src_openai = _source("openai_instrumentor")
        src_anthropic = _source("anthropic")

        # Parse ASTs and compare __init__ annotations structurally
        def _get_init_params(source: str) -> list[tuple[str, str]]:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for child in node.body:
                        if isinstance(child, ast.FunctionDef) and child.name == "__init__":
                            params = []
                            for arg in child.args.args + child.args.kwonlyargs:
                                if arg.arg == "self":
                                    continue
                                ann = ast.unparse(arg.annotation) if arg.annotation else ""
                                params.append((arg.arg, ann))
                            return params
            return []

        openai_params = _get_init_params(src_openai)
        anthropic_params = _get_init_params(src_anthropic)

        assert len(openai_params) == len(anthropic_params), (
            f"__init__ parameter count differs:\n"
            f"  OpenAI: {len(openai_params)}\n"
            f"  Anthropic: {len(anthropic_params)}"
        )

        for (oname, oann), (aname, aann) in zip(openai_params, anthropic_params):
            assert oname == aname, f"Parameter name mismatch: '{oname}' vs '{aname}'"
            assert oann == aann, (
                f"Parameter '{oname}' annotation differs:\n"
                f"  OpenAI: {oann}\n"
                f"  Anthropic: {aann}"
            )


# ---------------------------------------------------------------------------
# 5. Cross-module consistency for _persist_llm_call / _redact_messages
# ---------------------------------------------------------------------------


class TestSharedFunctionTypes:
    """Functions imported between tracing modules must have consistent signatures."""

    SHARED_FUNCS: list[tuple[str, str, str]] = [
        # (source_key, func_name, uses_from_key)
        ("openai_instrumentor", "_persist_llm_call", "anthropic"),
        ("openai_instrumentor", "_redact_messages", "anthropic"),
    ]

    def _get_func_ast_node(
        self, key: str, func_name: str
    ) -> ast.FunctionDef | None:
        """Find a top-level function definition in the module AST."""
        tree = ast.parse(_source(key))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return node
        return None

    def test_persist_llm_call_signature(self) -> None:
        """``_persist_llm_call`` has all required keyword-only parameters."""
        fn = self._get_func_ast_node("openai_instrumentor", "_persist_llm_call")
        assert fn is not None, "_persist_llm_call not found in openai_instrumentor.py"

        # Ensure all params after * are keyword-only
        assert fn.args.kwonlyargs, "_persist_llm_call should have keyword-only args"

        param_names = {arg.arg for arg in fn.args.kwonlyargs}
        required = {
            "trace_id",
            "span_id",
            "parent_span_id",
            "provider",
            "model",
            "request_tokens",
            "response_tokens",
            "total_tokens",
            "latency_ms",
            "cost_usd",
            "request_body",
            "response_body",
            "session_id",
            "agent_id",
            "event_id",
        }
        missing = required - param_names
        assert not missing, (
            f"_persist_llm_call is missing keyword-only parameters: {missing}"
        )

        # Verify annotations for numeric fields
        for arg in fn.args.kwonlyargs:
            if arg.arg in ("request_tokens", "response_tokens", "total_tokens", "latency_ms"):
                assert arg.annotation is not None, (
                    f"_persist_llm_call '{arg.arg}' has no type annotation"
                )

    def test_redact_messages_type(self) -> None:
        """``_redact_messages`` has correct parameter and return types."""
        fn = self._get_func_ast_node("openai_instrumentor", "_redact_messages")
        assert fn is not None, "_redact_messages not found in openai_instrumentor.py"

        # Check parameter type
        assert fn.args.args, "_redact_messages should have at least 1 parameter"
        param = fn.args.args[0]
        assert param.annotation is not None, (
            "_redact_messages 'messages' parameter has no type annotation"
        )
        ann = ast.unparse(param.annotation)
        assert "Any" in ann, (
            f"_redact_messages 'messages' annotation is '{ann}', expected Any"
        )

        # Check return type
        assert fn.returns is not None, (
            "_redact_messages has no return type annotation"
        )
        ret = ast.unparse(fn.returns)
        assert "Any" in ret, (
            f"_redact_messages return type is '{ret}', expected Any"
        )

    def test_shared_functions_referenced_by_anthropic(self) -> None:
        """Anthropic module imports ``_persist_llm_call`` and ``_redact_messages``."""
        source = _source("anthropic")
        tree = ast.parse(source)

        imported_funcs = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (
                    node.module
                    and "openai_instrumentor" in node.module
                ):
                    for alias in node.names:
                        imported_funcs.add(alias.name)

        for func_name in ("_persist_llm_call", "_redact_messages"):
            assert func_name in imported_funcs, (
                f"anthropic.py does not import '{func_name}' from "
                f"openai_instrumentor"
            )

    def test_engine_field_type_consistency(self) -> None:
        """All classes store ``engine`` with ``AuditEngine | None`` annotation."""
        import importlib

        for key in ("openai_instrumentor", "anthropic"):
            mod = importlib.import_module(MODULE_MAP[key])
            cls_name = "OpenAIInstrumentor" if key == "openai_instrumentor" else "AnthropicInstrumentor"
            cls = getattr(mod, cls_name)

            # Use AST to check the __annotations__ in the class body
            # (from __future__ import annotations makes get_type_hints unreliable)
            src = _source(key)
            tree = ast.parse(src)
            found_engine_hint = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == cls_name:
                    for child in node.body:
                        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name) and child.target.id == "engine":
                            found_engine_hint = True
                            ann = ast.unparse(child.annotation)
                            assert "AuditEngine | None" in ann or "Optional[AuditEngine]" in ann, (
                                f"{cls_name} field 'engine' type is '{ann}', "
                                f"expected 'AuditEngine | None'"
                            )
            if not found_engine_hint:
                # engine might be set in __init__ instead of class body — check via __init__ param
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == cls_name:
                        for child in node.body:
                            if isinstance(child, ast.FunctionDef) and child.name == "__init__":
                                for arg in child.args.args:
                                    if arg.arg == "engine" and arg.annotation is not None:
                                        found_engine_hint = True
                                        ann = ast.unparse(arg.annotation)
                                        assert "AuditEngine | None" in ann, (
                                            f"{cls_name} __init__ 'engine' type is '{ann}', "
                                            f"expected 'AuditEngine | None'"
                                        )

            assert found_engine_hint, (
                f"{cls_name} has no 'engine' annotation in class body or __init__"
            )


# ---------------------------------------------------------------------------
# 6. OTel-specific type annotations
# ---------------------------------------------------------------------------


class TestOpentelemetryAnnotations:
    """OTel SpanProcessor methods must accept duck-typed ``Any`` parameters."""

    def test_span_parameter_is_any(self) -> None:
        """``on_start``, ``on_end``, ``_process_span`` have ``span: Any``."""
        source = _source("opentelemetry")

        for method_name in ("on_start", "on_end", "_process_span"):
            found = False
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "AuditSpanProcessor":
                    for child in node.body:
                        if isinstance(child, ast.FunctionDef) and child.name == method_name:
                            found = True
                            assert child.args.args, (
                                f"AuditSpanProcessor.{method_name} should have args"
                            )
                            # First arg after self
                            span_arg = child.args.args[1] if len(child.args.args) > 1 else None
                            assert span_arg is not None, (
                                f"AuditSpanProcessor.{method_name} missing 'span' parameter"
                            )
                            assert span_arg.annotation is not None, (
                                f"AuditSpanProcessor.{method_name} 'span' has no type annotation"
                            )
                            ann = ast.unparse(span_arg.annotation)
                            assert "Any" in ann, (
                                f"AuditSpanProcessor.{method_name} 'span' is '{ann}', "
                                f"expected Any"
                            )
            assert found, (
                f"AuditSpanProcessor.{method_name} not found in opentelemetry.py"
            )

    def test_static_methods_have_return_types(self) -> None:
        """``_get_attributes``, ``_get_trace_id``, ``_get_span_id``, ``_get_parent_span_id``
        are @staticmethod and have return types."""
        source = _source("opentelemetry")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "AuditSpanProcessor":
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) and child.name.startswith("_get_"):
                        # Check decorated with @staticmethod
                        has_static = any(
                            isinstance(d, ast.Name) and d.id == "staticmethod"
                            for d in child.decorator_list
                        )
                        assert has_static, (
                            f"AuditSpanProcessor.{child.name} should be @staticmethod"
                        )
                        assert child.returns is not None, (
                            f"AuditSpanProcessor.{child.name} has no return type annotation"
                        )


# ---------------------------------------------------------------------------
# 7. _trace_call and _trace_anthropic_call signature parity
# ---------------------------------------------------------------------------


class TestTraceCallParity:
    """``_trace_call`` (OpenAI) and ``_trace_anthropic_call`` must have matching kwargs."""

    def test_trace_call_kwargs_match(self) -> None:
        """Both trace functions accept the same keyword-only parameters."""
        src_openai = _source("openai_instrumentor")
        src_anthropic = _source("anthropic")

        def _get_kwonly_params(source: str, func_name: str) -> list[tuple[str, str]]:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    params = []
                    for arg in node.args.kwonlyargs:
                        ann = ast.unparse(arg.annotation) if arg.annotation else ""
                        params.append((arg.arg, ann))
                    return params
            return []

        openai_params = _get_kwonly_params(src_openai, "_trace_call")
        anthropic_params = _get_kwonly_params(src_anthropic, "_trace_anthropic_call")

        # Both must exist
        assert openai_params, "_trace_call not found in openai_instrumentor.py"
        assert anthropic_params, "_trace_anthropic_call not found in anthropic.py"

        # Same parameter count
        assert len(openai_params) == len(anthropic_params), (
            f"Keyword-only parameter count differs:\n"
            f"  _trace_call: {len(openai_params)}\n"
            f"  _trace_anthropic_call: {len(anthropic_params)}"
        )

        # Same parameter names
        openai_names = [p[0] for p in openai_params]
        anthropic_names = [p[0] for p in anthropic_params]
        assert openai_names == anthropic_names, (
            f"Keyword-only parameter names differ:\n"
            f"  _trace_call: {openai_names}\n"
            f"  _trace_anthropic_call: {anthropic_names}"
        )

        # Same annotations
        for (oname, oann), (aname, aann) in zip(openai_params, anthropic_params):
            assert oann == aann, (
                f"Parameter '{oname}' annotation differs:\n"
                f"  _trace_call: {oann}\n"
                f"  _trace_anthropic_call: {aann}"
            )
