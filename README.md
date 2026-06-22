# agent-audit

**Tamper-proof audit trail for AI agents** — three-line integration (zero-code hook, `@observe` decorator, or framework callback). EU AI Act Article 12 ready.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-blue)](https://pypi.org/project/agent-audit/)

agent-audit records every decision, tool call, and model request an AI agent makes into an immutable, SHA-256 hash-chained log. Each event is cryptographically linked to the previous one — tamper with a single byte and the entire chain breaks, detected instantly on verification. Designed for **EU AI Act Article 12** (record-keeping, effective August 2026), SOC 2, and HIPAA audit requirements.

---

## Integration Methods 🆕

agent-audit v1.1 offers three integration paths — from zero-code to deep framework hooks. Pick the one that fits your stack.

| Method | Code Required | What It Captures | Best For |
|--------|:------------:|------------------|----------|
| **Zero-code hook** | None | All LLM calls in every Python process | Existing apps, no-code compliance |
| **`@observe` decorator** | 1 import + 1 line | Any Python function (inputs, outputs, latency) | Precise function-level tracing |
| **Framework callbacks** | 1 import + 1 line | LangChain LCEL / Hermes Agent actions | LangChain & Hermes users |

---

## Quick Start

### 1. Zero-Code (Global Hook) 🆕

Install agent-audit and start the server. Every Python process on the machine is automatically traced — no code changes.

```bash
pip install agent-audit
agent-audit server
# Dashboard at http://localhost:8081 — all LLM calls appear automatically
```

The global `sitecustomize.py` hook intercepts `httpx`-based LLM calls (OpenAI, Anthropic, and any OpenAI-compatible API) in every Python process. Works with frameworks, scripts, notebooks — anything that imports `openai` or `anthropic`.

### 2. @observe Decorator 🆕

Trace any Python function with one decorator. Inputs, outputs, execution time, and nested call trees are recorded into the audit trail.

```python
from agent_audit import observe, set_engine
from agent_audit.engine import AuditEngine

engine = AuditEngine("sqlite://audit.db")
set_engine(engine)

@observe(name="process_refund", metadata={"tier": "critical"})
def process_refund(order_id: str, amount: float) -> dict:
    user = lookup_user(order_id)
    result = issue_refund(user, amount)
    return result

# Nested calls are auto-linked as parent-child spans
@observe(name="lookup_user")
def lookup_user(order_id: str) -> dict: ...

@observe(name="issue_refund")
def issue_refund(user: dict, amount: float) -> dict: ...

process_refund("ORD-123", 45.00)
# → 3 audit events: process_refund → lookup_user, process_refund → issue_refund
#   with parent_span_id linking inner calls to outer
```

### 3. LangChain Callback 🆕

One line registers a callback handler that audits every LLM call, tool invocation, chain step, and agent decision.

```python
from agent_audit.hooks.langchain import LangChainAuditHandler

handler = LangChainAuditHandler(agent_id="my-agent")

from langchain.agents import AgentExecutor
executor = AgentExecutor(agent=agent, tools=tools, callbacks=[handler])
```

| Callback | Event Type |
|----------|-----------|
| `on_llm_start/end` | `model_request` |
| `on_tool_start/end` | `tool_call` |
| `on_chain_start/end` | `chain_step` |
| `on_agent_action/finish` | `decision` |

Token counts, latency, model name, and errors are captured automatically.

### 4. Hermes Middleware 🆕

Native support for the [Hermes Agent](https://hermes-agent.nousresearch.com/docs) framework. Zero-config — install and it auto-instruments all agent actions.

```python
# hermes_middleware.py is auto-detected
# No code changes needed in your Hermes agent
```

> **Note**: `langchain` and `langchain-core` are optional dependencies. Install them separately: `pip install langchain langchain-core`. When unavailable, the module imports cleanly but raises a friendly `RuntimeError` with install instructions.

---

## Key Features

### Core Audit Trail

- **Immutable Hash Chain** — SHA-256 chain linking every event. Break one link = tampering detected.
- **Ed25519 Digital Signatures** — Cryptographic non-repudiation per event.
- **AES-256-GCM Encryption** — Transparent encryption at rest.
- **PII Redaction** — Automatic PII scrubbing (emails, phones, SSNs, credit cards) before storage.

### v1.1 Highlights 🆕

- **🆕 Zero-Code Global Hook** — `sitecustomize.py` auto-instruments all Python processes. No imports, no decorators, no config.
- **🆕 @observe Decorator** — Lightweight function tracing with nested span trees, latency, and custom metadata.
- **🆕 LangChain CallbackHandler** — Native `LangChainAuditHandler` for LCEL chains, agents, and tools.
- **🆕 Hermes Middleware** — First-class Hermes Agent framework integration.
- **🆕 Enhanced SPA Dashboard** — Expandable event details, smart previews, model/latency columns, binary output filtering.

### Governance & Compliance

- **Policy Engine** — YAML-based guardrail rules. Block dangerous tool calls before execution.
- **Evidence Bundles** — Export signed `.zip` bundles for external auditors with SHA-256 verification.
- **EU AI Act Reports** — Generate Article 12 compliance reports on demand (`agent-audit report <agent>`).
- **Prompt Version Tracking** — Git-like prompt history with diffs — who changed what, when, and why.

### Observability

- **LLM Auto-Tracing** — Monkey-patch instrumentation for OpenAI, Anthropic, OpenTelemetry. Token counts, latency, cost.
- **Prometheus Metrics** — `GET /metrics` exporting `audit_events_total`, `audit_sessions_active`, `audit_policy_denials_total`.
- **Slack + Email Alerts** — Notifications for policy blocks, integrity failures, error spikes.

### Storage

- **JSONL** — Zero-dependency file backend for development.
- **SQLite** — Single-file embedded database for small-scale deployments.
- **PostgreSQL** — Production-grade concurrent-safe storage with connection pooling and Alembic migrations.

---

## Installation

```bash
pip install agent-audit
```

With PostgreSQL support:

```bash
pip install agent-audit[postgresql]
```

Or everything:

```bash
pip install agent-audit[all]
```

### From source

```bash
git clone https://github.com/user/agent-audit.git
cd agent-audit
pip install -e .
```

---

## Dashboard 🆕

> 📸 **Screenshot placeholder** — Dashboard screenshot coming soon.

The SPA Dashboard provides real-time visibility into your audit trail:

- **Event list** with expandable detail rows — inputs, outputs, metadata
- **Smart previews** — truncated long content with "Show more"
- **Model & latency columns** — at-a-glance performance monitoring
- **Binary/garbled output filtering** — clean display of structured data
- **SSE live updates** — new events stream in real time, no page refresh

Start the dashboard: `agent-audit server` → open `http://localhost:8081`

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      INTEGRATION LAYER                        │
│                                                              │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │  Zero-Code Hook  │  │  @observe    │  │ Framework Hooks  │ │
│  │  (sitecustomize) │  │  (decorator) │  │ (LangChain/Hermes)│ │
│  │                 │  │              │  │                  │ │
│  │  Auto-intercept  │  │  Manual trace│  │  Native callback │ │
│  │  all LLM calls   │  │  any function│  │  integration     │ │
│  └────────┬────────┘  └──────┬───────┘  └────────┬─────────┘ │
│           │                  │                    │           │
└───────────┼──────────────────┼────────────────────┼───────────┘
            │                  │                    │
            ▼                  ▼                    ▼
┌──────────────────────────────────────────────────────────────┐
│                      AUDIT ENGINE                             │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │Hash Chain│  │ Ed25519  │  │AES-256-GCM│  │ PII Redact   │ │
│  │ SHA-256  │  │Signatures│  │Encryption │  │              │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘ │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Storage Backends                         │    │
│  │     JSONL (dev)  │  SQLite (small)  │  PostgreSQL     │    │
│  └──────────────────────────────────────────────────────┘    │
└───────────────────────────┬──────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
   ┌────────────┐  ┌──────────────┐  ┌──────────────┐
   │  REST API  │  │SPA Dashboard │  │  Prometheus   │
   │  /api/v1/* │  │  :8081       │  │  /metrics     │
   └────────────┘  └──────────────┘  └──────────────┘
```

```
agent_audit/
├── trail.py              # Hash-chained audit trail (entry point)
├── engine.py             # Unified AuditEngine (JSONL/SQLite/PG)
├── observe.py            # @observe decorator 🆕
├── config.py             # 12-Factor configuration
├── cli.py                # CLI commands
├── core/
│   ├── chain.py          # SessionChain — per-session hash chains
│   ├── storage.py        # Storage backends (JSONL, SQLite, PostgreSQL)
│   ├── crypto.py         # Ed25519 signing
│   ├── encrypted.py      # AES-256-GCM encryption
│   ├── redact.py         # PII redaction
│   └── rotation.py       # Log rotation
├── server/
│   ├── app.py            # FastAPI application
│   ├── hermes_middleware.py  # Hermes Agent middleware 🆕
│   └── routes/           # REST endpoints
├── policy/engine.py      # YAML-based guardrail rules
├── tracing/              # LLM auto-instrumentation (OpenAI, Anthropic, OTel)
├── hooks/
│   ├── langchain.py      # LangChain CallbackHandler 🆕
│   ├── hermes_worker.py  # Hermes worker hook 🆕
│   ├── slack.py          # Slack notifications
│   └── email.py          # Email alerts
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

## CLI Reference

```bash
agent-audit <command> [options]
```

| Command   | Description                                    |
|-----------|------------------------------------------------|
| `server`  | Start API server + SPA Dashboard               |
| `verify`  | Check audit trail integrity (hash chain)       |
| `trail`   | Show recent events and statistics              |
| `report`  | Generate EU AI Act Article 12 compliance report|
| `log`     | Record a test event                            |
| `prompt`  | Manage prompt versions (list, diff, audit)     |

---

## REST API

Start the server:

```bash
agent-audit server
# OR: uvicorn agent_audit.server.app:app --host 0.0.0.0 --port 8081
```

Endpoints:

| Method | Path                            | Description                    |
|--------|---------------------------------|--------------------------------|
| GET    | `/health`                       | Health check                   |
| POST   | `/api/v1/log`                   | Append an audit event          |
| GET    | `/api/v1/events`                | Query events (filter + search) |
| GET    | `/api/v1/events/stream`         | SSE real-time event stream     |
| POST   | `/api/v1/verify`                | Verify chain integrity         |
| POST   | `/api/v1/compliance/report`     | Generate EU AI Act report      |
| GET    | `/api/v1/compliance/report/{id}`| Retrieve cached report         |
| GET    | `/api/v1/stats`                 | Aggregate statistics           |
| GET    | `/api/v1/sessions`              | List audit sessions            |
| GET    | `/metrics`                      | Prometheus metrics             |

---

## Configuration

All settings via environment variables (12-Factor App). See `.env.example` for a complete template.

| Variable                          | Default           | Description                             |
|-----------------------------------|-------------------|-----------------------------------------|
| `AGENT_AUDIT_DB_URL`              | _(auto-detect)_   | PostgreSQL / SQLite connection string   |
| `AGENT_AUDIT_SECRET_KEY`          | _(none)_          | HMAC secret for internal tokens         |
| `AGENT_AUDIT_STORAGE_BACKEND`     | `auto`            | `jsonl` / `sqlite` / `postgresql`       |
| `AGENT_AUDIT_AUDIT_DIR`           | `./audit_logs`    | Local directory for JSONL/SQLite        |
| `AGENT_AUDIT_API_HOST`            | `0.0.0.0`         | API bind address                        |
| `AGENT_AUDIT_API_PORT`            | `8081`            | API port                                |
| `AGENT_AUDIT_API_KEYS`            | _(none)_          | Comma-separated API keys                |
| `AGENT_AUDIT_CORS_ORIGINS`        | _(none)_          | Comma-separated allowed origins         |
| `AGENT_AUDIT_SIGNING_KEY`         | _(none)_          | Ed25519 private key for signing         |
| `AGENT_AUDIT_ENCRYPTION_KEY`      | _(none)_          | AES-256-GCM encryption key              |
| `AGENT_AUDIT_AUTO_TRACE`          | `0`               | Auto-trace LLM calls (`1`=on)           |
| `AGENT_AUDIT_TRACE_PII_REDACT`    | `0`               | Redact PII in traces (`1`=on)           |
| `AGENT_AUDIT_LOG_LEVEL`           | `info`            | `debug`, `info`, `warning`              |
| `AGENT_AUDIT_REDIS_URI`           | _(none)_          | Redis connection for caching            |
| `AGENT_AUDIT_SLACK_WEBHOOK`       | _(none)_          | Slack notification webhook              |
| `AGENT_AUDIT_SMTP_HOST`           | _(none)_          | Email notification SMTP host            |
| `AGENT_AUDIT_NOTIFY_ON_FAILURE`   | `0`               | Notify on chain integrity failure       |
| `AGENT_AUDIT_EVIDENCE_STORE`      | _(none)_          | External evidence store path            |

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

## Development

### Quick Start

```bash
# Clone & install
git clone https://github.com/user/agent-audit.git && cd agent-audit
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

For local development with PostgreSQL, the project ships `pg_embedded/` — an embedded PostgreSQL 17.10 instance that runs on-demand. **This is a development tool, not for production.**

| Property   | Value                                         |
|------------|-----------------------------------------------|
| Version    | PostgreSQL 17.10                              |
| Port       | `5432` (bound to `127.0.0.1` / `::1` only)   |
| Database   | `agent_audit`                                 |
| User       | `audit` (trust auth — local only)             |
| Disk usage | ~942 MB (data + binaries)                     |
| Git tracked| No (`.gitignore`d)                            |

**Security note**: The embedded PostgreSQL uses `trust` authentication and listens on `127.0.0.1`/`::1` only — no external network access. For production, use the Docker Compose stack which configures proper authentication.

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

> **Why embedded?** Avoids Docker/brew/system-PG dependency for quick local testing. **Why stop it?** 942 MB never-idle memory. Start it only when you need PG, stop it when you don't. For always-on development, prefer `docker compose up -d db`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
