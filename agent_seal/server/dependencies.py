"""
Shared infrastructure for all route modules.

Provides singleton instances of the audit engine, prompt registry,
SSE stream listeners, and helper functions that every route module needs.
Extracted from app.py to avoid circular imports and keep route modules
self-contained.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

from ..config import config
from ..core.storage import AuditEngine
from ..prompt_version import PromptRegistry

logger = logging.getLogger(__name__)

# ── Engine singleton ─────────────────────────────────────────────────────

_engine: AuditEngine | None = None
_prompt_registry: PromptRegistry | None = None


def get_engine() -> AuditEngine:
    """Lazy-init the AuditEngine singleton."""
    global _engine
    if _engine is None:
        _engine = AuditEngine(config.store_uri)
    return _engine


def get_prompt_registry() -> PromptRegistry:
    """Lazy-init the PromptRegistry singleton."""
    global _prompt_registry
    if _prompt_registry is None:
        _prompt_registry = PromptRegistry(config.audit_dir)
    return _prompt_registry


# ── LLM call in-memory store ─────────────────────────────────────────────
# Used by POST /api/v1/llm/log, GET /api/v1/llm/traces/{trace_id}, and
# GET /api/v1/llm/stats.  When a PostgreSQL ORM backend is active the
# data lives in the llm_calls table; this in-memory store serves as a
# light-weight default for SQLite / JSONL deployments.
#
# Capped at _LLM_CALLS_MAX_LEN entries (10 000 by default) to prevent
# unbounded memory growth in long-running processes.  When the limit is
# reached the oldest entries are evicted (FIFO ring buffer).

_LLM_CALLS_MAX_LEN = 10_000
_llm_calls: list[dict] = []


def store_llm_call(call: dict) -> dict:
    """Persist an LLM call record. Returns the stored dict with an assigned id."""
    if len(_llm_calls) >= _LLM_CALLS_MAX_LEN:
        _llm_calls.pop(0)  # Evict oldest
    call["id"] = len(_llm_calls) + 1
    _llm_calls.append(call)
    return call


def query_llm_trace(trace_id: str) -> list[dict]:
    """Return all LLM calls belonging to a trace, ordered by timestamp."""
    matches = [c for c in _llm_calls if c.get("trace_id") == trace_id]
    matches.sort(key=lambda c: c.get("timestamp", ""))
    return matches


def llm_stats() -> dict:
    """Compute aggregate LLM usage statistics from stored calls."""
    total_calls = len(_llm_calls)
    if total_calls == 0:
        return {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "by_provider": {},
            "by_model": {},
        }

    total_tokens = sum(c.get("total_tokens", 0) for c in _llm_calls)
    total_cost = sum(float(c.get("cost_usd", 0) or 0) for c in _llm_calls)
    latencies = [c.get("latency_ms", 0) for c in _llm_calls if c.get("latency_ms")]

    by_provider: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    for c in _llm_calls:
        provider = c.get("provider", "unknown")
        model = c.get("model", "unknown")
        for bucket, key in [(by_provider, provider), (by_model, model)]:
            if key not in bucket:
                bucket[key] = {"calls": 0, "tokens": 0, "cost_usd": 0.0}
            bucket[key]["calls"] += 1
            bucket[key]["tokens"] += c.get("total_tokens", 0)
            bucket[key]["cost_usd"] += float(c.get("cost_usd", 0) or 0)

    import statistics

    return {
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "avg_latency_ms": round(statistics.mean(latencies)) if latencies else 0,
        "p50_latency_ms": round(statistics.median(latencies)) if latencies else 0,
        "p95_latency_ms": _percentile(latencies, 95) if latencies else 0,
        "p99_latency_ms": _percentile(latencies, 99) if latencies else 0,
        "by_provider": by_provider,
        "by_model": by_model,
    }


def _percentile(data: list[int], pct: float) -> int:
    """Compute the pct-th percentile from a list of integers."""
    data_sorted = sorted(data)
    k = (len(data_sorted) - 1) * pct / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(data_sorted):
        return round(data_sorted[f] + c * (data_sorted[f + 1] - data_sorted[f]))
    return data_sorted[f]


# ── SSE stream listeners ─────────────────────────────────────────────────

_stream_listeners: list[asyncio.Queue] = []


async def notify_stream_listeners(event: dict) -> None:
    """Push a new event to all active SSE listeners."""
    stale: list[asyncio.Queue] = []
    for q in _stream_listeners:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            stale.append(q)
    for q in stale:
        with suppress(ValueError):
            _stream_listeners.remove(q)


def register_stream_listener(queue: asyncio.Queue) -> None:
    """Register a new SSE listener queue."""
    _stream_listeners.append(queue)


def unregister_stream_listener(queue: asyncio.Queue) -> None:
    """Remove an SSE listener queue."""
    with suppress(ValueError):
        _stream_listeners.remove(queue)


# ── Integrity helper ─────────────────────────────────────────────────────


def safe_integrity(engine: AuditEngine, session_id: str) -> str:
    """Check chain integrity, returning 'ok', 'broken', or 'unknown'."""
    try:
        return "ok" if engine.verify(session_id) else "broken"
    except (OSError, ValueError) as exc:
        logger.exception("Integrity check failed for session %s: %s", session_id, exc)
        return "unknown"


# ── Dashboard static files ───────────────────────────────────────────────

_STATIC_DIR = Path(__file__).parent / "static"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

_FALLBACK_SPA_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Agent Seal Dashboard</title>
<style>
:root{--bg:#0a0e14;--text:#c9d1d9;--dim:#6b7280;--cyan:#39d2c0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);max-width:600px;margin:80px auto;text-align:center;line-height:1.6}
h1{color:var(--cyan)}p{color:var(--dim);margin-top:16px}
</style>
</head>
<body>
<h1>Agent Seal Dashboard</h1>
<p>SPA build not found. Run <code>cd spa && npm run build</code> to generate the dashboard.</p>
<p>API is available at <a href="/docs" style="color:var(--cyan)">/docs</a></p>
</body>
</html>"""


def load_dashboard_html() -> str:
    """Load the dashboard template.

    Priority: static/index.html (Svelte build) > templates/index.html (fallback SPA).
    The static version is the compiled Svelte SPA from spa/.
    The templates version is a self-contained HTML file with inline CSS/JS
    used as a fallback when the Svelte build is unavailable.
    """
    static_path = _STATIC_DIR / "index.html"
    if static_path.exists():
        return static_path.read_text(encoding="utf-8")
    template_path = _TEMPLATES_DIR / "index.html"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return _FALLBACK_SPA_HTML


def get_static_dir() -> Path:
    """Return the static asset directory path."""
    return _STATIC_DIR
