"""
agent-audit hook — auto-installs httpx monkey-patch to capture LLM calls.

Place in Hermes worker's PYTHONPATH or use sitecustomize.
Captures all httpx.AsyncClient.request() calls to DeepSeek/Xiaomi APIs.
"""

import os
import json
import time
import functools

_HOOK_DB = os.environ.get(
    "AGENT_AUDIT_DB",
    "sqlite:///F:/workstation/projects/agent-audit/audit.db",
)
_HOOK_PROFILE = os.environ.get("HERMES_PROFILE") or os.environ.get("HERMES_AGENT_ID") or "unknown"

# Also try to detect from process command line / working directory
if _HOOK_PROFILE == "unknown":
    import sys as _sys
    for a in _sys.argv:
        for prof in ["workstation-gm", "workstation-business-dev", "workstation-test-dev", 
                     "workstation-reviewer", "workstation-planner", "workstation-debugger",
                     "workstation-designer", "workstation-framework-dev"]:
            if prof in a:
                _HOOK_PROFILE = prof
                break
        if _HOOK_PROFILE != "unknown":
            break

# Lazy-init audit engine
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        try:
            import sys
            sys.path.insert(0, "F:/workstation/projects/agent-audit")
            from agent_audit.engine import AuditEngine
            _engine = AuditEngine(_HOOK_DB)
        except Exception:
            _engine = False
    return _engine if _engine is not False else None


def _patch_httpx():
    """Monkey-patch httpx.Client.request AND AsyncClient.request to record LLM calls."""
    try:
        import httpx

        # Shared audit logic
        def _audit_call(url_str, kwargs, status_code, dt):
            engine = _get_engine()
            if not engine:
                return
            if not any(h in url_str for h in ("deepseek", "xiaomimimo", "openai")):
                return
            content = kwargs.get("content") or kwargs.get("json")
            if not content:
                return
            try:
                body = json.loads(content) if isinstance(content, bytes) else content
                model = body.get("model", "?")
                msgs = body.get("messages", [{}])
                txt = (msgs[-1].get("content", "") or "")[:200] if msgs else ""
            except Exception:
                model = "?"; txt = ""
            engine.log(
                session_id=f"hook-{_HOOK_PROFILE}",
                event_type="llm_request",
                agent_id=_HOOK_PROFILE,
                prompt_version=model,
                input_text=txt,
                output_text=f"{status_code}",
                metadata={"model": model, "ms": dt, "url": url_str[:80]},
            )

        # Patch async client
        _orig_async = httpx.AsyncClient.request

        @functools.wraps(_orig_async)
        async def _audited_async(self, method, url, **kwargs):
            t0 = time.monotonic()
            resp = await _orig_async(self, method, url, **kwargs)
            dt = int((time.monotonic() - t0) * 1000)
            try:
                _audit_call(str(url), kwargs, resp.status_code, dt)
            except Exception:
                pass
            return resp

        httpx.AsyncClient.request = _audited_async

        # Patch sync client
        _orig_sync = httpx.Client.request

        @functools.wraps(_orig_sync)
        def _audited_sync(self, method, url, **kwargs):
            t0 = time.monotonic()
            resp = _orig_sync(self, method, url, **kwargs)
            dt = int((time.monotonic() - t0) * 1000)
            try:
                _audit_call(str(url), kwargs, resp.status_code, dt)
            except Exception:
                pass
            return resp

        httpx.Client.request = _audited_sync
        return True
    except Exception:
        return False


# Auto-patch on import
_patch_httpx()
