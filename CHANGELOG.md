# Changelog

All notable changes to agent-seal will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-06-22

### Added
- **@observe decorator** — Lightweight function tracing. `@observe` records inputs, outputs, execution time, and nested parent-child spans into the audit trail.
- **LangChain CallbackHandler** — Native tracing for LangChain LCEL chains, agents, and tools via `LangChainAuditHandler`.
- **Hermes middleware** — Zero-config middleware for Hermes Agent framework, auto-instruments all agent actions.
- **Global sitecustomize hook** — Zero-code auto-instrumentation. Drop `sitecustomize.py` into site-packages and all Python processes are automatically traced — no code changes needed.
- **SPA Dashboard enhancements** — Event list with expandable details, smart previews, model/latency columns, binary/garbled output filtering.

## [1.0.0] — 2026-06-21

### Added

- **PostgreSQL backend** — production-grade, concurrent-safe storage with `psycopg2` connection pooling and SQLAlchemy ORM with `alembic` migration support.
- **FastAPI server** — ASGI production server with OpenAPI docs (`/docs`), CORS, SSE streaming, structured logging (text/JSON), health/readiness endpoints.
- **SPA Dashboard** — real-time Svelte dashboard with SSE live updates, no build step required.
- **SSE streaming endpoint** — `GET /api/v1/events/stream` for real-time dashboard updates, with 15-second keepalive pings.
- **LLM auto-tracing** — zero-instrumentation monkey-patching for OpenAI and Anthropic SDKs. Automatic token counting, latency measurement, and cost tracking.
- **PII redaction** — automatic PII stripping from traced content via regex patterns (emails, phones, SSNs, credit cards).
- **Prometheus metrics** — `GET /metrics` endpoint exporting `audit_events_total`, `audit_sessions_active`, `audit_policy_denials_total`, and more.
- **Encrypted storage backend** — AES-256-GCM transparent encryption at rest via `EncryptedStore`.
- **Digital signatures** — Ed25519 signing per event with configurable signing key.
- **Policy engine** — YAML-based guardrail rules blocking dangerous patterns (`rm -rf`, `DROP TABLE`, API key leaks). Verdicts: PASS / BLOCK / APPROVAL.
- **Evidence export** — tamper-evident `.zip` bundles with SHA-256 verification for auditors.
- **Prompt versioning** — Git-like prompt history with diff support, recording who, when, and why for every prompt change.
- **Docker Compose** — 4-service production stack (nginx → API → PostgreSQL 15 + Redis) with health checks and named volumes.
- **Multi-stage Docker build** — builder stage → production image, non-root `agentseal` user.
- **Nginx reverse proxy** — TLS termination, static file serving for SPA assets, proxy_pass to API.
- **`.env.example`** — complete environment variable reference with inline documentation.
- **Slack webhook notifications** — audit alerts for policy blocks, integrity failures, error spikes.
- **Email alerts** — SMTP-based configurable failure notifications.
- **172-test pytest suite** — all green across 7+ test modules.

### Changed

- **Config namespace**: all environment variables now use `AGENT_SEAL_` prefix. Legacy names still read as fallback.
- **API versioning**: all v1 endpoints under `/api/v1/`. Legacy v0.1 endpoints preserved with redirects.
- **API response format**: session endpoints now return rich summaries instead of raw ID lists.
- **Unified store factory**: `create_store()` auto-detects backend from URI scheme (`postgresql://` → PG, `sqlite://` or `.db` → SQLite, directory → JSONL).
- **Database URL config**: standardized `AGENT_SEAL_DB_URL` across all backends, replacing old `AGENT_SEAL_DIR` / `AGENT_SEAL_URI`.

### Deprecated

- Legacy v0.1 API paths (`GET /sessions`, `GET /stats`, `POST /log`, `POST /verify`). Migrate to `/api/v1/` equivalents.
- Legacy environment variable names (`AUDIT_DIR`, `DB_URL`, `API_KEYS`, `SECRET_KEY`, `LOG_LEVEL`). Migrate to `AGENT_SEAL_` prefix.

[1.1.0]: https://github.com/user/agent-seal/releases/tag/v1.1.0
[1.0.0]: https://github.com/user/agent-seal/releases/tag/v1.0.0
