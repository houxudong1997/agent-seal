"""
agent-seal server middleware stack — CORS, GZip, API Key auth.

Architecture reference: docs/architecture-v1.md line 1045.
Extracted from app.py so middleware configuration is centralized
and the app factory stays lean.

Order matters: middleware added *last* runs *first* on the way in.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from ..config import config

logger = logging.getLogger(__name__)

# ── Per-middleware setup functions ──────────────────────────────────────


def setup_cors(app: FastAPI) -> None:
    """Configure CORS from AGENT_SEAL_CORS_ORIGINS.

    Defaults to ``[]`` (no origins allowed — secure by default);
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def setup_gzip(app: FastAPI) -> None:
    """Compress JSON/HTML/text responses > 1 KB."""
    app.add_middleware(GZipMiddleware, minimum_size=1000)


def setup_prometheus(app: FastAPI) -> None:
    """Wire up ``prometheus-fastapi-instrumentator`` for automatic
    per-request metrics (latency histograms, request counts).

    Uses a **dedicated** ``CollectorRegistry`` (not the global default)
    so that multiple app instances in the same process (e.g. during
    test suites) don't conflict with duplicate metric registrations.

    The dedicated registry is registered with ``metrics.py`` so the
    ``/metrics`` endpoint aggregates both business-level and
    request-level metrics.

    When ``PROMETHEUS_MULTIPROC_DIR`` is set the instrumentator
    automatically switches to multi-process mode — no code changes
    needed.
    """
    try:
        from prometheus_client import CollectorRegistry
        from prometheus_fastapi_instrumentator import Instrumentator

        from .metrics import register_external_registry

        # Dedicated registry avoids cross-app metric conflicts when
        # multiple FastAPI instances live in the same process (tests,
        # hot-reload, etc.).
        inst_registry = CollectorRegistry()

        instrumentator = Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            should_instrument_requests_inprogress=False,
            excluded_handlers=[
                "/metrics",
                "/health",
                "/ready",
                "/favicon.svg",
                "/icons.svg",
            ],
            body_handlers=[],
            round_latency_decimals=4,
            registry=inst_registry,
        )
        instrumentator.instrument(app)
        # Don't call .expose() — we serve /metrics via the admin router
        # (routes/admin.py) which aggregates all metrics including the
        # instrumentator's.  The instrumentator's middleware still collects
        # request-level metrics regardless of whether its own route is added.

        # Register with metrics.py so generate() aggregates this registry.
        register_external_registry(inst_registry)

        logger.info(
            "Prometheus request-level instrumentation active "
            "(prometheus-fastapi-instrumentator %s)",
            getattr(Instrumentator, "__version__", "unknown"),
        )
    except ImportError:
        logger.warning(
            "prometheus-fastapi-instrumentator not installed; "
            "request-level metrics disabled. Install with: "
            "pip install prometheus-fastapi-instrumentator"
        )
    except ValueError:
        # prometheus_client raises ValueError("Duplicated timeseries...")
        # when the app is recreated in the same process (e.g. during tests
        # that call setup_all() multiple times).  The instrumentator is
        # already registered from a prior call — safe to ignore.
        logger.debug(
            "Prometheus instrumentator already registered (duplicate init skipped)"
        )


# ── API Key authentication middleware ──────────────────────────────────


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate /api/* routes when ``AGENT_SEAL_API_KEYS`` is configured.

    When no keys are set (the default for local development) every
    request passes through — zero-config dev experience.

    Accepts the key via:

        - ``X-API-Key: <key>``
        - ``Authorization: Bearer <key>``

    Health/readiness/stream endpoints are always public.
    """

    AUTH_HEADER = "X-API-Key"
    BEARER_PREFIX = "Bearer "

    # Endpoints that never require authentication
    _PUBLIC_ENDPOINTS: frozenset[str] = frozenset(
        {
            "/health",
            "/ready",
            "/metrics",
            "/api/v1/stats",
            "/api/v1/events/stream",
        }
    )

    def __init__(self, app, api_keys: list[str]):
        super().__init__(app)
        self._keys: set[str] = {k for k in api_keys if k}
        self._enabled = bool(self._keys)
        if self._enabled:
            logger.info("API Key auth enabled: %d key(s) configured", len(self._keys))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only protect /api/* routes, and only when keys are configured
        if not self._enabled or not request.url.path.startswith("/api"):
            return await call_next(request)

        # Public endpoints — no auth required
        if request.url.path in self._PUBLIC_ENDPOINTS:
            return await call_next(request)

        # Extract key
        raw_key = request.headers.get(self.AUTH_HEADER)
        if not raw_key:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith(self.BEARER_PREFIX):
                raw_key = auth_header[len(self.BEARER_PREFIX) :]

        if not raw_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        # Constant-time key comparison — avoids timing side-channel
        # from Python set membership (hash-based lookup).
        # Evaluate ALL comparisons before checking any() to avoid
        # short-circuit leaking which key matched.
        matches = [secrets.compare_digest(raw_key, k) for k in self._keys]
        if not any(matches):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        return await call_next(request)


def setup_api_key_auth(app: FastAPI) -> None:
    """Apply API-key auth middleware when AGENT_SEAL_API_KEYS is set."""
    keys = config.api_keys
    # Only register the middleware when keys are actually configured.
    # When keys is empty the middleware is a no-op anyway, but skipping
    # the add_middleware call avoids an unnecessary hop for every request.
    if keys:
        app.add_middleware(APIKeyAuthMiddleware, api_keys=keys)


# ── Convenience: apply everything ──────────────────────────────────────


def setup_all(app: FastAPI) -> None:
    """Apply the full middleware stack to a FastAPI app instance.

    Call this *once* during app creation, before any routes are registered::

        from agent_seal.server.middlewares import setup_all
        setup_all(app)
    """
    setup_gzip(app)
    setup_cors(app)
    setup_api_key_auth(app)
    setup_prometheus(app)
