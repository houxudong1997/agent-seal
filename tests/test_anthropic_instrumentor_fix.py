"""Tests for Anthropic Instrumentor fix: independent install flags, _resolve_tracer, imports.

Validates three aspects of the tracing fix (t_a8fe3d70):

  1. auto.py ``_OPENAI_INSTALLED`` / ``_ANTHROPIC_INSTALLED`` flags — independent per-provider guards
  2. ``_resolve_tracer`` in anthropic.py — shared tracer-resolution function
  3. ``anthropic.py`` ↔ ``openai_instrumentor.py`` import contract
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# ═══════════════════════════════════════════════════════════════════
# 1. auto.py — independent install flags per provider
# ═══════════════════════════════════════════════════════════════════


class TestInstalledGuard:
    """_OPENAI_INSTALLED / _ANTHROPIC_INSTALLED flags correctly prevent duplicate installation."""

    def test_first_call_returns_true_and_sets_flag(self):
        """install_auto_tracing returns True and sets _OPENAI_INSTALLED on first call."""
        import agent_seal.tracing.auto as auto_mod

        saved = auto_mod._OPENAI_INSTALLED
        auto_mod._OPENAI_INSTALLED = False
        try:
            with patch("agent_seal.tracing.openai_instrumentor.OpenAIInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr_cls.return_value = mock_instr

                result = auto_mod.install_auto_tracing()

                assert result is True
                assert auto_mod._OPENAI_INSTALLED is True
                mock_instr.install.assert_called_once()
        finally:
            auto_mod._OPENAI_INSTALLED = saved

    def test_second_call_skips_reinstall(self):
        """When _OPENAI_INSTALLED is True, install_auto_tracing returns True without re-installing."""
        import agent_seal.tracing.auto as auto_mod

        saved = auto_mod._OPENAI_INSTALLED
        auto_mod._OPENAI_INSTALLED = True
        try:
            with patch("agent_seal.tracing.openai_instrumentor.OpenAIInstrumentor") as mock_instr_cls:
                result = auto_mod.install_auto_tracing()

                assert result is True
                mock_instr_cls.assert_not_called()
        finally:
            auto_mod._OPENAI_INSTALLED = saved

    def test_second_call_preserves_first_original(self):
        """install_auto_tracing called twice does not re-create the instrumentor."""
        import agent_seal.tracing.auto as auto_mod

        saved = auto_mod._OPENAI_INSTALLED
        auto_mod._OPENAI_INSTALLED = False
        try:
            with patch("agent_seal.tracing.openai_instrumentor.OpenAIInstrumentor") as mock_instr_cls:
                mock_instr_cls.return_value = MagicMock()

                result1 = auto_mod.install_auto_tracing()
                assert result1 is True
                assert mock_instr_cls.call_count == 1

                result2 = auto_mod.install_auto_tracing()
                assert result2 is True
                # Second call should NOT create a new instrumentor
                assert mock_instr_cls.call_count == 1
        finally:
            auto_mod._OPENAI_INSTALLED = saved

    def test_error_during_install_does_not_set_flag(self):
        """When install() raises, _OPENAI_INSTALLED stays False."""
        import agent_seal.tracing.auto as auto_mod

        saved = auto_mod._OPENAI_INSTALLED
        auto_mod._OPENAI_INSTALLED = False
        try:
            with patch("agent_seal.tracing.openai_instrumentor.OpenAIInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr.install.side_effect = RuntimeError("install failed")
                mock_instr_cls.return_value = mock_instr

                result = auto_mod.install_auto_tracing()

                assert result is False
                assert auto_mod._OPENAI_INSTALLED is False
        finally:
            auto_mod._OPENAI_INSTALLED = saved

    def test_anthropic_install_uses_independent_flag(self):
        """install_auto_anthropic_tracing uses _ANTHROPIC_INSTALLED independently of OpenAI flag."""
        import agent_seal.tracing.auto as auto_mod

        saved_anthro = auto_mod._ANTHROPIC_INSTALLED
        saved_openai = auto_mod._OPENAI_INSTALLED
        auto_mod._ANTHROPIC_INSTALLED = False
        auto_mod._OPENAI_INSTALLED = True  # OpenAI already installed
        try:
            with patch("agent_seal.tracing.anthropic.AnthropicInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr_cls.return_value = mock_instr

                # Even though OpenAI is installed, Anthropic should still install
                result1 = auto_mod.install_auto_anthropic_tracing()
                assert result1 is True
                assert auto_mod._ANTHROPIC_INSTALLED is True
                assert auto_mod._OPENAI_INSTALLED is True  # Unchanged
                assert mock_instr_cls.call_count == 1
                mock_instr.install.assert_called_once()

                # Second Anthropic call — should skip (own flag is True)
                result2 = auto_mod.install_auto_anthropic_tracing()
                assert result2 is True
                assert mock_instr_cls.call_count == 1  # No new instrumentor
        finally:
            auto_mod._ANTHROPIC_INSTALLED = saved_anthro
            auto_mod._OPENAI_INSTALLED = saved_openai

# ═══════════════════════════════════════════════════════════════════
# 2. _resolve_tracer (anthropic.py)
# ═══════════════════════════════════════════════════════════════════


class TestResolveTracerAnthropic:
    """_resolve_tracer in anthropic.py resolves tracer correctly."""

    def test_returns_provided_tracer(self):
        """_resolve_tracer returns the tracer when one is provided."""
        from agent_seal.tracing.anthropic import _resolve_tracer

        mock_tracer = MagicMock()
        result = _resolve_tracer(mock_tracer)
        assert result is mock_tracer

    def test_returns_none_when_opentelemetry_not_installed(self):
        """_resolve_tracer returns None when opentelemetry is not installed."""
        import builtins

        from agent_seal.tracing.anthropic import _resolve_tracer

        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == "opentelemetry":
                raise ImportError("no opentelemetry")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", failing_import):
            result = _resolve_tracer(None)
            assert result is None

    def test_returns_otel_tracer_when_installed(self):
        """_resolve_tracer returns an OTel tracer when opentelemetry is available."""
        from agent_seal.tracing.anthropic import _resolve_tracer

        mock_otel = MagicMock()
        mock_tracer_api = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer_api.get_tracer.return_value = mock_tracer
        mock_otel.trace = mock_tracer_api

        with patch.dict(sys.modules, {"opentelemetry": mock_otel}):
            result = _resolve_tracer(None)
            assert result is mock_tracer
            mock_tracer_api.get_tracer.assert_called_once_with("agent-seal")

    def test_logs_warning_when_missing(self):
        """_resolve_tracer logs a debug message when opentelemetry is absent."""
        from agent_seal.tracing.anthropic import _resolve_tracer, logger

        with patch.object(logger, "debug") as mock_debug, \
                patch.dict(sys.modules, {"opentelemetry": None}):
            # Trigger the import fail path
                # We need to make the import actually fail
                import builtins

                original_import = builtins.__import__

                def failing_import(name, *args, **kwargs):
                    if name == "opentelemetry":
                        raise ImportError("no opentelemetry")
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", failing_import):
                    result = _resolve_tracer(None)
                    assert result is None
                    mock_debug.assert_called_once_with(
                        "opentelemetry not installed — spans disabled"
                    )


# ═══════════════════════════════════════════════════════════════════
# 3. Import correctness — anthropic.py → openai_instrumentor.py
# ═══════════════════════════════════════════════════════════════════


class TestImportContract:
    """anthropic.py imports correctly from openai_instrumentor.py."""

    def test_anthropic_imports_persist_llm_call(self):
        """anthropic.py imports _persist_llm_call from openai_instrumentor."""
        from agent_seal.tracing.anthropic import _persist_llm_call
        from agent_seal.tracing.openai_instrumentor import _persist_llm_call as _openai_persist

        # Same function — not a copy
        assert _persist_llm_call is _openai_persist

    def test_anthropic_imports_redact_messages(self):
        """anthropic.py imports _redact_messages from openai_instrumentor."""
        from agent_seal.tracing.anthropic import _redact_messages
        from agent_seal.tracing.openai_instrumentor import _redact_messages as _openai_redact

        # Same function — not a copy
        assert _redact_messages is _openai_redact

    def test_init_exports_both_instrumentors(self):
        """__init__.py correctly exports AnthropicInstrumentor and OpenAIInstrumentor."""
        from agent_seal.tracing import AnthropicInstrumentor, OpenAIInstrumentor
        from agent_seal.tracing.anthropic import AnthropicInstrumentor as _Anthropic
        from agent_seal.tracing.openai_instrumentor import OpenAIInstrumentor as _OpenAI

        assert AnthropicInstrumentor is _Anthropic
        assert OpenAIInstrumentor is _OpenAI

    def test_init_exports_install_auto_tracing(self):
        """__init__.py correctly exports install_auto_tracing."""
        from agent_seal.tracing import install_auto_tracing
        from agent_seal.tracing.auto import install_auto_tracing as _auto_install

        assert install_auto_tracing is _auto_install

    def test_init_does_not_export_install_auto_anthropic_tracing(self):
        """__init__.py does NOT export install_auto_anthropic_tracing (only available via auto module)."""
        import agent_seal.tracing as tracing_mod

        assert not hasattr(tracing_mod, "install_auto_anthropic_tracing")


# ═══════════════════════════════════════════════════════════════════
# 4. _resolve_tracer — identity consistency (same logic in both modules)
# ═══════════════════════════════════════════════════════════════════


class TestResolveTracerConsistency:
    """Both modules have the same _resolve_tracer signature and behaviour."""

    def test_both_return_provided_tracer(self):
        """Both _resolve_tracer implementations return the provided tracer."""
        from agent_seal.tracing.anthropic import _resolve_tracer as anthro_resolve
        from agent_seal.tracing.openai_instrumentor import _resolve_tracer as openai_resolve

        mock_tracer = MagicMock()
        assert anthro_resolve(mock_tracer) is mock_tracer
        assert openai_resolve(mock_tracer) is mock_tracer

    def test_both_default_to_none_when_otel_missing(self):
        """Both return None when opentelemetry is unavailable."""
        import builtins

        from agent_seal.tracing.anthropic import _resolve_tracer as anthro_resolve
        from agent_seal.tracing.openai_instrumentor import _resolve_tracer as openai_resolve

        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == "opentelemetry":
                raise ImportError("no opentelemetry")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", failing_import):
            assert anthro_resolve(None) is None
            assert openai_resolve(None) is None


# ═══════════════════════════════════════════════════════════════════
# 5. auto.py — resume_auto_tracing (module-level activation)
# ═══════════════════════════════════════════════════════════════════


class TestModuleLevelActivation:
    """Module-level auto-activation via env var."""

    def test_auto_enabled_triggers_both_installs(self):
        """When AGENT_SEAL_AUTO_TRACE=1, _auto_enabled returns True."""
        from agent_seal.tracing.auto import _auto_enabled

        for val in ("1", "true", "yes", "on"):
            with patch.dict("os.environ", {"AGENT_SEAL_AUTO_TRACE": val}):
                assert _auto_enabled() is True

    def test_install_auto_anthropic_tracing_passes_config(self):
        """install_auto_anthropic_tracing creates TraceConfig from app config."""
        import agent_seal.tracing.auto as auto_mod

        saved = auto_mod._ANTHROPIC_INSTALLED
        auto_mod._ANTHROPIC_INSTALLED = False
        try:
            with patch("agent_seal.tracing.anthropic.AnthropicInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr_cls.return_value = mock_instr

                result = auto_mod.install_auto_anthropic_tracing()

                assert result is True
                mock_instr.install.assert_called_once()
                call_config = mock_instr_cls.call_args.kwargs.get("config")
                assert call_config is not None
                assert call_config.auto_cost is True
        finally:
            auto_mod._ANTHROPIC_INSTALLED = saved

    def test_install_auto_anthropic_tracing_passes_engine(self):
        """install_auto_anthropic_tracing passes engine to AnthropicInstrumentor."""
        import agent_seal.tracing.auto as auto_mod

        saved = auto_mod._ANTHROPIC_INSTALLED
        auto_mod._ANTHROPIC_INSTALLED = False
        try:
            with patch("agent_seal.tracing.anthropic.AnthropicInstrumentor") as mock_instr_cls:
                mock_instr = MagicMock()
                mock_instr_cls.return_value = mock_instr

                engine = MagicMock()
                result = auto_mod.install_auto_anthropic_tracing(engine=engine)

                assert result is True
                assert mock_instr_cls.call_args.kwargs.get("engine") is engine
        finally:
            auto_mod._ANTHROPIC_INSTALLED = saved


# ═══════════════════════════════════════════════════════════════════
# 6. _extract_content_text — utility function in anthropic.py
# ═══════════════════════════════════════════════════════════════════


class TestExtractContentText:
    """_extract_content_text handles various Anthropic content formats."""

    def test_extracts_text_from_block_with_text_attr(self):
        """Extracts text from a ContentBlock-like object with .text attribute."""
        from agent_seal.tracing.anthropic import _extract_content_text

        class FakeTextBlock:
            text = "Hello Claude"

        result = _extract_content_text([FakeTextBlock()])
        assert result == "Hello Claude"

    def test_returns_empty_string_for_none(self):
        """Returns empty string when content is None."""
        from agent_seal.tracing.anthropic import _extract_content_text

        assert _extract_content_text(None) == ""

    def test_returns_string_directly(self):
        """Returns the string as-is when content is already a string."""
        from agent_seal.tracing.anthropic import _extract_content_text

        assert _extract_content_text("plain string") == "plain string"

    def test_extracts_text_from_dict_block(self):
        """Extracts text from a dict content block."""
        from agent_seal.tracing.anthropic import _extract_content_text

        result = _extract_content_text([{"type": "text", "text": "Dict block"}])
        assert result == "Dict block"

    def test_extracts_text_from_dict_block_missing_text_key(self):
        """Returns empty string when dict block has no 'text' key."""
        from agent_seal.tracing.anthropic import _extract_content_text

        result = _extract_content_text([{"type": "tool_use", "name": "get_weather"}])
        assert result == ""

    def test_returns_empty_string_for_empty_list(self):
        """Returns empty string for empty content list."""
        from agent_seal.tracing.anthropic import _extract_content_text

        assert _extract_content_text([]) == ""

    def test_handles_non_list_non_string_type(self):
        """Returns empty string for unexpected types (e.g., int, dict without list)."""
        from agent_seal.tracing.anthropic import _extract_content_text

        assert _extract_content_text(42) == ""

    def test_text_block_with_none_text(self):
        """When .text is None, returns empty string."""
        from agent_seal.tracing.anthropic import _extract_content_text

        class FakeBlock:
            text = None

        result = _extract_content_text([FakeBlock()])
        assert result == ""
