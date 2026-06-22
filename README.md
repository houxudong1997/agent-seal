# agent-audit

Tamper-evident audit trail for AI agents — **EU AI Act ready**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-blue)](https://pypi.org/project/agent-audit/)

**agent-audit** records every decision, tool call, and model request an AI agent makes into an immutable, SHA-256 hash-chained log. Each event is cryptographically linked to the previous one — tamper with a single byte and the entire chain breaks, detected instantly on verification.

Designed for **EU AI Act Article 12** (record-keeping, effective August 2026), SOC 2, and HIPAA audit requirements.

---

## Key Features

- **Immutable Hash Chain** — Every event links to its predecessor via SHA-256. Chain breaks = tampering detected.
- **Ed25519 Digital Signatures** — Each record can be cryptographically signed for non-repudiation.
- **AES-256-GCM Encryption** — Encrypt sensitive audit data at rest.
- **PII Redaction** — Automatic PII scrubbing before storage.
- **Prompt Version Tracking** — Full audit trail of prompt changes with diffs.
- **Policy Engine** — YAML-based rules to block dangerous tool calls before execution.
- **Evidence Bundles** — Export signed `.zip` bundles for external auditors.
- **LLM Tracing** — Auto-instrument OpenAI, Anthropic, and OpenTelemetry clients.
- **EU AI Act Compliance Reports** — Generate markdown compliance reports on demand.
- **Multiple Backends** — JSONL (dev), SQLite (small-scale), PostgreSQL (production).
- **CLI + REST API + SPA Dashboard** — Command-line, HTTP API, and web UI.

---

## Installation

```bash
pip install agent-audit
```

With PostgreSQL support:

```bash
pip install agent-audit[postgresql]
```

Or install everything:

```bash
pip install agent-audit[all]
```

### From source

```bash
git clone <repo-url>
cd agent-audit
pip install -e .
```

---

## Quick Start

```python
from agent_audit.trail import AuditTrail

# Create an audit trail
trail = AuditTrail("./logs/my-agent")

# Log agent activity
trail.log(
    session_id="sess-001",
    event_type="decision",
    agent_id="refund-bot",
    input_snapshot="User: I want a refund for $45",
    output_snapshot="Approved: $45 refund — within $100 limit",
)

# Each event is hash-chained to the previous one
trail.log(
    session_id="sess-001",
    event_type="tool_call",
    agent_id="refund-bot",
    input_snapshot="Execute refund",
    output_snapshot="CALL: stripe.refund(ch_789, amount=45)",
)

# Verify integrity
trail.verify()  # ✅ Chain intact — no tampering detected
```

### Generate an EU AI Act compliance report

```bash
agent-audit report refund-bot --output compliance-2026.md
```

---

## CLI Reference

```bash
agent-audit <command> [options]
```

| Command     | Description                                |
|-------------|--------------------------------------------|
| `verify`    | Check audit trail integrity (hash chain)   |
| `trail`     | Show recent events and statistics          |
| `report`    | Generate EU AI Act Article 12 compliance report |
| `log`       | Record a test event                        |
| `prompt`    | Manage prompt versions (list, diff, audit) |

---

## REST API

Start the server:

```bash
agent-audit server
# OR: uvicorn agent_audit.server.app:app --host 0.0.0.0 --port 8081
```

Endpoints:

| Method | Path                              | Description                    |
|--------|-----------------------------------|--------------------------------|
| GET    | `/health`                         | Health check                   |
| POST   | `/api/v1/log`                     | Append an audit event          |
| GET    | `/api/v1/events`                  | Query events (filter + search) |
| POST   | `/api/v1/verify`                  | Verify chain integrity         |
| POST   | `/api/v1/compliance/report`       | Generate EU AI Act report      |
| GET    | `/api/v1/compliance/report/{id}`  | Retrieve cached report         |
| GET    | `/metrics`                        | Prometheus metrics             |
| GET    | `/api/v1/stats`                   | Aggregate statistics           |

---

## Docker Deployment

```bash
# 1. Copy and configure environment
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, AGENT_AUDIT_SECRET_KEY, API keys

# 2. Start the stack
docker compose up -d

# 3. Verify
curl http://localhost/health
```

The stack includes:
- **nginx** — Reverse proxy (port 80/443) + SPA static files
- **api** — FastAPI application server (internal port 8081)
- **db** — PostgreSQL 15 (audit data + prompt versions)
- **redis** — Caching, rate limiting (optional)

---

## Configuration

All settings via environment variables (12-Factor App). See `.env.example` for a complete template.

| Variable                        | Default              | Description                            |
|---------------------------------|----------------------|----------------------------------------|
| `AGENT_AUDIT_DB_URL`            | _(auto-detect)_      | PostgreSQL / SQLite connection string  |
| `AGENT_AUDIT_SECRET_KEY`        | _(none)_             | HMAC secret for internal tokens        |
| `AGENT_AUDIT_STORAGE_BACKEND`   | `auto`               | `jsonl` / `sqlite` / `postgresql`      |
| `AGENT_AUDIT_AUDIT_DIR`         | `./audit_logs`       | Local directory for JSONL/SQLite       |
| `AGENT_AUDIT_API_HOST`          | `0.0.0.0`            | API bind address                       |
| `AGENT_AUDIT_API_PORT`          | `8081`               | API port                               |
| `AGENT_AUDIT_API_KEYS`          | _(none)_             | Comma-separated API keys               |
| `AGENT_AUDIT_CORS_ORIGINS`      | _(none)_             | Comma-separated allowed origins        |
| `AGENT_AUDIT_SIGNING_KEY`       | _(none)_             | Ed25519 private key for signing        |
| `AGENT_AUDIT_SIGNING_KEY_PASSWORD` | _(none)_           | Password for encrypted signing key     |
| `AGENT_AUDIT_ENCRYPTION_KEY`    | _(none)_             | AES-256-GCM encryption key             |
| `AGENT_AUDIT_LOG_LEVEL`         | `info`               | Log level (`debug`, `info`, `warning`) |
| `AGENT_AUDIT_LOG_FORMAT`        | `text`               | `text` or `json`                       |
| `AGENT_AUDIT_AUTO_TRACE`        | `0`                  | Auto-trace LLM calls (`1`=on)          |
| `AGENT_AUDIT_TRACE_PII_REDACT`  | `0`                  | Redact PII in traces (`1`=on)          |
| `AGENT_AUDIT_TRACE_MAX_LEN`     | `4000`               | Max characters per trace entry         |
| `AGENT_AUDIT_TRACE_COST_MODEL`  | `openai`             | Cost tracking model                    |
| `AGENT_AUDIT_REDIS_URI`         | _(none)_             | Redis connection for caching           |
| `AGENT_AUDIT_SLACK_WEBHOOK`     | _(none)_             | Slack notification webhook             |
| `AGENT_AUDIT_SMTP_HOST`         | _(none)_             | Email notification SMTP host           |
| `AGENT_AUDIT_NOTIFY_ON_FAILURE` | `0`                  | Notify on chain integrity failure      |
| `AGENT_AUDIT_EVIDENCE_STORE`    | _(none)_             | External evidence store path           |

---

## Architecture

```
agent_audit/
├── trail.py              # Hash-chained audit trail (entry point)
├── engine.py             # Unified AuditEngine (JSONL/SQLite/PG)
├── config.py             # 12-Factor configuration
├── cli.py                # CLI commands
├── core/
│   ├── chain.py          # SessionChain — per-session hash chains
│   ├── storage.py        # Storage backends (JSONL, SQLite, PostgreSQL)
│   ├── crypto.py         # Ed25519 signing
│   ├── encrypted.py      # AES-256-GCM encryption
│   ├── redact.py         # PII redaction
│   └── rotation.py       # Log rotation
├── server/               # FastAPI REST API + SPA
├── policy/engine.py      # YAML policy engine
├── tracing/              # LLM auto-instrumentation (OpenAI, Anthropic, OTel)
├── hooks/                # Notification hooks (Slack, Email)
├── integrations/         # LangChain, MCP server adapters
├── models/               # SQLAlchemy models
├── evidence.py           # Evidence bundle export
├── report.py             # EU AI Act compliance reports
├── prompt_version.py     # Prompt version tracking
├── replay.py             # Trail replay
└── regression.py         # Regression testing
```

For detailed architecture see [docs/architecture-v1.md](docs/architecture-v1.md).

---

## Development

### Quick Start

```bash
# Clone & install
git clone <repo-url> && cd agent-audit
pip install -e ".[all]"

# Run tests
pytest tests/ -v

# Code quality
ruff check .
mypy agent_audit/

# Run demo
python examples/demo.py
```

### Embedded PostgreSQL (development only)

For local development with PostgreSQL, the project ships `pg_embedded/` — an embedded
PostgreSQL 17.10 instance that runs on-demand. **This is a development tool, not for production.**

| Property    | Value                                      |
|-------------|--------------------------------------------|
| Version     | PostgreSQL 17.10                           |
| Port        | `5432` (bound to `127.0.0.1` / `::1` only) |
| Database    | `agent_audit`                              |
| User        | `audit` (trust auth — local only)          |
| Disk usage  | ~942 MB (data + binaries)                  |
| Git tracked | No (`.gitignore`d)                         |

**Security note**: The embedded PostgreSQL uses `trust` authentication and listens on
`127.0.0.1`/`::1` only — no external network access. For production, use the Docker
Compose stack which configures proper authentication.

```bash
# One-time initialization (creates data/ directory and database)
pg_embedded/init.bat

# Start on demand
pg_embedded/start.bat

# Stop when done
pg_embedded/stop.bat
```

Configure via `.env`:

```bash
AGENT_AUDIT_DB_URL=postgresql://audit:***@127.0.0.1:5432/agent_audit
AGENT_AUDIT_STORAGE_BACKEND=postgresql
```

> **Why embedded?** Avoids Docker/brew/system-PG dependency for quick local testing.
> **Why stop it?** 942 MB never-idle memory. Start it only when you need PG, stop it
> when you don't. For always-on development, prefer `docker compose up -d db`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
