# agent-seal v1.0 — Phase 5.2 Security Audit Report

> **Document**: P5.2 Security Audit Report
> **Date**: 2026-06-22
> **Auditor**: workstation-business-dev (Turing)
> **Scope**: Full codebase manual audit — encryption, authentication, input validation, dependency vulnerabilities
> **Status**: Complete (code changes required before production)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Audit Methodology](#2-audit-methodology)
3. [Encryption Audit (Section A)](#3-encryption-audit-section-a)
4. [Authentication Audit (Section B)](#4-authentication-audit-section-b)
5. [Input Validation Audit (Section C)](#5-input-validation-audit-section-c)
6. [Dependency Vulnerabilities Audit (Section D)](#6-dependency-vulnerabilities-audit-section-d)
7. [Risk Matrix](#7-risk-matrix)
8. [Remediation Roadmap](#8-remediation-roadmap)
9. [Compliance Mapping](#9-compliance-mapping)

---

## 1. Executive Summary

A full manual security audit of the agent-seal v1.0.0 codebase was conducted across
four critical security domains: encryption, authentication, input validation, and
dependency vulnerabilities.  Every `.py` file in the `agent_seal/` source tree was
reviewed, with special attention to the `core/`, `server/`, and `server/routes/` modules.

### Overall Assessment: **CONDITIONAL PASS** — 4 HIGH, 14 MEDIUM, 8 LOW

The codebase demonstrates strong cryptographic foundations and good security awareness.
The Ed25519 signing, AES-256-GCM encryption, SHA-256 hash chains, and constant-time
API key comparison are all correctly implemented and follow industry best practices.

**However**, four HIGH-severity findings must be addressed before production deployment:

| ID | Finding | Area | Impact |
|----|---------|------|--------|
| H-1 | Temp file leakage in evidence bundle export | Encryption | Disk exhaustion, data residue |
| H-2 | API keys stored in plain text (no hashing at rest) | Authentication | Key compromise on env leak |
| H-3 | No Pydantic models in POST /api/v1/log | Input Validation | Malformed data, injection risk |
| H-4 | No batch size limit in POST /api/v1/log/batch | Input Validation | OOM DoS |

**Production readiness**: After fixing the 4 HIGH findings (estimated 4–6 hours),
the system is suitable for production deployment with standard monitoring.

---

## 2. Audit Methodology

### 2.1 Files Audited

| Module | Files | Lines |
|--------|-------|-------|
| Core crypto | `core/crypto.py`, `core/encrypted.py`, `core/chain.py`, `core/redact.py` | 611 |
| Evidence | `evidence.py` | 232 |
| Auth | `server/middlewares.py`, `config.py` | 417 |
| Routes | `server/routes/events.py`, `sessions.py`, `llm.py`, `compliance.py`, `evidence.py`, `policy.py`, `prompts.py`, `admin.py` | 1,020 |
| Dependencies | `requirements.txt`, `requirements-dev.txt`, `setup.py` | 82 |

**Total**: 2,362 lines across 18 files.

### 2.2 Tools Used

- **Manual code review**: Every function, every route handler, every data path
- **pip-audit**: OSS dependency vulnerability scan against OSV + PyPA advisory DB
- **FastAPI documentation**: Cross-referenced middleware and route behavior
- **OWASP Top 10 (2021)** and **OWASP API Security Top 10 (2023)** as reference frameworks

### 2.3 Severity Classification

| Rating | Criteria |
|--------|----------|
| **HIGH** | Direct path to data breach, system compromise, or regulatory violation |
| **MEDIUM** | Defense-in-depth gap, hardening opportunity, or best-practice violation |
| **LOW** | Cosmetic, documentation gap, or negligible risk in current deployment model |
| **INFO** | Observation without risk — noted for awareness |

---

## 3. Encryption Audit (Section A)

### 3.1 Cryptographic Foundations

agent-seal's cryptographic core is strong:

| Primitive | Implementation | Status |
|-----------|---------------|--------|
| Hash chain | SHA-256, per-session independent chains | ✅ Correct |
| Signing | Ed25519 via `cryptography` library | ✅ Correct |
| Encryption at rest | AES-256-GCM, unique nonce per event | ✅ Correct |
| Key derivation | PBKDF2-HMAC-SHA256, 600k iterations | ✅ OWASP-compliant |
| Evidence bundle signing | HMAC-SHA256 | ✅ Correct |
| PII redaction | Regex-based (6 categories) | ⚠️ See A-5 |

#### A-1: crypto.py — Ed25519 Signing

```
File: agent_seal/core/crypto.py (243 lines)
```

**Strengths:**

- `generate_key_pair()` (line 28): Uses `Ed25519PrivateKey.generate()` — correct.
- `save_private_key()` (line 35): Uses `BestAvailableEncryption(password)` with PEM PKCS8 — industry standard.
- `Signer.sign_event()` (line 115): Composite payload `{event_id}|{event_hash}|{timestamp}` — binds all three components.
- `Verifier.verify()` (line 146): Catches `InvalidSignature`, `ValueError`, `TypeError` separately — no information leak through exception differentiation.

**Findings:**

| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| A-1a | MEDIUM | No key rotation mechanism — keys are generated once and used indefinitely | `crypto.py:28` |
| A-1b | LOW | `save_private_key()` password validated only for emptiness, not strength | `crypto.py:46` |
| A-1c | INFO | `Signer.sign()` logs partial signature (first 12 chars) — low risk but unnecessary | `crypto.py:112` |

#### A-2: encrypted.py — AES-256-GCM Encrypted Storage

```
File: agent_seal/core/encrypted.py (135 lines)
```

**Strengths:**

- `derive_key()` (line 28): PBKDF2 with 600,000 iterations + random salt — exceeds OWASP minimum (600k for SHA-256).
- `EncryptedStore.write()` (line 71): Unique 12-byte nonce per event (`os.urandom(12)`), session_id as AAD — prevents nonce reuse and ciphertext manipulation.
- `EncryptedStore.read()` (line 88): Catches `InvalidTag` for tamper detection, `json.JSONDecodeError` for corruption.
- Binary format header `AUDIT\x01` (line 64) with `ct_len` prefix — proper framing.

**Findings:**

| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| A-2a | MEDIUM | No encrypted store key rotation — same key encrypts all events indefinitely | `encrypted.py:52` |
| A-2b | LOW | `save_key()` / `load_key()` write/read with no permission checks (0600 umask not enforced) | `encrypted.py:41-46` |
| A-2c | INFO | `stats()` method reads AND decrypts all sessions — O(n) CPU cost for what should be metadata | `encrypted.py:131` |

#### A-3: evidence.py — Evidence Bundle Export

```
File: agent_seal/evidence.py (232 lines)
```

**Strengths:**

- `EvidenceExporter.export()` (line 62): Creates zip bundle with metadata + events + prompts + bundle hash + signature.
- `verify_bundle()` (line 146): Verifies both SHA-256 hash AND event hash chain — dual integrity check.
- HMAC-SHA256 signing with configurable key — flexible.

**Findings:**

| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| **A-3a** | **🔴 HIGH** | **`tempfile.NamedTemporaryFile(delete=False)` in `server/routes/evidence.py:56` — temp files are NEVER cleaned up. Each evidence export leaks a `.zip` file in the system temp directory. On a busy server this causes disk exhaustion.** | `server/routes/evidence.py:55-58` |
| A-3b | MEDIUM | `sign_key` accepted as plain string in POST body — should use env var or dedicated secret management | `server/routes/evidence.py:33` |
| A-3c | LOW | `_compute_bundle_hash()` uses `event_ids` + `event_hashes` but NOT event content — a collision in event_id or hash could produce identical bundle hash | `evidence.py:195` |

#### A-4: chain.py — Hash Chain Engine

```
File: agent_seal/core/chain.py (191 lines)
```

**Strengths:**

- Per-session independent hash chains — limits blast radius of a single chain break.
- `SessionChain.append()` (line 53): Truncates input/output at 8,000 characters (`[:8000]`) — prevents memory-bomb via oversized payloads.
- `verify()` (line 90): Recomputes hash of every event (not just checks `prev_hash` pointer) — detects content modification even if hash pointer is consistent.

**Findings:**

| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| A-4a | INFO | Event ID uses `uuid.uuid4()[:12]` — 12 hex chars = 48 bits of entropy. Sufficient for audit (2.8e14 events before 50% collision probability) but shorter than standard UUID. | `chain.py:65` |

#### A-5: redact.py — PII Redaction

```
File: agent_seal/core/redact.py (42 lines)
```

**Findings:**

| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| A-5a | MEDIUM | Regex-based PII detection is bypassable: phone numbers with non-standard formatting, email addresses with Unicode homoglyphs, API keys without `=` separator. Defense-in-depth gap — not a primary security boundary. | `redact.py:11-18` |
| A-5b | LOW | `hash_sensitive()` uses SHA-256[:12] — 12 hex chars = 48 bits. Sufficient for pseudonymization but not anonymization. Document this limitation. | `redact.py:34-41` |

---

## 4. Authentication Audit (Section B)

### 4.1 API Key Authentication

```
File: agent_seal/server/middlewares.py (221 lines)
```

**Strengths:**

- `secrets.compare_digest()` (line 186): Constant-time comparison — eliminates timing side-channel. **This is the gold standard.**
- Evaluates ALL comparisons before `any()` (lines 186–187): Avoids short-circuit leaking which key matched.
- Supports both `X-API-Key` header and `Authorization: Bearer` (lines 169–173).
- Public endpoint exclusion via frozenset (line 142) — `/health`, `/ready`, `/metrics`, `/stats`, `/events/stream` are unauthenticated by design.

**Findings:**

| ID | Severity | Finding | Location |
|----|----------|---------|----------|
| **B-1** | **🔴 HIGH** | **API keys stored in plain text. `AGENT_SEAL_API_KEYS` is a comma-separated env var of raw keys. If `.env` leaks (misconfigured S3 bucket, CI log, Docker image layer), all API keys are exposed. Production should hash keys at rest.** | `config.py:115-117` |
| B-2 | MEDIUM | No rate limiting — brute-force against API key endpoint has no throttle. An attacker can try unlimited keys per second. | `middlewares.py:159` |
| B-3 | MEDIUM | No key rotation support — adding a new key and removing an old one requires config change + server restart. No dual-key transition period. | `config.py:115` |
| B-4 | MEDIUM | `/api/v1/stats` and `/api/v1/events/stream` are public — leak internal state (event counts, session IDs) without authentication. Acceptable for dev but should be configurable in production. | `middlewares.py:142-150` |
| B-5 | MEDIUM | `secret_key` fallback chain: `AGENT_SEAL_SECRET_KEY → SECRET_KEY` (non-prefixed). In a multi-app environment this could accidentally share secrets across services. | `config.py:72-73` |
| B-6 | LOW | `WWW-Authenticate: ApiKey` is non-standard (RFC 7235 doesn't define `ApiKey` scheme). Use `Bearer` for standards compliance. | `middlewares.py:179` |
| B-7 | INFO | CORS defaults to empty origins (secure by default) — correct. | `config.py:121-124` |

---

## 5. Input Validation Audit (Section C)

### 5.1 Route-by-Route Analysis

#### C-1: POST /api/v1/log (events.py:125–159)

```python
data = await request.json()          # ← Raw JSON, no schema validation
event = engine.log(
    session_id=data.get("session_id", "default"),   # ← No type/length check
    event_type=data.get("event_type", "unknown"),
    agent_id=data.get("agent_id", "unknown"),
    prompt_version=data.get("prompt_version", "v1"),
    input_text=data.get("input", ""),               # ← Unlimited size (truncated at 8000 in chain.py)
    output_text=data.get("output", ""),             # ← Unlimited size
    metadata=data.get("metadata"),                  # ← Arbitrary JSON, no depth/size limit
)
```

| ID | Severity | Finding |
|----|----------|---------|
| **C-1a** | **🔴 HIGH** | **No Pydantic request model — the handler calls `request.json()` directly and accesses fields with `.get()`. There is zero type validation, zero length validation, and zero schema enforcement. A malformed payload passes silently.** |
| C-1b | MEDIUM | `metadata` field accepts arbitrary nested JSON with no depth limit — could cause recursion issues in JSON serialization downstream. |
| C-1c | INFO | Input truncation at 8000 chars happens in `chain.py:72-73` — defense-in-depth is correct, but the truncation is silent (no warning to caller). |

#### C-2: POST /api/v1/log/batch (events.py:162–207)

| ID | Severity | Finding |
|----|----------|---------|
| **C-2a** | **🔴 HIGH** | **No batch size limit. An attacker can POST an array of 1,000,000 events, causing OOM and crashing the server. Mitigation: cap batch size at 1,000 (configurable).** |
| C-2b | MEDIUM | Same Pydantic-model gap as single-log endpoint — each array element is unchecked. |

#### C-3: Other Route Endpoints

| ID | Severity | Finding | Route |
|----|----------|---------|-------|
| C-3a | MEDIUM | `agent_id` accepted as raw string, no alphanumeric/length validation | All routes that accept `agent_id` |
| C-3b | MEDIUM | `session_id` accepted as raw string in path params — no sanitization against traversal (`../`) | `sessions.py:51`, `events.py:37` |
| C-3c | MEDIUM | `prompt_text` in `POST /api/v1/prompts/{agent_id}` has no max length — could accept a 100MB string | `prompts.py:113-118` |
| C-3d | MEDIUM | `output` and `input` in `POST /api/v1/policy/evaluate` have no max length | `policy.py:57-63` |
| C-3e | LOW | `POST /api/v1/llm/log` uses FastAPI `Body(...)` with type hints — this is the only endpoint using proper Pydantic validation. Other endpoints should follow this pattern. | `llm.py:101-118` |
| C-3f | LOW | `GET /api/v1/events` validates `limit` (1–500) and `offset` (≥ 0) via FastAPI `Query(ge=...)` — correct pattern. | `events.py:74-76` |

#### C-4: PII Redaction Gaps

| ID | Severity | Finding |
|----|----------|---------|
| C-4a | MEDIUM | PII redaction is **opt-in** (caller must instantiate `Redactor` and call `.sanitize()`). The API endpoints do NOT redact by default. Sensitive data entering via `POST /api/v1/log` is stored as-is. |
| C-4b | LOW | Redaction patterns don't cover international PII formats (e.g., non-US phone numbers, national ID numbers). |

---

## 6. Dependency Vulnerabilities Audit (Section D)

### 6.1 pip-audit Scan Results

```
$ pip-audit --requirement requirements.txt
No known vulnerabilities found
```

All declared dependencies pass the OSV + PyPA advisory database scan. No known CVEs
in the version ranges specified by `requirements.txt`.

### 6.2 Installed Version Check

| Package | requirements.txt Min | setup.py Min | Installed | Status |
|---------|---------------------|--------------|-----------|--------|
| cryptography | >=43.0 | >=43.0 | 49.0.0 | ✅ Current |
| fastapi | >=0.100 | >=0.100 | 0.133.1 | ✅ Current |
| pydantic | >=2.0 | >=2.0 | 2.13.4 | ✅ Current |
| sqlalchemy | >=2.0 | >=2.0 | 2.0.34 | ✅ Current |
| starlette | >=1.3.1 | — | 1.3.1 | ✅ Current |
| uvicorn | >=0.20 | >=0.20 | 0.41.0 | ✅ Current |
| alembic | >=1.13 | >=1.13 | 1.18.4 | ✅ Current |
| pyyaml | >=6.0 | >=6.0 | 6.0.3 | ✅ Current |
| **prometheus-client** | **>=0.20** | **>=0.14** | **0.14.1** | ⚠️ **Below requirements.txt floor** |
| prometheus-fastapi-instrumentator | >=7.0 | >=6.0 | 8.0.0 | ✅ Current |

### 6.3 Dependency Declaration Inconsistencies

| ID | Severity | Finding |
|----|----------|---------|
| D-1 | MEDIUM | `setup.py` declares `prometheus_client>=0.14` (underscore, version 0.14) while `requirements.txt` declares `prometheus-client>=0.20` (hyphen, version 0.20). The installed version (0.14.1) meets the setup.py minimum but VIOLATES the requirements.txt minimum. The PyPI package name uses a **hyphen** (`prometheus-client`); `setup.py`'s underscore variant may cause install issues on some resolvers. |
| D-2 | MEDIUM | `setup.py` has lower version floors than `requirements.txt` for both prometheus packages (`>=0.14` vs `>=0.20`, `>=6.0` vs `>=7.0`). `requirements.txt` should be the authoritative source; `setup.py` should match. |
| D-3 | MEDIUM | No lock file (`poetry.lock`, `Pipfile.lock`, or `requirements-lock.txt` with hashes). Reproducible builds are not guaranteed — a `pip install` today may resolve different versions than last week. |
| D-4 | MEDIUM | `psycopg2-binary>=2.9` present in `setup.py` (`extras_require["postgresql"]`) and `requirements-dev.txt` but **absent from `requirements.txt`**. Production Docker builds that only install `requirements.txt` will fail to connect to PostgreSQL. The CHANGELOG claims PostgreSQL support as a headline feature. |
| D-5 | LOW | `types-PyYAML` and `types-psycopg2` not pinned in `requirements-dev.txt` — type-stub packages can introduce breaking changes on minor version bumps. |
| D-6 | INFO | `sse-starlette>=1.0` has no upper bound. Version 3.x may break the SSE API (currently on 3.4.4 — works fine, but unpinned). |

---

## 7. Risk Matrix

### 7.1 Summary by Severity

| Area | HIGH | MEDIUM | LOW | INFO |
|------|------|--------|-----|------|
| Encryption | 1 | 4 | 3 | 3 |
| Authentication | 1 | 4 | 1 | 1 |
| Input Validation | 2 | 5 | 2 | 1 |
| Dependencies | 0 | 4 | 1 | 1 |
| **Total** | **4** | **17** | **7** | **6** |

### 7.2 OWASP Top 10 Mapping

| OWASP Category | Findings | Status |
|----------------|----------|--------|
| A01: Broken Access Control | B-4 (public stats/stream) | MEDIUM |
| A02: Cryptographic Failures | A-3b (plain sign_key), A-5a (regex redact) | MEDIUM |
| A03: Injection | C-3b (path traversal), C-1a (no schema) | HIGH |
| A04: Insecure Design | B-3 (no key rotation), D-3 (no lockfile) | MEDIUM |
| A05: Security Misconfiguration | B-1 (plaintext keys), D-4 (missing psycopg2) | HIGH |
| A06: Vulnerable Components | pip-audit: clean | ✅ PASS |
| A07: Auth Failures | B-2 (no rate limit) | MEDIUM |
| A08: Software & Data Integrity | D-3 (no lockfile), C-4a (PII not redacted) | MEDIUM |
| A09: Logging & Monitoring | — | ✅ PASS |
| A10: SSRF | — | ✅ N/A |

### 7.3 OWASP API Security Top 10 Mapping

| API Category | Findings |
|-------------|----------|
| API1: Broken Object Level Auth | B-4 (public session enumeration) |
| API2: Broken Authentication | B-2 (no rate limit) |
| API3: Broken Object Property Level Auth | C-1a (no schema — mass assignment possible) |
| API4: Unrestricted Resource Consumption | C-2a (no batch limit), C-3c (unbounded prompt_text) |
| API5: Broken Function Level Auth | — ✅ |
| API6: Unrestricted Access to Sensitive Business Flows | B-4 (public /stats) |
| API7: Server Side Request Forgery | — ✅ N/A |
| API8: Security Misconfiguration | D-1/D-2 (version inconsistency) |
| API9: Improper Inventory Management | D-4 (missing psycopg2 in prod deps) |
| API10: Unsafe Consumption of APIs | C-1a (no request validation) |

---

## 8. Remediation Roadmap

### 8.1 P0 — Must Fix Before Production (estimated 4–6 hours)

| ID | Finding | Fix | Effort | File |
|----|---------|-----|--------|------|
| H-1 | Temp file leak in evidence export | Add `BackgroundTask` to delete temp file after response; or use `SpooledTemporaryFile` | 30 min | `server/routes/evidence.py` |
| H-2 | Plaintext API keys | Hash keys at rest with SHA-256; compare hashes in middleware; env var stores hashes | 1 hr | `config.py`, `server/middlewares.py` |
| H-3 | No Pydantic model in POST /api/v1/log | Create `LogEventRequest` Pydantic model with field validators (max_length, regex for IDs) | 1.5 hr | `server/routes/events.py`, new `server/schemas.py` |
| H-4 | No batch size limit in POST /api/v1/log/batch | Add `max_batch_size` config (default 1000); reject oversized batches with 413 | 30 min | `server/routes/events.py`, `config.py` |

### 8.2 P1 — Should Fix Before Widespread Use (estimated 4–6 hours)

| ID | Finding | Fix |
|----|---------|-----|
| A-3b | Plain sign_key in API body | Move to `AGENT_SEAL_SIGNING_KEY` env var |
| B-2 | No rate limiting | Add `slowapi` or Starlette `RateLimitMiddleware` (100 req/min per IP for auth endpoints) |
| B-4 | Public /stats and /events/stream | Add `AGENT_SEAL_PUBLIC_ENDPOINTS` config toggle |
| C-3a–d | No input sanitization | Add Pydantic `Field(max_length=...)` and `regex` validators on all string inputs |
| C-4a | PII not redacted by default | Auto-redact `input_snapshot`/`output_snapshot` when `AGENT_SEAL_AUTO_REDACT=1` |
| D-1/D-2 | Version inconsistency | Align setup.py with requirements.txt; make requirements.txt canonical |
| D-3 | No lock file | Add `requirements-lock.txt` with `pip freeze --hashes` |
| D-4 | Missing psycopg2 in requirements.txt | Move `psycopg2-binary>=2.9` from dev to core requirements, or document as optional |

### 8.3 P2 — Nice to Have (estimated 4–8 hours)

| ID | Finding | Fix |
|----|---------|-----|
| A-1a | No key rotation | Document key rotation procedure for Ed25519 and AES-256 keys |
| A-2a | No encrypted store key rotation | Implement key version header in encrypted records |
| B-3 | No dual-key transition | Support `AGENT_SEAL_API_KEYS` and `AGENT_SEAL_API_KEYS_PREVIOUS` for rotation |
| A-5a | Regex redact bypass | Add `presidio-analyzer` or spaCy NER as optional enhancement |

---

## 9. Compliance Mapping

### 9.1 EU AI Act Article 12 (Record-Keeping)

| Requirement | agent-seal Status | Notes |
|-------------|-------------------|-------|
| Automatic logging | ✅ Supported via LLM auto-tracing | Optional, off by default |
| Technical safeguards against tampering | ✅ SHA-256 hash chains + Ed25519 signatures | Core feature |
| Retention period documentation | ⚠️ See `core/rotation.py` | Rotation policy exists but retention config not surfaced in .env.example |
| Access control | ⚠️ API keys supported but plaintext | Fix H-2 |
| Input validation | ❌ No Pydantic models | Fix H-3 |

### 9.2 SOC 2 (Security)

| Trust Service Criteria | Status |
|------------------------|--------|
| CC6.1 (Logical access controls) | ✅ API key auth + constant-time comparison |
| CC6.6 (External boundary protections) | ⚠️ No rate limiting (B-2) |
| CC7.1 (Vulnerability detection) | ✅ pip-audit integration possible |
| CC7.2 (Monitoring) | ✅ Prometheus metrics + structured logging |

### 9.3 HIPAA (Technical Safeguards)

| Safeguard | Status |
|-----------|--------|
| Access control (§164.312(a)(1)) | ✅ API key auth |
| Audit controls (§164.312(b)) | ✅ Hash-chained audit trail |
| Integrity controls (§164.312(c)(1)) | ✅ SHA-256 + Ed25519 |
| Person authentication (§164.312(d)) | ✅ API keys (fix H-2 for hashing) |
| Transmission security (§164.312(e)(1)) | ⚠️ TLS handled by nginx in front; not enforced at app layer |

---

## Appendix A: File Manifest

All audited files with line counts:

```
agent_seal/core/crypto.py          243 lines  — Ed25519 signing
agent_seal/core/encrypted.py       135 lines  — AES-256-GCM encrypted store
agent_seal/core/chain.py           191 lines  — SHA-256 hash chain engine
agent_seal/core/redact.py           42 lines  — PII redaction
agent_seal/evidence.py             232 lines  — Evidence bundle export
agent_seal/config.py               196 lines  — Configuration system
agent_seal/server/middlewares.py    221 lines  — Auth + CORS + GZip + Prometheus
agent_seal/server/routes/events.py  261 lines  — Event CRUD + SSE
agent_seal/server/routes/sessions.py 99 lines  — Session list/detail
agent_seal/server/routes/llm.py     179 lines  — LLM tracing
agent_seal/server/routes/compliance.py 78 lines — Compliance reports
agent_seal/server/routes/evidence.py  85 lines — Evidence export endpoint
agent_seal/server/routes/policy.py    90 lines — Policy evaluation
agent_seal/server/routes/prompts.py  173 lines — Prompt versioning
agent_seal/server/routes/admin.py    100 lines — Health/dashboard/metrics
agent_seal/server/dependencies.py    207 lines — Shared infrastructure
requirements.txt                       31 lines — Core dependencies
requirements-dev.txt                   17 lines — Dev dependencies
setup.py                               34 lines — Package definition
```

---

## Appendix B: pip-audit Command Output

```
$ pip-audit --requirement requirements.txt
No known vulnerabilities found
```

Scan performed 2026-06-22 against the OSV.dev and PyPA advisory databases.
All dependencies in the declared version ranges are free of known CVEs.

---

*End of Phase 5.2 Security Audit Report.  Next step: P5.3 v1.0 Release Notes.*
