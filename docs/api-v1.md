# agent-audit REST API v1.0

> Complete reference for the agent-audit REST API. Base URL: `http://localhost:8081`

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Authentication](#2-authentication)
3. [Health & Readiness](#3-health--readiness)
   - `GET /health`
   - `GET /ready`
4. [Observability](#4-observability)
   - `GET /metrics`
   - `GET /api/v1/stats`
5. [Event Logging](#5-event-logging)
   - `POST /api/v1/log`
   - `GET /api/v1/events`
   - `GET /api/v1/events/stream` (SSE)
6. [Session Management](#6-session-management)
   - `GET /api/v1/sessions`
   - `GET /api/v1/sessions/{session_id}`
7. [Integrity Verification](#7-integrity-verification)
   - `POST /api/v1/verify`
8. [LLM Tracing](#8-llm-tracing)
   - `GET /api/v1/llm/stats`
   - `GET /api/v1/llm/status`
   - `POST /api/v1/llm/enable`
   - `POST /api/v1/llm/disable`
   - `POST /api/v1/llm/log`
   - `GET /api/v1/llm/traces/{trace_id}`
9. [Compliance](#9-compliance)
   - `POST /api/v1/compliance/report`
   - `GET /api/v1/compliance/report/{agent_id}`
10. [Evidence Export](#10-evidence-export)
    - `POST /api/v1/evidence/export`
11. [Admin](#11-admin)
    - `GET /api/v1/admin/status`
12. [Dashboard & Static Assets](#12-dashboard--static-assets)
    - `GET /`
13. [Legacy Endpoints](#13-legacy-endpoints)
14. [Error Codes](#14-error-codes)
15. [Event Types Reference](#15-event-types-reference)

---

## 1. Quick Start

```bash
# Start the server
agent-audit serve

# Or with uvicorn directly
uvicorn agent_audit.server.app:app --host 0.0.0.0 --port 8081

# Interactive API docs
open http://localhost:8081/docs
```

All API responses are JSON unless noted otherwise. The FastAPI server also serves an interactive OpenAPI docs page at `/docs`.

---

## 2. Authentication

Bearer token authentication via the `Authorization` header. Configured via `AGENT_AUDIT_API_KEYS` in `.env`.

**If no API keys are configured, the API is open access** (dev mode).


**Configuration**:

```bash
# .env — comma-separated Bearer tokens
AGENT_AUDIT_API_KEYS=prod-key-abc123,prod-key-def456

# Empty = open access (dev only)
AGENT_AUDIT_API_KEYS=
```

**Authenticated request**:

```bash
curl -H "Authorization: Bearer ***" http://localhost:8081/api/v1/log
```

**Unauthorized response** (`401 Unauthorized`):

```json
{"detail": "Not authenticated"}
```

> **Note**: The legacy HTTP server (`api.py`) returns `{"error": "unauthorized"}` with `401`. The FastAPI server returns `{"detail": "Not authenticated"}` with `401`. Both use the same `AGENT_AUDIT_API_KEYS` config.

---

## 3. Health & Readiness

### `GET /health`

Health check. Always returns 200 if the server is running.

**Request**:

```bash
curl http://localhost:8081/health
```

**Response** `200 OK`:

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

No authentication required.

---

### `GET /ready`

Readiness probe. Returns 200 if the storage backend is accessible, 503 if not.

**Request**:

```bash
curl http://localhost:8081/ready
```

**Response** `200 OK`:

```json
{"status": "ready"}
```

**Response** `503 Service Unavailable`:

```json
{"status": "not_ready", "error": "unable to open database file"}
```

No authentication required.

---

## 4. Observability

### `GET /metrics`

Prometheus-format metrics. Suitable for scraping by Prometheus/Grafana.

**Request**:

```bash
curl http://localhost:8081/metrics
```

**Response** `200 OK` (text/plain):

```
# HELP audit_events_total Total number of audit events recorded
# TYPE audit_events_total counter
audit_events_total 42

# HELP audit_sessions_active Number of tracked sessions
# TYPE audit_sessions_active gauge
audit_sessions_active 3

# HELP audit_uptime_seconds Seconds since agent-audit started
# TYPE audit_uptime_seconds gauge
audit_uptime_seconds 378

# HELP audit_policy_denials_total Policy denials counter
# TYPE audit_policy_denials_total counter
audit_policy_denials_total 5

# HELP audit_policy_approvals_total Approval requests counter
# TYPE audit_policy_approvals_total counter
audit_policy_approvals_total 0

# HELP audit_verify_checks_total Integrity verification runs
# TYPE audit_verify_checks_total counter
audit_verify_checks_total 10

# HELP audit_storage_bytes Estimated storage size
# TYPE audit_storage_bytes gauge
audit_storage_bytes 0
```

**Metrics**:

| Metric | Type | Description |
|---|---|---|
| `audit_events_total` | counter | Total audit events recorded |
| `audit_sessions_active` | gauge | Number of tracked sessions |
| `audit_uptime_seconds` | gauge | Seconds since server start |
| `audit_policy_denials_total` | counter | Policy engine denials |
| `audit_policy_approvals_total` | counter | Approval requests made |
| `audit_verify_checks_total` | counter | Integrity verification runs |
| `audit_storage_bytes` | gauge | Estimated storage size |

---

### `GET /api/v1/stats`

Aggregate audit trail statistics.

**Request**:

```bash
curl http://localhost:8081/api/v1/stats
```

**Response** `200 OK`:

```json
{
  "total_events": 42,
  "sessions": 3,
  "event_types": {
    "decision": 20,
    "tool_call": 12,
    "model_request": 8,
    "guardrail": 2
  },
  "integrity": "ok",
  "agents": ["refund-bot", "support-bot"]
}
```

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `total_events` | int | Total number of audit events |
| `sessions` | int | Number of tracked sessions |
| `event_types` | object | Count per event type (`{"decision": N, ...}`) |
| `integrity` | string | Overall chain integrity: `"ok"`, `"broken"`, or `"unknown"` |
| `agents` | array | List of known agent IDs |

---

## 5. Event Logging

### `POST /api/v1/log`

Record a new audit event. The event is appended to its session's SHA-256 hash chain and persisted to the storage backend.

**Authentication**: Required if `AGENT_AUDIT_API_KEYS` is set.

**Request**:

```bash
curl -X POST http://localhost:8081/api/v1/log \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{
    "session_id": "customer-12345",
    "event_type": "decision",
    "agent_id": "refund-bot",
    "prompt_version": "v3",
    "input": "User: refund $45 for order #12345",
    "output": "Approved: amount=$45, within v3 $500 limit",
    "metadata": {"order_id": "12345", "region": "eu-west"}
  }'
```

**Request Body**:

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `session_id` | string | No | `"default"` | Session identifier — groups related events |
| `event_type` | string | No | `"unknown"` | Event category: see [§15 Event Types](#15-event-types-reference) |
| `agent_id` | string | No | `"unknown"` | Agent identifier |
| `prompt_version` | string | No | `"v1"` | Prompt version used for this event |
| `input` | string | No | `""` | Input to the agent (truncated at 8000 chars) |
| `output` | string | No | `""` | Output from the agent (truncated at 8000 chars) |
| `metadata` | object | No | `{}` | Arbitrary JSON metadata |

**Response** `200 OK`:

```json
{
  "event_id": "a1b2c3d4e5f6",
  "hash": "3f8a9b0c1d2e4f5a6b7c8d9e0f1a2b3c",
  "session_id": "customer-12345",
  "sequence": 0,
  "timestamp": 1719001234.567,
  "event_type": "decision",
  "agent_id": "refund-bot",
  "prompt_version": "v3"
}
```

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `event_id` | string | Unique event ID (12-char UUID prefix) |
| `hash` | string | SHA-256 hash (first 16 chars) |
| `session_id` | string | Session ID |
| `sequence` | int | Position in the session's chain (0-indexed) |
| `timestamp` | float | Unix timestamp |
| `event_type` | string | Event type |
| `agent_id` | string | Agent ID |
| `prompt_version` | string | Prompt version |

**Side effect**: If SSE listeners are connected, the new event is pushed to all `/api/v1/events/stream` connections in real time.

**Error responses**:

| Status | Body | Condition |
|---|---|---|
| `400` | `{"error": "invalid JSON"}` | Request body is not valid JSON |
| `401` | `{"detail": "Not authenticated"}` | Missing or invalid Bearer token |

---

### `GET /api/v1/events`

Query audit events with optional filters. Paginated.

**Request**:

```bash
# All events (first 50)
curl "http://localhost:8081/api/v1/events"

# Filtered and paginated
curl "http://localhost:8081/api/v1/events?session_id=customer-12345&event_type=decision&limit=10&offset=0"
```

**Query Parameters**:

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `session_id` | string | No | — | Filter by session ID |
| `event_type` | string | No | — | Filter by event type |
| `limit` | int | No | `50` | Max events per page (1–500) |
| `offset` | int | No | `0` | Pagination offset (0-indexed) |

**Response** `200 OK`:

```json
{
  "events": [
    {
      "event_id": "a1b2c3d4e5f6",
      "session_id": "customer-12345",
      "sequence": 0,
      "timestamp": 1719001234.567,
      "event_type": "decision",
      "agent_id": "refund-bot",
      "prompt_version": "v3",
      "input_snapshot": "User: refund $45 for order #12345",
      "output_snapshot": "Approved: amount=$45, within v3 $500 limit",
      "metadata": {"order_id": "12345"},
      "prev_hash": "",
      "hash": "3f8a9b0c1d2e4f5a6b7c8d9e0f1a2b3c"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `events` | array | Array of event objects (see [§15 Event Types](#15-event-types-reference)) |
| `total` | int | Total matching events (before pagination) |
| `limit` | int | Page size |
| `offset` | int | Current offset |

---

### `GET /api/v1/events/stream`

**Server-Sent Events (SSE)**. Real-time event stream — pushes new events to connected clients as they are logged.

**Request**:

```bash
curl -N "http://localhost:8081/api/v1/events/stream"
```

**Stream events**:

| Event | Data | Description |
|---|---|---|
| `connected` | `{"message": "Stream connected"}` | Sent on initial connection |
| `new_event` | JSON event object | Pushed when a new event is logged via `POST /api/v1/log` |
| `ping` | `""` (empty) | Keepalive every 15 seconds |

**Example stream**:

```
event: connected
data: {"message": "Stream connected"}

event: ping
data:

event: new_event
data: {"event_id":"a1b2c3d4e5f6","hash":"3f8a9b0c...","session_id":"customer-12345","sequence":0,"timestamp":1719001234.567,"event_type":"decision","agent_id":"refund-bot","prompt_version":"v3"}
```

**JavaScript client**:

```javascript
const source = new EventSource("http://localhost:8081/api/v1/events/stream");

source.addEventListener("new_event", (e) => {
  const event = JSON.parse(e.data);
  console.log("New event:", event);
});

source.addEventListener("ping", () => {
  // Keepalive — no action needed
});
```

> **Note**: SSE data is the same partial event object returned by `POST /api/v1/log` — it does not include `input_snapshot` or `output_snapshot`.

---

## 6. Session Management

### `GET /api/v1/sessions`

List all session IDs with summary statistics.

**Request**:

```bash
curl http://localhost:8081/api/v1/sessions
```

**Response** `200 OK`:

```json
{
  "sessions": [
    {
      "session_id": "customer-12345",
      "event_count": 5,
      "last_event_type": "decision",
      "last_timestamp": 1719001234.567,
      "agent_id": "refund-bot",
      "integrity": "ok"
    },
    {
      "session_id": "customer-67890",
      "event_count": 3,
      "last_event_type": "tool_call",
      "last_timestamp": 1719001111.222,
      "agent_id": "support-bot",
      "integrity": "ok"
    }
  ]
}
```

**Response fields per session**:

| Field | Type | Description |
|---|---|---|
| `session_id` | string | Session identifier |
| `event_count` | int | Number of events in this session |
| `last_event_type` | string | Type of the most recent event |
| `last_timestamp` | float | Timestamp of the most recent event |
| `agent_id` | string | Agent ID from the most recent event |
| `integrity` | string | `"ok"`, `"broken"`, or `"unknown"` |

---

### `GET /api/v1/sessions/{session_id}`

Full event list for a single session, including integrity status.

**Request**:

```bash
curl http://localhost:8081/api/v1/sessions/customer-12345
```

**Response** `200 OK`:

```json
{
  "session_id": "customer-12345",
  "event_count": 2,
  "integrity": "ok",
  "events": [
    {
      "event_id": "a1b2c3d4e5f6",
      "session_id": "customer-12345",
      "sequence": 0,
      "timestamp": 1719001234.567,
      "event_type": "decision",
      "agent_id": "refund-bot",
      "prompt_version": "v3",
      "input_snapshot": "User: refund $45",
      "output_snapshot": "Approved: $45",
      "metadata": {},
      "prev_hash": "",
      "hash": "3f8a9b0c..."
    },
    {
      "event_id": "b2c3d4e5f6a7",
      "session_id": "customer-12345",
      "sequence": 1,
      "timestamp": 1719001300.000,
      "event_type": "tool_call",
      "agent_id": "refund-bot",
      "prompt_version": "v3",
      "input_snapshot": "CALL: process_refund($45)",
      "output_snapshot": "SUCCESS: refund processed",
      "metadata": {},
      "prev_hash": "3f8a9b0c...",
      "hash": "4a9b0c1d..."
    }
  ]
}
```

**Response** `404 Not Found`:

```json
{"error": "session not found"}
```

---

## 7. Integrity Verification

### `POST /api/v1/verify`

Verify hash chain integrity — globally or for a specific session. Recomputes all SHA-256 hashes and checks that the chain links are intact.

**Global verification** (no body, or empty body):

```bash
curl -X POST http://localhost:8081/api/v1/verify \
  -H "Content-Type: application/json"
```

**Response** `200 OK`:

```json
{
  "integrity": "ok",
  "sessions": {
    "customer-12345": "ok",
    "customer-67890": "ok"
  }
}
```

**Per-session verification**:

```bash
curl -X POST http://localhost:8081/api/v1/verify \
  -H "Content-Type: application/json" \
  -d '{"session_id": "customer-12345"}'
```

**Response** `200 OK`:

```json
{
  "integrity": "ok",
  "session_id": "customer-12345"
}
```

**Integrity statuses**:

| Status | Meaning |
|---|---|
| `"ok"` | All hashes verified — chain is intact |
| `"broken"` | One or more events have been modified — hash mismatch detected |
| `"unknown"` | Error during verification (e.g., missing data, corrupt format) |

---

## 8. LLM Tracing

### `GET /api/v1/llm/stats`

Token usage and cost summary across all traced LLM calls.

**Request**:

```bash
curl http://localhost:8081/api/v1/llm/stats
```

**Response** `200 OK`:

```json
{
  "total_calls": 142,
  "total_tokens": 45800,
  "prompt_tokens": 28900,
  "completion_tokens": 16900,
  "total_cost_usd": 0.3572,
  "by_model": {
    "openai/gpt-4o": {"calls": 87, "tokens": 31200, "cost": 0.312},
    "anthropic/claude-sonnet-4": {"calls": 55, "tokens": 14600, "cost": 0.0452}
  },
  "avg_latency_ms": 342.5
}
```

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `total_calls` | int | Total number of traced LLM calls |
| `total_tokens` | int | Sum of all tokens (prompt + completion) |
| `prompt_tokens` | int | Total prompt/input tokens |
| `completion_tokens` | int | Total completion/output tokens |
| `total_cost_usd` | float | Total estimated cost in USD (6 decimal places) |
| `by_model` | object | Breakdown by model: calls, tokens, cost |
| `avg_latency_ms` | float | Average latency across all calls |

> **Note**: Cost estimates are per the pricing tables in `tracing/cost.py` for OpenAI, Anthropic, and DeepSeek models. Only available when `AGENT_AUDIT_AUTO_TRACE=1` is set.

---

### `GET /api/v1/llm/status`

Current LLM tracing status and configuration.

**Request**:

```bash
curl http://localhost:8081/api/v1/llm/status
```

**Response** `200 OK`:

```json
{
  "tracing": {
    "enabled": true,
    "pii_redaction": false,
    "auto_cost": true,
    "max_prompt_len": 4000,
    "cost_model": "openai",
    "capture_request": true,
    "capture_response": true
  },
  "env_config": {
    "AGENT_AUDIT_AUTO_TRACE": true,
    "AGENT_AUDIT_TRACE_PII_REDACT": false,
    "AGENT_AUDIT_TRACE_MAX_LEN": 4000,
    "AGENT_AUDIT_TRACE_COST_MODEL": "openai"
  }
}
```

---

### `POST /api/v1/llm/enable`

Enable LLM auto-tracing at runtime. Monkey-patches the OpenAI and Anthropic SDKs to intercept all LLM calls and log them to the audit trail.

**Request**:

```bash
curl -X POST http://localhost:8081/api/v1/llm/enable
```

**Response** `200 OK`:

```json
{"status": "ok", "message": "LLM tracing enabled"}
```

**Error** `500 Internal Server Error`:

```json
{"status": "error", "message": "Failed to install tracing"}
```

---

### `POST /api/v1/llm/disable`

Disable LLM auto-tracing. Note: monkey-patching cannot be fully reversed at runtime. Set `AGENT_AUDIT_AUTO_TRACE=0` in `.env` and restart the server for a complete disable.

**Request**:

```bash
curl -X POST http://localhost:8081/api/v1/llm/disable
```

**Response** `200 OK`:

```json
{
  "status": "info",
  "message": "LLM tracing cannot be fully disabled at runtime after monkey-patching. Set AGENT_AUDIT_AUTO_TRACE=0 in .env and restart the server."
}
```

---

### `POST /api/v1/llm/log`

Record an LLM call manually. Allows external systems to push LLM call telemetry into agent-audit for traceability and cost tracking. Auto-generates `trace_id` and `span_id` if not provided.

**Request**:

```bash
curl -X POST http://localhost:8081/api/v1/llm/log \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openai",
    "model": "gpt-4o",
    "request_tokens": 450,
    "response_tokens": 120,
    "latency_ms": 342,
    "cost_usd": 0.0053,
    "session_id": "refund-bot-001"
  }'
```

**Request Body** (all fields via JSON body):

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `provider` | string | Yes | — | LLM provider (e.g. `"openai"`, `"anthropic"`, `"deepseek"`) |
| `model` | string | Yes | — | Model name (e.g. `"gpt-4o"`, `"claude-sonnet-4"`) |
| `trace_id` | string | No | auto-generated | Distributed trace identifier (32-char hex) |
| `span_id` | string | No | auto-generated | Span identifier within trace (16-char hex) |
| `parent_span_id` | string | No | `""` | Parent span identifier |
| `request_tokens` | int | No | `0` | Input/prompt token count |
| `response_tokens` | int | No | `0` | Output/completion token count |
| `total_tokens` | int | No | `request + response` | Total tokens (auto-computed if omitted) |
| `latency_ms` | int | No | `0` | Round-trip latency in milliseconds |
| `cost_usd` | float | No | `0.0` | Estimated cost in USD |
| `request_body` | object | No | `null` | Full LLM request payload (for replay) |
| `response_body` | object | No | `null` | Full LLM response payload (for replay) |
| `session_id` | string | No | `""` | Session this call belongs to |
| `agent_id` | string | No | `""` | Agent that initiated this call |
| `event_id` | string | No | `""` | Associated audit event ID |

**Response** `200 OK`:

```json
{
  "id": 1,
  "provider": "openai",
  "model": "gpt-4o",
  "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "span_id": "1f2e3d4c5b6a7980",
  "parent_span_id": "",
  "request_tokens": 450,
  "response_tokens": 120,
  "total_tokens": 570,
  "latency_ms": 342,
  "cost_usd": 0.0053,
  "request_body": null,
  "response_body": null,
  "session_id": "refund-bot-001",
  "agent_id": "",
  "event_id": "",
  "timestamp": "2026-06-22T10:30:00.123456+00:00"
}
```

---

### `GET /api/v1/llm/traces/{trace_id}`

Query all LLM calls belonging to a distributed trace, ordered by timestamp. Suitable for constructing waterfall views and latency breakdowns.

**Request**:

```bash
curl http://localhost:8081/api/v1/llm/traces/a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6
```

**Response** `200 OK`:

```json
{
  "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "call_count": 3,
  "calls": [
    {
      "id": 1,
      "provider": "openai",
      "model": "gpt-4o",
      "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
      "span_id": "1f2e3d4c5b6a7980",
      "request_tokens": 450,
      "response_tokens": 120,
      "total_tokens": 570,
      "latency_ms": 342,
      "cost_usd": 0.0053,
      "timestamp": "2026-06-22T10:30:00.123456+00:00"
    }
  ]
}
```

**Error** `404 Not Found`:

```json
{"error": "trace not found", "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"}
```

---

## 9. Compliance

### `POST /api/v1/compliance/report`

Generate an EU AI Act Article 12 compliance report for an agent. Includes agent identity, event timeline, prompt version history, chain integrity proof, policy evaluation log, and evidence bundle export.

**Authentication**: Required if `AGENT_AUDIT_API_KEYS` is set.

**Request**:

```bash
curl -X POST http://localhost:8081/api/v1/compliance/report \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"agent_id": "refund-bot", "format": "markdown"}'
```

**Request Body**:

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `agent_id` | string | Yes | — | Agent identifier |
| `format` | string | No | `"markdown"` | Output format: `"markdown"` or `"json"` |

**Response** `200 OK` (format=markdown): `text/markdown` — the full compliance report.

**Response** `200 OK` (format=json):

```json
{
  "agent_id": "refund-bot",
  "format": "html",
  "report": "# EU AI Act Compliance Report\n\n**Agent**: refund-bot\n..."
}
```

**Error** `500 Internal Server Error`:

```json
{"error": "report generation failed", "detail": "..."}
```

> The report is cached in memory after generation and available via `GET /api/v1/compliance/report/{agent_id}`.

---

### `GET /api/v1/compliance/report/{agent_id}`

Retrieve the last generated compliance report for an agent (from in-memory cache).

**Request**:

```bash
curl http://localhost:8081/api/v1/compliance/report/refund-bot
```

**Response** `200 OK`: `text/markdown` — the cached report.

**Response** `404 Not Found`:

```json
{"error": "no report cached", "agent_id": "refund-bot"}
```

> **Note**: The cache is in-memory only. Reports are lost on server restart. Re-generate via `POST /api/v1/compliance/report`.

---

## 10. Evidence Export

### `POST /api/v1/evidence/export`

Export a signed, tamper-evident evidence bundle (.zip) containing the complete audit trail, prompt version history, integrity proof, and cryptographic signature. Bundles are verifiable offline — no live system access needed.

Compliant with: EU AI Act Article 12, SOC 2, HIPAA audit trail requirements.

**Authentication**: Required if `AGENT_AUDIT_API_KEYS` is set.

**Request**:

```bash
curl -X POST http://localhost:8081/api/v1/evidence/export \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ***" \
  -d '{"agent_id": "refund-bot", "format": "zip", "sign": true}'
```

**Request Body**:

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `agent_id` | string | Yes | — | Agent whose data to export |
| `format` | string | No | `"zip"` | Bundle format (`"zip"`) |
| `sign` | bool | No | `false` | If `true`, signs bundle with HMAC-SHA256 using `AGENT_AUDIT_SECRET_KEY` |
| `session_filter` | array | No | — | Optional list of session IDs to include (all sessions if omitted) |

**Response** `200 OK` — binary `.zip` download:

```
Content-Type: application/zip
Content-Disposition: attachment; filename="evidence-refund-bot-20260622.zip"
```

**Bundle contents**:

| File | Description |
|---|---|
| `metadata.json` | Bundle metadata (agent, timestamp, event count, integrity status) |
| `events.json` | Complete audit trail (hash-chained events) |
| `prompts.json` | Prompt version history |
| `bundle.json` | Bundle SHA-256 hash and optional HMAC signature |
| `README.txt` | Human-readable bundle description and verification instructions |

**Error** `400 Bad Request`:

```json
{"error": "invalid request", "detail": "agent_id is required"}
```

**Verification (offline)**:

```bash
agent-audit verify-bundle evidence-refund-bot.zip
```

> The `SHA-256` bundle hash enables independent auditors to detect any tampering without access to the live system.

---

## 11. Admin

### `GET /api/v1/admin/status`

Administrative status endpoint. Returns storage backend details, uptime, and configuration summary.

**Request**:

```bash
curl http://localhost:8081/api/v1/admin/status
```

**Response** `200 OK`:

```json
{
  "version": "1.0.0",
  "uptime_seconds": 8423,
  "storage": {
    "backend": "sqlite",
    "uri": "sqlite:///./agent_audit.db",
    "size_bytes": 458752
  },
  "api_keys_configured": true,
  "auto_trace_enabled": false,
  "cors_origins": ["*"]
}
```

**Response fields**:

| Field | Type | Description |
|---|---|---|
| `version` | string | Server version |
| `uptime_seconds` | int | Seconds since server start |
| `storage.backend` | string | Active storage backend (`jsonl`, `sqlite`, `postgresql`, `postgresql-orm`) |
| `storage.uri` | string | Database connection URI (credentials masked) |
| `storage.size_bytes` | int | Estimated storage footprint |
| `api_keys_configured` | bool | `true` if `AGENT_AUDIT_API_KEYS` is set |
| `auto_trace_enabled` | bool | `true` if `AGENT_AUDIT_AUTO_TRACE=1` |
| `cors_origins` | array | Allowed CORS origins from `AGENT_AUDIT_CORS_ORIGINS` |

---

## 12. Dashboard & Static Assets

### `GET /`

Serves the SPA dashboard. Uses the first available template:

1. `agent_audit/server/static/index.html` — Svelte SPA build
2. `agent_audit/server/templates/index.html` — self-contained HTML dashboard with SSE streaming, tab navigation, and REST API integration
3. Fallback: inline HTML page with API endpoint listing

**Request**:

```bash
curl http://localhost:8081/
```

**Response**: `text/html` — the dashboard SPA.

### Static Assets

Svelte SPA assets are mounted under `/assets/`:

| Path | Description |
|---|---|
| `GET /assets/{file}` | Svelte SPA JS/CSS bundles (if `static/assets/` exists) |
| `GET /favicon.svg` | Site favicon |
| `GET /icons.svg` | SVG icon sprite sheet |

---

## 13. Legacy Endpoints

v1.0 maintains backward compatibility with the original `http.server`-based API. These endpoints delegate to their v1 equivalents with no functional difference.

| Legacy Endpoint | Maps To | Notes |
|---|---|---|
| `GET /api/stats` | `GET /api/v1/stats` | Same response |
| `GET /api/events` | `GET /api/v1/events` (limit=20) | Same structure |
| `GET /sessions` | `GET /api/v1/sessions` | Same response |
| `GET /session/{id}` | `GET /api/v1/sessions/{id}` | Same response |
| `POST /log` | `POST /api/v1/log` | Same request/response |
| `POST /verify` | `POST /api/v1/verify` | Same request/response |
| `GET /stats` | `GET /api/v1/stats` | Same response |

> **Recommendation**: Update all clients to use `/api/v1/` prefixed endpoints. Legacy endpoints will be deprecated in v2.0.

---

## 14. Error Codes

| Status | Typical Body | Condition |
|---|---|---|
| `200` | (varies) | Success |
| `400` | `{"error": "invalid JSON"}` | Malformed JSON in request body |
| `401` | `{"detail": "Not authenticated"}` | Missing/invalid Bearer token (FastAPI) |
| `401` | `{"error": "unauthorized"}` | Missing/invalid Bearer token (legacy) |
| `404` | `{"error": "session not found"}` | Session ID not found |
| `404` | `{"error": "not found"}` | Unknown endpoint |
| `503` | `{"status": "not_ready", "error": "..."}` | Storage backend unavailable |

---

## 15. Event Types Reference

An audit event object contains the following fields:

```json
{
  "event_id": "a1b2c3d4e5f6",
  "session_id": "customer-12345",
  "sequence": 0,
  "timestamp": 1719001234.567,
  "event_type": "decision",
  "agent_id": "refund-bot",
  "prompt_version": "v3",
  "input_snapshot": "User: refund $45 for order #12345",
  "output_snapshot": "Approved: amount=$45, within v3 $500 limit",
  "metadata": {},
  "prev_hash": "",
  "hash": "3f8a9b0c1d2e4f5a6b7c8d9e0f1a2b3c"
}
```

**Field reference**:

| Field | Type | Description |
|---|---|---|
| `event_id` | string | Unique event identifier (12-char) |
| `session_id` | string | Session this event belongs to |
| `sequence` | int | Position in session's hash chain (0, 1, 2, ...) |
| `timestamp` | float | Unix timestamp |
| `event_type` | string | Category (see below) |
| `agent_id` | string | Agent that produced this event |
| `prompt_version` | string | Prompt version at event time |
| `input_snapshot` | string | Agent input (max 8000 chars) |
| `output_snapshot` | string | Agent output (max 8000 chars) |
| `metadata` | object | Arbitrary JSON metadata |
| `prev_hash` | string | SHA-256 of previous event in chain |
| `hash` | string | SHA-256 of this event |

**Recommended event types**:

| `event_type` | Use for |
|---|---|
| `"decision"` | Agent made a decision (approve, deny, recommend) |
| `"tool_call"` | Agent called an external tool/API |
| `"model_request"` | Agent sent a request to an LLM |
| `"guardrail"` | Policy engine blocked or flagged an action |
| `"error"` | Agent encountered an error |
