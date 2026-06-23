# Show HN: agent-seal — Tamper-proof audit trail for AI agents, zero-code integration

Hi HN,

I built an open-source audit trail system for AI agents. It records every decision, tool call, and model request into a SHA-256 hash-chained log that can't be tampered with without detection. Three lines to integrate, EU AI Act Article 12 ready.

## Why this exists

EU AI Act Article 12 ("Record-keeping") takes effect August 2, 2026. It requires all high-risk AI systems to maintain automatic, tamper-proof logs of every decision — with cryptographic integrity verification and export capability for regulators.

Existing options: SaaS subscriptions (your audit data on their cloud — compliance teams hate this), enterprise products (six-figure quotes), or nothing at all for open-source.

So I built one. MIT license, Python 3.11+, `pip install` and go.

## Three integration paths (pick what fits your stack)

**1. Zero-Code Global Hook**

No code changes. Install, start the server, and every Python process on the machine is automatically traced:

```bash
pip install agent-seal
agent-seal serve
# Dashboard at http://localhost:8081 — all LLM calls auto-appear
```

A `sitecustomize.py` global hook intercepts `httpx`-based LLM API calls (OpenAI, Anthropic, any OpenAI-compatible endpoint) in every Python process. Works with FastAPI, Celery workers, Jupyter notebooks, CLI scripts — anything that imports `openai` or `anthropic`.

**2. @observe Decorator**

Trace any Python function with one decorator. Inputs, outputs, latency, and nested call trees are recorded:

```python
from agent_seal import observe, set_engine
from agent_seal.engine import AuditEngine

engine = AuditEngine("sqlite://audit.db")
set_engine(engine)

@observe(name="process_refund", metadata={"tier": "critical"})
def process_refund(order_id: str, amount: float) -> dict:
    user = lookup_user(order_id)
    result = issue_refund(user, amount)
    return result

@observe(name="lookup_user")
def lookup_user(order_id: str) -> dict: ...

@observe(name="issue_refund")
def issue_refund(user: dict, amount: float) -> dict: ...
```

Three events auto-generated, nested calls linked via `parent_span_id`.

**3. Framework Callbacks**

LangChain users — one line:

```python
from agent_seal.hooks.langchain import AuditCallbackHandler
handler = AuditCallbackHandler(agent_id="my-agent")
executor = AgentExecutor(agent=agent, tools=tools, callbacks=[handler])
```

Hermes Agent framework users — zero-config native middleware.

## How it actually prevents tampering

Claims of "tamper-proof" need to be verifiable, not aspirational. Here's the crypto:

- **SHA-256 hash chain**: Each event = `SHA-256(previous_hash + event_content)`. Tamper with one byte and the entire chain fails verification. You run `agent-seal verify` and get a mathematical yes/no — no trust required.
- **Ed25519 digital signatures**: Optional per-event cryptographic non-repudiation. Auditor can independently verify signatures without accessing your system.
- **AES-256-GCM encryption**: Transparent encryption at rest. Compromised database = encrypted bytes.
- **PII redaction**: Automatic scrubbing of emails, phones, SSNs, credit card numbers before storage.

## Beyond logging: governance and compliance

- **Policy Engine**: YAML-based guardrail rules that block dangerous operations (`rm -rf /`, `DROP TABLE`, API key leaks) before execution
- **Evidence Bundles**: One-command `.zip` export with SHA-256 verification — hand it to an auditor, they verify independently
- **EU AI Act Reports**: `agent-seal report <agent>` generates Article 12 compliance report
- **Prompt Versioning**: Git-like prompt history with diffs — tracks who changed what, when, and why
- **Prometheus Metrics**: `GET /metrics` with `audit_events_total`, `audit_sessions_active`, `audit_policy_denials_total`
- **Slack + Email Alerts**: Policy blocks, integrity failures, error spikes
- **SPA Dashboard**: Real-time SSE event stream, expandable details, model/latency columns

## Storage: dev to production

| Backend | Use Case | Dependency |
|---------|----------|------------|
| JSONL | Local dev, prototyping | Zero |
| SQLite | Small-scale, single-server | Standard library |
| PostgreSQL | Production, concurrent-safe | psycopg2 + Alembic |

One env var switches backends: `AGENT_SEAL_DB_URL`.

## Deployment

```bash
cp .env.example .env
docker compose up -d
# nginx → FastAPI → PostgreSQL 15 + Redis
# SPA dashboard, API docs at /docs, Prometheus /metrics
```

## Code quality

- 172 tests, all green (pytest)
- ruff zero warnings, mypy clean
- Python 3.11 / 3.12 / 3.13
- FastAPI auto-generated OpenAPI docs

## Tech stack

Python 3.11+, FastAPI, SQLAlchemy, Alembic, cryptography, Prometheus, SSE streaming, Docker multi-stage build.

## What's next

The core audit chain, signatures, encryption, policy engine, and compliance reports are production-ready (we dogfood it in our own Hermes Agent workstation). Near-term roadmap: S3 evidence store, Grafana dashboard templates, OpenTelemetry spans.

---

**GitHub: [https://github.com/houxudong1997/agent-seal](https://github.com/houxudong1997/agent-seal)**

MIT license. Stars, issues, and PRs welcome.
