# agent-audit Storage Migration Guide

> How to migrate between JSONL, SQLite, and PostgreSQL storage backends — from local dev to enterprise production.

---

## Table of Contents

1. [Storage Backend Overview](#1-storage-backend-overview)
2. [Quick Reference](#2-quick-reference)
3. [Backend Selection](#3-backend-selection)
4. [Migration Procedures](#4-migration-procedures)
   - [JSONL → SQLite](#41-jsonl--sqlite)
   - [JSONL → PostgreSQL](#42-jsonl--postgresql)
   - [SQLite → PostgreSQL](#43-sqlite--postgresql)
5. [Docker Compose Deployment](#5-docker-compose-deployment)
6. [Zero-Downtime Migration](#6-zero-downtime-migration)
7. [Troubleshooting](#7-troubleshooting)
8. [Post-Migration Checklist](#8-post-migration-checklist)

---

## 1. Storage Backend Overview

agent-audit provides three pluggable storage backends, all implementing the same `AuditStore` protocol. Swap backends without changing any application code.

| Backend | Best for | Concurrency | Query Support | Production Ready |
|---|---|---|---|---|
| **JSONL** | Local dev, single-process, prototyping | ❌ single-process | ❌ file grep only | ❌ No |
| **SQLite** | Local dev, read-heavy dashboards | ⚠️ single-writer, multi-reader | ✅ full SQL | ⚠️ Single server only |
| **PostgreSQL** | Production, multi-server, high-concurrency | ✅ full MVCC | ✅ full SQL + JSONB | ✅ Yes |

### JSONL (File-based)

```
audit_logs/
├── session-abc.jsonl    # One file per session
├── session-def.jsonl
└── audit.jsonl          # Optional legacy format
```

Each line is a JSON object representing one audit event. Simple, human-readable, but no query support and writes are not concurrency-safe.

### SQLite (File-based)

```
audit.db                 # Single-file database
```

A single SQLite database file with an `events` table and indexes on `session_id` and `(session_id, sequence)`. Supports concurrent reads but serializes writes. Uses WAL journal mode for better read concurrency.

### PostgreSQL (Server-based)

```
agent_audit database
├── events table         # Core audit events (JSONB metadata)
├── llm_calls table      # LLM call tracing (v1.0+)
├── prompt_versions table # Prompt version history
├── policy_decisions table # Policy evaluation records
└── sessions table       # Session metadata
```

Full ACID compliance, concurrent writes, JSONB indexes, connection pooling (via `psycopg2.pool.ThreadedConnectionPool`). Production-grade.

---

## 2. Quick Reference

| From | To | Tool | Command |
|---|---|---|---|
| JSONL | SQLite | `agent_audit.migrate.jsonl_to_sqlite()` | See [§4.1](#41-jsonl--sqlite) |
| JSONL | PostgreSQL | pgloader or custom script | See [§4.2](#42-jsonl--postgresql) |
| SQLite | PostgreSQL | pgloader | `pgloader audit.db postgresql://...` |
| Any | Any | Config change (cold) | Change `AGENT_AUDIT_DB_URL` and restart |

---

## 3. Backend Selection

The storage backend is determined by the `AGENT_AUDIT_DB_URL` environment variable (or `--store-uri` in code). agent-audit auto-detects the backend from the URI scheme.

### Auto-Detection Rules

```
postgresql://user:pass@host:5432/db  →  PostgreSQLStore  (native psycopg2)
postgres://user:pass@host:5432/db    →  PostgreSQLStore
sqlite://path/to/audit.db             →  SQLiteStore
audit.db                              →  SQLiteStore      (.db extension)
./audit_logs                          →  JSONLStore       (directory, default)
```

### Explicit Backend Override

Set `AGENT_AUDIT_STORAGE_BACKEND` to force a specific backend regardless of URI:

| Value | Backend | Notes |
|---|---|---|
| `jsonl` | `JSONLStore` | Strip `jsonl://` prefix if present |
| `sqlite` | `SQLiteStore` | Strip `sqlite://` prefix if present |
| `postgresql` | `PostgreSQLStore` | Native psycopg2, lightweight |
| `postgresql-orm` | `PostgreSQLStoreORM` | Full SQLAlchemy ORM with Alembic schema |
| `auto` | Auto-detect (default) | Detect from URI scheme/extension |

### Code Example

```python
from agent_audit.core.storage import create_store

# Auto-detect from URI
store = create_store("postgresql://audit:***@localhost:5432/agent_audit")

# Force backend
store = create_store(
    "postgresql://audit:***@localhost:5432/agent_audit",
    backend="postgresql-orm"
)
```

---

## 4. Migration Procedures

### 4.1 JSONL → SQLite

Best for adding SQL query support to an existing JSONL trail.

#### Option A: Using `AuditEngine` (recommended)

```bash
# Migrate all JSONL files in a directory to a SQLite database
python -c "
from agent_audit.core.storage import create_store, AuditEngine

# Read from JSONL
jsonl_engine = AuditEngine('./audit_logs')

# Write to SQLite
import os; os.environ['AGENT_AUDIT_STORAGE_BACKEND'] = 'sqlite'
sqlite_engine = AuditEngine('sqlite://audit_new.db')

# Copy all events
for sid in jsonl_engine.sessions():
    events = jsonl_engine.read(sid)
    for e in events:
        sqlite_engine.log(
            session_id=e['session_id'],
            event_type=e['event_type'],
            agent_id=e.get('agent_id', 'unknown'),
            prompt_version=e.get('prompt_version', 'v1'),
            input_text=e.get('input_snapshot', ''),
            output_text=e.get('output_snapshot', ''),
            metadata=e.get('metadata', {}),
        )

# Verify the copy
print(f'Events copied. Verifying...')
print('Source stats:', jsonl_engine.stats())
print('Target stats:', sqlite_engine.stats())
sqlite_engine.close()
jsonl_engine.close()
"
```

#### Option B: Switch config and let data accumulate (lazy)

```bash
# Change .env or env var
export AGENT_AUDIT_DB_URL=sqlite://audit.db
agent-audit serve
```

New events go to SQLite. Old JSONL events remain in the old directory. No data loss, but old data is split across backends. Use for greenfield migrations where historical data isn't critical.

### 4.2 JSONL → PostgreSQL

Best for moving from local dev to production.

#### Prerequisites

```bash
# PostgreSQL server running
# Install the PostgreSQL driver
pip install psycopg2-binary

# Create the database
createdb agent_audit
```

#### Option A: Bulk import with a migration script

```python
"""migrate_jsonl_to_pg.py — Bulk import JSONL audit trails into PostgreSQL."""

import json
import sys
from pathlib import Path

from agent_audit.core.storage import create_store

def migrate(jsonl_dir: str, pg_dsn: str) -> int:
    """Import all JSONL files into PostgreSQL. Returns event count."""
    pg_store = create_store(pg_dsn, backend="postgresql")
    jsonl_store = create_store(jsonl_dir, backend="jsonl")

    total = 0
    sessions = jsonl_store.sessions()

    print(f"Found {len(sessions)} sessions. Importing...")

    for sid in sessions:
        events = jsonl_store.read_session(sid)
        for e in events:
            # Reconstruct a ChainEvent and write
            from agent_audit.core.chain import ChainEvent
            event = ChainEvent(
                event_id=e.get("event_id", ""),
                session_id=e.get("session_id", sid),
                sequence=e.get("sequence", 0),
                timestamp=e.get("timestamp", 0),
                event_type=e.get("event_type", "unknown"),
                agent_id=e.get("agent_id", "unknown"),
                prompt_version=e.get("prompt_version", "v1"),
                input_snapshot=e.get("input_snapshot", "")[:8000],
                output_snapshot=e.get("output_snapshot", "")[:8000],
                metadata=e.get("metadata", {}),
                prev_hash=e.get("prev_hash", ""),
                hash=e.get("hash", ""),
            )
            pg_store.write(event)
            total += 1

        print(f"  {sid}: {len(events)} events")

    pg_store.close()
    jsonl_store.close()
    print(f"\nDone. {total} events imported from {len(sessions)} sessions.")
    return total

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python migrate_jsonl_to_pg.py <jsonl_dir> <postgresql_dsn>")
        sys.exit(1)
    migrate(sys.argv[1], sys.argv[2])
```

Run:

```bash
python migrate_jsonl_to_pg.py ./audit_logs "postgresql://audit:pass@localhost:5432/agent_audit"
```

#### Option B: Using pgloader (advanced)

For very large datasets (>100k events), pgloader is faster:

```bash
# Install pgloader
# macOS: brew install pgloader
# Ubuntu: apt install pgloader

# Create a pgloader command file
cat > migrate.load <<'EOF'
LOAD CSV
  FROM 'audit_logs/all_events.csv'
  INTO postgresql://audit:pass@localhost:5432/agent_audit
  TARGET TABLE events
  WITH
    fields terminated by ',',
    fields optionally enclosed by '"',
    skip header = 1
  SET work_mem to '256MB',
      maintenance_work_mem to '512MB'
  BEFORE LOAD DO
    $$ DROP INDEX IF EXISTS idx_events_session; $$,
    $$ DROP INDEX IF EXISTS idx_events_session_seq; $$
  AFTER LOAD DO
    $$ CREATE INDEX idx_events_session ON events(session_id); $$,
    $$ CREATE UNIQUE INDEX idx_events_session_seq ON events(session_id, sequence); $$;
EOF

# First export JSONL to CSV
python -c "
import json, csv
from pathlib import Path

with open('audit_logs/all_events.csv', 'w') as out:
    writer = csv.DictWriter(out, fieldnames=[
        'event_id','session_id','sequence','timestamp','event_type',
        'agent_id','prompt_version','input_snapshot','output_snapshot',
        'metadata_json','prev_hash','hash'
    ])
    writer.writeheader()
    for f in Path('audit_logs').glob('*.jsonl'):
        for line in open(f):
            if line.strip():
                e = json.loads(line)
                e.setdefault('sequence', 0)
                e.setdefault('metadata_json', json.dumps(e.get('metadata', {})))
                writer.writerow({k: e.get(k, '') for k in writer.fieldnames})
print('CSV export done.')
"

pgloader migrate.load
```

### 4.3 SQLite → PostgreSQL

Best for scaling up from single-server to multi-server deployment.

#### Option A: Bulk import script

```python
"""migrate_sqlite_to_pg.py — Import SQLite audit trail into PostgreSQL."""

import sqlite3
import sys

from agent_audit.core.storage import create_store
from agent_audit.core.chain import ChainEvent

def migrate(sqlite_path: str, pg_dsn: str) -> int:
    sqlite_db = sqlite3.connect(sqlite_path)
    pg_store = create_store(pg_dsn, backend="postgresql")

    rows = sqlite_db.execute(
        "SELECT event_id, session_id, sequence, timestamp, event_type, "
        "agent_id, prompt_version, input_snapshot, output_snapshot, "
        "metadata_json, prev_hash, hash FROM events ORDER BY session_id, sequence"
    ).fetchall()

    total = 0
    cur_session = None
    for row in rows:
        event = ChainEvent(
            event_id=row[0],
            session_id=row[1],
            sequence=row[2],
            timestamp=row[3],
            event_type=row[4],
            agent_id=row[5],
            prompt_version=row[6],
            input_snapshot=(row[7] or "")[:8000],
            output_snapshot=(row[8] or "")[:8000],
            metadata=json.loads(row[9]) if row[9] else {},
            prev_hash=row[10] or "",
            hash=row[11] or "",
        )
        pg_store.write(event)
        total += 1

    sqlite_db.close()
    pg_store.close()
    print(f"Migrated {total} events.")
    return total

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python migrate_sqlite_to_pg.py <sqlite_path> <postgresql_dsn>")
        sys.exit(1)
    import json
    migrate(sys.argv[1], sys.argv[2])
```

#### Option B: Using pgloader

pgloader has native SQLite support:

```bash
pgloader audit.db postgresql://audit:pass@localhost:5432/agent_audit
```

---

## 5. Docker Compose Deployment

The recommended production deployment uses Docker Compose with PostgreSQL:

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your values:
#   POSTGRES_PASSWORD=<strong-password>
#   AGENT_AUDIT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# 2. Import existing data (if migrating)
#    Run one of the migration scripts from §4 against your local PostgreSQL

# 3. Start the stack
docker compose up -d

# 4. Verify
curl http://localhost/health
# {"status":"ok","version":"1.0.0"}
```

### Stack Architecture

```
                  ┌──────────────┐
                  │    nginx     │  :80/:443  (TLS termination, SPA static files)
                  └──────┬───────┘
                         │ proxy_pass
                  ┌──────▼───────┐
                  │  FastAPI     │  :8081  (REST API + SSE + SPA)
                  └──┬────────┬──┘
                     │        │
              ┌──────▼──┐ ┌──▼──────┐
              │   PG    │ │  Redis  │  :5432 / :6379
              └─────────┘ └─────────┘
```

### Environment Variables for Production

| Variable | Required | Example |
|---|---|---|
| `POSTGRES_USER` | Yes | `audit` |
| `POSTGRES_PASSWORD` | Yes | `change-me-in-production` |
| `POSTGRES_DB` | Yes | `agent_audit` |
| `AGENT_AUDIT_DB_URL` | Yes | `postgresql://audit:***@db:5432/agent_audit` |
| `AGENT_AUDIT_SECRET_KEY` | Yes | 64 hex chars |
| `AGENT_AUDIT_API_KEYS` | Recommended | `key1,key2` |
| `AGENT_AUDIT_SIGNING_KEY` | Optional | `/etc/secrets/ed25519.pem` |
| `AGENT_AUDIT_ENCRYPTION_KEY` | Optional | 32 hex bytes |

---

## 6. Zero-Downtime Migration

For production migrations with active traffic.

### Strategy: Dual Write → Cutover

```
Phase 1 (Dual Write):
  ┌─────────┐     write     ┌──────────┐
  │  App    │──────────────▶│  SQLite  │ (current)
  │         │               └──────────┘
  │         │     write     ┌──────────────┐
  │         │──────────────▶│  PostgreSQL  │ (new)
  └─────────┘               └──────────────┘

Phase 2 (Backfill):
  Migrate historical data from SQLite to PostgreSQL.

Phase 3 (Cutover):
  ┌─────────┐               ┌──────────┐
  │  App    │               │  SQLite  │ (read-only, archive)
  │         │     write     ┌──────────────┐
  │         │──────────────▶│  PostgreSQL  │ (primary)
  └─────────┘               └──────────────┘

Phase 4 (Cleanup):
  Archive SQLite file. Remove dual-write code.
```

#### Implementation Sketch

```python
from agent_audit.core.storage import AuditEngine

class DualWriteEngine:
    """Write to both old and new backends during migration."""

    def __init__(self, old_engine: AuditEngine, new_engine: AuditEngine):
        self.old = old_engine
        self.new = new_engine
        self.cutover = False  # Flip to True after backfill

    def log(self, **kwargs):
        self.new.log(**kwargs)
        if not self.cutover:
            self.old.log(**kwargs)

    def read(self, session_id: str):
        if self.cutover:
            return self.new.read(session_id)
        result = self.new.read(session_id)
        return result if result else self.old.read(session_id)
```

---

## 7. Troubleshooting

### psycopg2 ImportError

```
ImportError: PostgreSQLStore requires psycopg2. Install with:
  pip install psycopg2-binary
```

Install the PostgreSQL driver:

```bash
pip install psycopg2-binary
```

Or install with the `[postgresql]` extra:

```bash
pip install -e ".[postgresql]"
```

### Connection Refused

```
psycopg2.OperationalError: could not connect to server: Connection refused
```

- Ensure PostgreSQL is running: `pg_isready`
- Check the DSN: `postgresql://user:***@host:5432/dbname`
- In Docker Compose, the hostname is `db` (service name), not `localhost`

### Events table not created

The `PostgreSQLStore` auto-creates the `events` table on first use. If it doesn't:

```bash
# Check if the table exists
psql -U audit -d agent_audit -c "\dt events"

# Create manually if needed
psql -U audit -d agent_audit <<'SQL'
CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    timestamp DOUBLE PRECISION NOT NULL,
    event_type TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL DEFAULT '',
    input_snapshot TEXT DEFAULT '',
    output_snapshot TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    prev_hash TEXT DEFAULT '',
    hash TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, sequence);
SQL
```

### Hash chain breaks after migration

This should NOT happen — the migration copies `prev_hash` and `hash` fields as-is. If verification fails:

1. Check that all events were copied: compare `engine.stats()` between source and target
2. Check event ordering: events must be written in `sequence` order within each session
3. Verify a single session: `engine.verify("session-id")`
4. Check for truncated fields: `input_snapshot` and `output_snapshot` are capped at 8000 chars

### Large JSONL files

For very large JSONL directories (100k+ files), listing sessions may be slow:

```bash
# Combine into a single file first
cat audit_logs/*.jsonl > combined.jsonl

# Or migrate directly with python
```

---

## 8. Post-Migration Checklist

After migration, verify everything:

```bash
# 1. Check data counts match
python -c "
from agent_audit.core.storage import create_store
old = create_store('./audit_logs', backend='jsonl')
new = create_store('postgresql://audit:***@localhost:5432/agent_audit', backend='postgresql')
print('Old:', old.stats())
print('New:', new.stats())
old.close()
new.close()
"

# 2. Verify hash chains (per session)
python -c "
from agent_audit.core.storage import create_store
store = create_store('postgresql://audit:***@localhost:5432/agent_audit', backend='postgresql')
for sid in store.sessions():
    ok = store.verify_session(sid)
    status = '✅' if ok else '❌ BROKEN'
    print(f'{status} {sid}')
store.close()
"

# 3. Start the API and check health
agent-audit serve &
curl http://localhost:8081/health

# 4. Update .env for production
export AGENT_AUDIT_DB_URL=postgresql://audit:***@localhost:5432/agent_audit
export AGENT_AUDIT_STORAGE_BACKEND=postgresql

# 5. Archive old data
tar -czf audit_logs_archive.tar.gz audit_logs/
# Keep the archive for 90 days, then delete
```
