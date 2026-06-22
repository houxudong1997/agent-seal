"""
Unified entry point for agent-audit — the AuditEngine.

This module is the single import target for all audit functionality,
backed by pluggable storage backends (JSONL, SQLite, PostgreSQL).

Usage::

    from agent_audit.engine import AuditEngine, create_store

    engine = AuditEngine("sqlite://audit.db")
    engine.log("sess-1", "decision", "my-agent", "v1", "input", "output")
    ok = engine.verify("sess-1")

    # Direct store access
    store = create_store("postgresql://user:***@host:5432/db")
    store.write(event)

Compat note: The AuditEngine was originally defined in
``agent_audit.core.storage``.  This top-level module is the canonical
public API from v1.0.0 onward, per the architecture doc at
``docs/architecture-v1.md`` line 1023.  The internal module continues
to work — consumers are encouraged to migrate their imports to this
module whenever convenient.

Architecture ref:
    1022:│   ├── __init__.py             # v1.0.0
    1023:│   ├── engine.py               # [NEW] AuditEngine (统一入口)
    1024:│   ├── trail.py                # [KEEP] 兼容层 → 委托 engine
    1025:│   ├── storage.py              # [DEPRECATE] → 委托 engine
"""

from __future__ import annotations

from .core.chain import (
    ChainEvent,
    SessionChain,
)

# -- re-export convenience types ---------------------------------------------
# Optional cryptography wrapper — lazy to avoid hard dep on pycryptodome
from .core.crypto import (
    SignedAuditEngine,
)

# -- core exports ------------------------------------------------------------
from .core.storage import (
    AuditEngine,
    AuditStore,
    JSONLStore,
    PostgreSQLStore,
    PostgreSQLStoreORM,
    SQLiteStore,
    create_store,
)

__all__ = [
    "AuditEngine",
    "AuditStore",
    "ChainEvent",
    "JSONLStore",
    "PostgreSQLStore",
    "PostgreSQLStoreORM",
    "SQLiteStore",
    "SessionChain",
    "SignedAuditEngine",
    "create_store",
]
