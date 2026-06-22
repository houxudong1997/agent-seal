# agent-audit v1.0.0 Release Notes

> **Release Date**: 2026-06-21
> **Codename**: "Enterprise Foundations"
> **Version**: v1.0.0

**agent-audit v1.0** is the first production-grade release. It transforms the v0.1 proof-of-concept into a deployable, scalable, and observable enterprise audit trail system for AI agents — ready for EU AI Act Article 12 compliance.

---

## Highlights

- **PostgreSQL backend** — production-grade, concurrent-safe storage
- **FastAPI server** — with OpenAPI docs, CORS, SSE streaming, and structured logging
- **SPA Dashboard** — real-time Svelte dashboard with SSE live updates, no build step required
- **Docker Compose** — full production stack: nginx → API → PostgreSQL + Redis
- **LLM auto-tracing** — zero-instrumentation tracing for OpenAI and Anthropic SDKs
- **172 test suite** — pytest, all green

---

## What's New

### Storage

| Feature | Description |
|---|---|
| **PostgreSQL backend** | New `PostgreSQLStore` with `psycopg2` connection pooling (1–10 connections). JSONB metadata with native PostgreSQL types. Auto-creates schema on first use. |
| **PostgreSQL ORM backend** | New `PostgreSQLStoreORM` (SQLAlchemy) with full `alembic` migration support. UUID primary keys, INET types, GIN indexes on JSONB. |
| **Unified `create_store()` factory** | Single entry point for all backends. Auto-detects from URI scheme: `postgresql://` → PG, `sqlite://` or `.db` → SQLite, directory → JSONL. |
| **`AGENT_AUDIT_DB_URL` config** | Standardized database URL across all backends. Replaces old `AGENT_AUDIT_DIR` / `AGENT_AUDIT_URI`. |

### Server & API

| Feature | Description |
|---|---|
| **FastAPI replaces http.server** | Production ASGI server (uvicorn). Automatic OpenAPI docs at `/docs`. Proper HTTP status codes, query parameter validation, CORS. |
| **API versioning** | All v1 endpoints under `/api/v1/`. Legacy endpoints preserved for backward compat with redirect to v1. |
| **SSE streaming** | `GET /api/v1/events/stream` — Server-Sent Events for real-time dashboard updates. New events pushed to all connected clients. |
| **Structured logging** | `AGENT_AUDIT_LOG_FORMAT=json` for ELK/Loki integration. Text format for human readability. |
| **Health + readiness** | `GET /health` and `GET /ready` endpoints for Kubernetes liveness/readiness probes. |

### Dashboard

| Feature | Description |
|---|---|
| **SPA Dashboard** | Self-contained HTML template (`templates/index.html`) with inline CSS/JS. No build step required — works out of the box. |
| **Real-time event feed** | SSE-powered live event stream. New audit events appear instantly. |
| **Tab-based navigation** | Overview, Events, Sessions, Prompts, Integrity, Evidence — all in one page. |
| **Grafana dashboard** | Pre-built dashboard at `deploy/grafana/dashboards/agent-audit-overview.json`. 12 panels: event throughput, token usage, latency P50/P95/P99, error rate, and more. |

### Tracing & Observability

| Feature | Description |
|---|---|
| **LLM auto-tracing** | `import agent_audit.tracing.auto` — monkey-patches OpenAI/Anthropic SDKs. All LLM calls automatically recorded with tokens, latency, and cost. |
| **PII redaction** | `AGENT_AUDIT_TRACE_PII_REDACT=1` — automatically strips PII from traced content. Uses regex patterns for emails, phones, SSNs, credit cards. |
| **Cost tracking** | Token → USD cost calculation. Per-model pricing. Read from `AGENT_AUDIT_TRACE_COST_MODEL`. |
| **Prometheus metrics** | `GET /metrics` endpoint exports `audit_events_total`, `audit_sessions_active`, `audit_policy_denials_total`, and more. |

### Security & Compliance

| Feature | Description |
|---|---|
| **Encrypted storage** | `AES-256-GCM` encrypted backend (`EncryptedStore`). Transparent encryption at rest. Requires 32-byte hex key. |
| **Digital signatures** | `Ed25519` signing. Each event optionally signed with a private key. `AGENT_AUDIT_SIGNING_KEY` points to PEM file. |
| **Policy engine** | YAML-based guardrail rules. Default rules block dangerous patterns (`rm -rf`, `DROP TABLE`, API key leaks). Veredict: PASS / BLOCK / APPROVAL. |
| **Evidence export** | `.zip` evidence bundles with SHA-256 verification. Tamper-evident packaging for auditors. |
| **Prompt versioning** | Git-like prompt history with diff support. Every prompt change is recorded with who, when, and why. |

### Notifications

| Feature | Description |
|---|---|
| **Slack webhooks** | `AGENT_AUDIT_SLACK_WEBHOOK` — audit alerts delivered to Slack. Policy blocks, integrity failures, error spikes. |
| **Email alerts** | `AGENT_AUDIT_SMTP_HOST` — SMTP-based email notifications. Configurable failure alerts. |
| **Failure notifications** | `AGENT_AUDIT_NOTIFY_ON_FAILURE=1` — auto-notify on integrity breaks. |

### Deployment

| Feature | Description |
|---|---|
| **Docker Compose** | 4-service stack: nginx (reverse proxy) + api (FastAPI) + db (PostgreSQL 15) + redis (caching). Health checks on all services. Named volumes for persistence. |
| **Multi-stage Docker build** | Builder stage → production stage. No build tools in runtime image. Non-root user (`agentaudit`). Health check built in. |
| **Nginx reverse proxy** | TLS termination, static file serving for SPA assets, proxy_pass to API. |
| **`.env.example`** | Complete environment variable reference with inline documentation. 12-Factor App compliant. |

---

## Breaking Changes

### Config namespace

All environment variables now use the `AGENT_AUDIT_` prefix:

| v0.1 | v1.0 | Notes |
|---|---|---|
| `AUDIT_DIR` | `AGENT_AUDIT_AUDIT_DIR` | Still supported for backward compat |
| `DB_URL` / `DATABASE_URL` | `AGENT_AUDIT_DB_URL` | Legacy vars still read as fallback |
| `API_KEYS` | `AGENT_AUDIT_API_KEYS` | Legacy var still read as fallback |
| `SECRET_KEY` | `AGENT_AUDIT_SECRET_KEY` | Legacy var still read as fallback |
| `SIGNING_KEY` | `AGENT_AUDIT_SIGNING_KEY` | New namespace only |
| `LOG_LEVEL` | `AGENT_AUDIT_LOG_LEVEL` | Legacy var still read as fallback |

### API paths

Legacy endpoints are preserved but deprecated. Migrate to v1:

| v0.1 Legacy (deprecated) | v1.0 |
|---|---|
| `GET /sessions` | `GET /api/v1/sessions` |
| `GET /session/<id>` | `GET /api/v1/sessions/{id}` |
| `GET /stats` | `GET /api/v1/stats` |
| `POST /log` | `POST /api/v1/log` |
| `POST /verify` | `POST /api/v1/verify` |

### Storage backend

- Default remains JSONL directory for local dev (no breaking change for existing users).
- PostgreSQL is now the recommended production backend.
- `create_store()` factory replaces direct `JSONLStore()` or `SQLiteStore()` instantiation.

### API response format

| v0.1 `GET /sessions` | v1.0 `GET /api/v1/sessions` |
|---|---|
| `{"sessions": ["sid1", "sid2"]}` | `{"sessions": [{"session_id": "sid1", "event_count": 5, ...}]}` |

v1.0 returns rich session summaries. v0.1 returns raw ID list.

---

## Upgrade Path

### From v0.1.0 (JSONL)

```bash
# 1. Update package
pip install --upgrade agent-audit

# 2. Update .env (add AGENT_AUDIT_ prefix)
#    Legacy vars still work, but we recommend migrating:
#    AUDIT_DIR=./audit_logs  →  AGENT_AUDIT_AUDIT_DIR=./audit_logs

# 3. Restart server
agent-audit serve
```

Your existing JSONL audit trail continues to work. No data migration required unless switching to PostgreSQL — see `docs/migration-guide.md`.

### From v0.1.0 (SQLite)

```bash
# Same as above. SQLite backend is unchanged.
agent-audit serve
```

---

## Known Issues

1. **SSE stream disconnect on silent periods**: Clients may timeout on long idle periods. The server sends keepalive pings every 15 seconds. Adjust client timeout to >30s.
2. **PostgreSQLStoreORM timestamp type**: Event timestamps are stored as `DateTime` in the ORM model but the underlying `ChainEvent` uses `float` (Unix time). Conversion is handled in `_model_to_dict()` but custom queries on the ORM model should expect `datetime` objects.
3. **Large event payloads**: `input_snapshot` and `output_snapshot` are truncated to 8000 characters. Set `AGENT_AUDIT_TRACE_MAX_LEN` to adjust (max 8000).
4. **Windows SSL**: On Windows, `psycopg2` may need `libpq` from a PostgreSQL installation. Use `psycopg2-binary` to avoid this.

---

## Dependencies

### Runtime (setup.py install_requires)

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | >=0.100 | REST API framework |
| `uvicorn[standard]` | >=0.20 | ASGI server |
| `sse-starlette` | >=1.0 | Server-Sent Events |
| `python-dotenv` | >=1.0 | .env configuration |
| `sqlalchemy` | >=2.0 | ORM (PostgreSQL ORM backend) |
| `cryptography` | >=43.0 | Ed25519 + AES-256-GCM |
| `pyyaml` | >=6.0 | Policy rules parsing |
| `pydantic` | >=2.0 | Data validation |
| `alembic` | >=1.13 | Database migrations |

### Optional

| Package | Version | Extra | Purpose |
|---|---|---|---|
| `psycopg2-binary` | >=2.9 | `[postgres]` | PostgreSQL driver |

---

## What's Next (v1.1+)

- **TimescaleDB support** — automatic hypertable partitioning for high-volume event streams
- **Kubernetes Helm chart** — production K8s deployment with autoscaling
- **SOC 2 attestation** — pre-built compliance evidence packages
- **Webhook integrations** — PagerDuty, Opsgenie, Datadog
- **Multi-tenant mode** — isolated audit trails per organization
- **Audit report scheduling** — automated periodic EU AI Act reports

---

## Resources

- **README**: `README.md` — Getting started, usage examples
- **Architecture**: `docs/architecture-v1.md` — Full v1.0 architecture design
- **Migration Guide**: `docs/migration-guide.md` — JSONL/SQLite → PostgreSQL
- **API Reference**: `docs/api-v1.md` — Complete REST API documentation
- **Interactive docs**: `http://localhost:8081/docs` (when server is running)

---

## Feedback

Issues and feature requests: file in the project repository.

---

*agent-audit v1.0.0 — Tamper-evident. Production-ready. EU AI Act compliant.*
