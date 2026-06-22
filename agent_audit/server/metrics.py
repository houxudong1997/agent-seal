"""
Prometheus metrics for agent-audit.

Uses the ``prometheus_client`` library for production-grade metrics
with Counter, Gauge, Histogram, labels, and multi-process support.

Exposed metrics:
    Counters (monotonically increasing):
        audit_events_total{event_type, agent_id}  — total events recorded
        audit_policy_decisions_total{decision}     — policy decisions (blocked/approved/passed)
        audit_verify_checks_total                  — integrity verification runs
        audit_http_requests_total{method, path, status}  — HTTP request counter

    Gauges (up/down):
        audit_sessions_active                      — active sessions
        audit_storage_bytes{backend}               — estimated storage size
        audit_uptime_seconds                       — server uptime

    Histograms:
        audit_event_log_duration_seconds           — time to log an event
        audit_request_latency_seconds              — HTTP request latency

Multi-process mode: set ``PROMETHEUS_MULTIPROC_DIR`` to a writable
directory path; metrics are collected from all worker processes.

Version info: ``audit_info{version, storage_backend}``.
"""

from __future__ import annotations

import logging
import os
import time

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
    multiprocess,
)
from prometheus_client.registry import Collector

from ..config import config

logger = logging.getLogger(__name__)

# ── Multi-process support ───────────────────────────────────────────────
# When PROMETHEUS_MULTIPROC_DIR is set, metrics are stored in
# per-process mmap files and aggregated by the collector.
# https://github.com/prometheus/client_python#multiprocess-mode-gunicorn

_MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "")
_MULTIPROC = bool(_MULTIPROC_DIR)

if _MULTIPROC:
    logger.info("Prometheus multi-process mode: dir=%s", _MULTIPROC_DIR)
    # In multi-process mode, use the default registry (which reads from
    # mmap files) and don't create new metrics — they'll be collected
    # from the multiprocess data store.
    _REGISTRY: CollectorRegistry | None = None
else:
    _REGISTRY = CollectorRegistry(auto_describe=True)

# ── Registry helper ─────────────────────────────────────────────────────


def _registry() -> CollectorRegistry:
    """Return the active registry (multi-process or local)."""
    if _MULTIPROC:
        return CollectorRegistry()  # fresh registry reads mmap files
    assert _REGISTRY is not None
    return _REGISTRY


# ── Metric definitions ──────────────────────────────────────────────────

# Counters
_events_total = Counter(
    "audit_events_total",
    "Total number of audit events recorded",
    ["event_type", "agent_id"],
    registry=_REGISTRY,
)

_policy_decisions_total = Counter(
    "audit_policy_decisions_total",
    "Policy engine decision counts",
    ["decision"],  # passed / blocked / approval_required
    registry=_REGISTRY,
)

_verify_checks_total = Counter(
    "audit_verify_checks_total",
    "Integrity verification runs",
    registry=_REGISTRY,
)

_http_requests_total = Counter(
    "audit_http_requests_total",
    "HTTP request count",
    ["method", "path_template", "status_code"],
    registry=_REGISTRY,
)

# Gauges
_sessions_active = Gauge(
    "audit_sessions_active",
    "Number of active audit sessions",
    registry=_REGISTRY,
)

_storage_bytes = Gauge(
    "audit_storage_bytes",
    "Estimated storage size in bytes",
    ["backend"],
    registry=_REGISTRY,
)

_uptime_seconds = Gauge(
    "audit_uptime_seconds",
    "Seconds since agent-audit started",
    registry=_REGISTRY,
)

# Histograms
_event_log_duration = Histogram(
    "audit_event_log_duration_seconds",
    "Time to log an audit event",
    ["event_type"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    registry=_REGISTRY,
)

_request_latency = Histogram(
    "audit_request_latency_seconds",
    "HTTP request latency",
    ["method", "path_template"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=_REGISTRY,
)

# Info
_start_time = time.time()
_uptime_seconds.set_function(lambda: time.time() - _start_time)

_info = Info("audit", "agent-audit build information", registry=_REGISTRY)
_info.info(
    {
        "version": "1.0.0",
        "storage_backend": config.storage_backend,
    }
)

# ── All known collectors (for the /metrics endpoint generator) ──────────

_ALL_COLLECTORS: list[Collector] = [
    _events_total,
    _policy_decisions_total,
    _verify_checks_total,
    _http_requests_total,
    _sessions_active,
    _storage_bytes,
    _uptime_seconds,
    _event_log_duration,
    _request_latency,
    _info,
]

# ── Backward-compatible convenience API ─────────────────────────────────
# Legacy callers used inc("name") and set_gauge("name", value).
# These are retained for compatibility but routed through the new metrics.


# Map old flat metric names to new prometheus_client objects.
# Labels are set to default values where the old API didn't carry them.
_LEGACY_METRIC_MAP: dict[str, Counter | Gauge] = {
    "audit_events_total": _events_total,
    "audit_policy_denials": _policy_decisions_total,
    "audit_policy_approvals": _policy_decisions_total,
    "audit_verify_checks": _verify_checks_total,
    "audit_sessions_active": _sessions_active,
    "audit_storage_bytes": _storage_bytes,
}


def inc(name: str, delta: int = 1) -> None:
    """Increment a named counter (legacy API).

    For labeled metrics, uses default empty labels.
    Prefer the new label-aware API for production code.
    """
    metric = _LEGACY_METRIC_MAP.get(name)
    if metric is None:
        logger.warning("metrics.inc: unknown metric name %r", name)
        return

    # Old "audit_policy_denials" and "audit_policy_approvals" both map
    # to _policy_decisions_total, but with different label values.
    if name == "audit_policy_denials":
        _policy_decisions_total.labels(decision="blocked").inc(delta)
    elif name == "audit_policy_approvals":
        _policy_decisions_total.labels(decision="approval_required").inc(delta)
    elif name == "audit_events_total":
        _events_total.labels(event_type="", agent_id="").inc(delta)
    elif name == "audit_verify_checks":
        _verify_checks_total.inc(delta)
    elif name == "audit_storage_bytes":
        _storage_bytes.labels(backend="").inc(delta)
    elif name == "audit_sessions_active":
        _sessions_active.inc(delta)


def set_gauge(name: str, value: float) -> None:
    """Set a gauge metric (legacy API).

    For labeled metrics, uses default empty labels.
    Prefer the new label-aware API for production code.
    """
    if name == "audit_sessions_active":
        _sessions_active.set(value)
    elif name == "audit_storage_bytes":
        _storage_bytes.labels(backend="").set(value)
    else:
        logger.warning("metrics.set_gauge: unknown metric name %r", name)


# ── New labeled API ─────────────────────────────────────────────────────


def record_event(
    event_type: str = "",
    agent_id: str = "",
    duration: float = 0.0,
) -> None:
    """Record an audit event with labels.

    Args:
        event_type: ``decision`` / ``tool_call`` / ``model_request`` / ``guardrail``
        agent_id: Identifies the agent that produced the event.
        duration: Processing time in seconds (observes histogram).
    """
    _events_total.labels(event_type=event_type, agent_id=agent_id).inc()
    if duration > 0:
        _event_log_duration.labels(event_type=event_type).observe(duration)


def record_policy_decision(decision: str) -> None:
    """Record a policy engine decision.

    Args:
        decision: ``passed`` / ``blocked`` / ``approval_required``
    """
    _policy_decisions_total.labels(decision=decision).inc()


def record_verify_check() -> None:
    """Record an integrity verification run."""
    _verify_checks_total.inc()


def record_http_request(
    method: str = "",
    path_template: str = "",
    status_code: str = "",
    latency: float = 0.0,
) -> None:
    """Record an HTTP request with labels.

    Args:
        method: HTTP method (GET, POST, ...)
        path_template: Route template (e.g. ``/api/v1/events``)
        status_code: HTTP status code as string (e.g. ``200``)
        latency: Request duration in seconds (observes histogram).
    """
    _http_requests_total.labels(
        method=method,
        path_template=path_template,
        status_code=status_code,
    ).inc()
    if latency > 0:
        _request_latency.labels(
            method=method,
            path_template=path_template,
        ).observe(latency)


def set_sessions_active(count: int) -> None:
    """Set the active sessions gauge."""
    _sessions_active.set(count)


def set_storage_bytes(backend: str, size_bytes: int) -> None:
    """Set the storage size gauge for a backend."""
    _storage_bytes.labels(backend=backend).set(size_bytes)


# ── Metrics endpoint generator ──────────────────────────────────────────

# Optional external registry (e.g. from prometheus-fastapi-instrumentator).
# Stored here so generate() can merge it into the /metrics output.
_INSTRUMENTATOR_REGISTRY: CollectorRegistry | None = None


def register_external_registry(registry: CollectorRegistry) -> None:
    """Register an external ``CollectorRegistry`` whose metrics should be
    included in the ``/metrics`` endpoint output.

    Call this from ``setup_prometheus()`` after creating a dedicated
    registry for ``prometheus-fastapi-instrumentator``.
    """
    global _INSTRUMENTATOR_REGISTRY
    _INSTRUMENTATOR_REGISTRY = registry


def generate() -> str:
    """Generate Prometheus-format metrics text for the ``/metrics`` endpoint.

    In multi-process mode, aggregates metrics from all worker processes.
    In single-process mode, returns the full registry output including
    all Python platform metrics and any registered external registry
    (e.g. prometheus-fastapi-instrumentator).
    """
    if _MULTIPROC:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return str(generate_latest(registry).decode("utf-8"))
    else:
        # Collect from our primary registry
        output: str = generate_latest(_REGISTRY).decode("utf-8")

        # Merge instrumentator registry if registered
        if _INSTRUMENTATOR_REGISTRY is not None:
            output += "\n" + str(generate_latest(_INSTRUMENTATOR_REGISTRY).decode("utf-8"))

        return output


# ── Handlers for fastapi-prometheus-instrumentator ──────────────────────
# These are plain functions (not async) because the instrumentator
# calls them synchronously. They act as adapters between the
# instrumentator callbacks and our labeled metric primitives.


def _instrumentator_http_handler(
    method: str,
    path_template: str,
    status_code: int,
    _duration: float,
) -> None:
    """Callback for prometheus-fastapi-instrumentator HTTP metrics."""
    _http_requests_total.labels(
        method=method,
        path_template=path_template,
        status_code=str(status_code),
    ).inc()


# ── Cleanup ─────────────────────────────────────────────────────────────


def shutdown() -> None:
    """Clean up multi-process metrics resources."""
    if _MULTIPROC:
        multiprocess.mark_process_dead(os.getpid())
