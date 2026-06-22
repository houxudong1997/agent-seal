"""
Database backend for agent-audit — DEPRECATED.

.. deprecated::
    This module is deprecated. Use ``agent_audit.engine.AuditEngine`` with
    a SQLite store URI directly::

        from agent_audit.engine import AuditEngine
        engine = AuditEngine("sqlite://audit.db")

    All calls now delegate to AuditEngine.  ``SQLiteTrail`` will be removed
    in a future major version.

Compatibility wrapper — delegates to agent_audit.engine.AuditEngine.
SQLiteTrail emits a ``DeprecationWarning`` on instantiation.
"""

import json
import sqlite3
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from agent_audit.core.chain import ChainEvent
from agent_audit.engine import AuditEngine


@dataclass
class AuditEvent:
    """One record in the agent's audit trail.  Legacy type.

    Compatibility type — wraps ChainEvent with an optional ``id`` field.
    """

    event_id: str
    session_id: str
    timestamp: float
    event_type: str
    agent_id: str
    prompt_version: str
    input_snapshot: str
    output_snapshot: str
    metadata: dict = field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""
    id: int | None = None

    @classmethod
    def from_chain_event(cls, ce: ChainEvent, row_id: int | None = None) -> "AuditEvent":
        """Convert a ChainEvent to the legacy AuditEvent type."""
        return cls(
            event_id=ce.event_id,
            session_id=ce.session_id,
            timestamp=ce.timestamp,
            event_type=ce.event_type,
            agent_id=ce.agent_id,
            prompt_version=ce.prompt_version,
            input_snapshot=ce.input_snapshot,
            output_snapshot=ce.output_snapshot,
            metadata=ce.metadata,
            prev_hash=ce.prev_hash,
            hash=ce.hash,
            id=row_id,
        )

    @classmethod
    def from_dict(cls, d: dict) -> "AuditEvent":
        """Convert a stored dict to the legacy AuditEvent type."""
        return cls(
            event_id=d.get("event_id", ""),
            session_id=d.get("session_id", ""),
            timestamp=d.get("timestamp", 0.0),
            event_type=d.get("event_type", ""),
            agent_id=d.get("agent_id", ""),
            prompt_version=d.get("prompt_version", ""),
            input_snapshot=d.get("input_snapshot", ""),
            output_snapshot=d.get("output_snapshot", ""),
            metadata=d.get("metadata", {}),
            prev_hash=d.get("prev_hash", ""),
            hash=d.get("hash", ""),
            id=d.get("id"),
        )


class SQLiteTrail:
    """SQLite-backed audit trail.  **Deprecated** — delegates to AuditEngine.

    .. deprecated::
        Use ``AuditEngine("sqlite://audit.db")`` instead.

    Same API as the original SQLiteTrail, but all methods now delegate
    to the new ``AuditEngine`` storage layer.
    """

    def __init__(self, db_path: str | Path):
        warnings.warn(
            "SQLiteTrail is deprecated. Use AuditEngine directly: "
            "from agent_audit.engine import AuditEngine; "
            f"engine = AuditEngine('sqlite://{db_path}')",
            DeprecationWarning,
            stacklevel=2,
        )
        self.db_path = str(db_path)
        self._engine = AuditEngine(f"sqlite://{self.db_path}")

    # ═══════════════════════ CORE API (delegates) ═══════════════════════

    def log(
        self,
        session_id: str,
        event_type: str,
        agent_id: str,
        prompt_version: str,
        input_snapshot: str,
        output_snapshot: str,
        metadata: dict | None = None,
    ) -> AuditEvent:
        """Record one event.  Delegates to AuditEngine."""
        ce = self._engine.log(
            session_id=session_id,
            event_type=event_type,
            agent_id=agent_id,
            prompt_version=prompt_version,
            input_text=input_snapshot,
            output_text=output_snapshot,
            metadata=metadata,
        )
        return AuditEvent.from_chain_event(ce)

    def verify(self) -> bool:
        """Verify all sessions are intact.  Delegates to AuditEngine."""
        try:
            return self._engine.verify(session_id=None)
        except ValueError as e:
            raise ValueError(str(e)) from e

    def search(
        self,
        session_id=None,
        event_type=None,
        agent_id=None,
        limit=100,
    ) -> list[dict]:
        """Search audit events by filter criteria.

        Uses engine.query() to push session_id and event_type filters
        to the storage layer, then applies agent_id filter in Python.
        """
        # Push session_id + event_type to storage layer
        events, _total = self._engine.query(
            session_id=session_id,
            event_type=event_type,
            limit=limit,
            offset=0,
        )

        # Apply agent_id filter in Python (not yet supported at storage layer)
        if agent_id:
            return [e for e in events if e.get("agent_id") == agent_id]
        return events

    def sessions(self) -> list[str]:
        """List all unique session IDs.  Delegates to AuditEngine."""
        return self._engine.sessions()

    def stats(self) -> dict:
        """Return summary statistics.  Delegates to AuditEngine."""
        return self._engine.stats()

    # ═══════════════════════ EXTRA API (deprecated helpers) ═══════════════════

    def count_by_type(self) -> dict[str, int]:
        """Count events grouped by event_type.

        .. deprecated::
            Use ``engine.stats()["event_types"]`` instead.
        """
        return dict(self._engine.stats().get("event_types", {}))

    def time_range(self) -> tuple[float, float] | None:
        """Return (min_timestamp, max_timestamp) across all events.

        .. deprecated::
            Access the underlying store directly for production use.
        """
        min_ts: float | None = None
        max_ts: float | None = None
        for sid in self._engine.sessions():
            for event in self._engine.read(sid):
                ts = event.get("timestamp", 0.0)
                if min_ts is None or ts < min_ts:
                    min_ts = ts
                if max_ts is None or ts > max_ts:
                    max_ts = ts
        if min_ts is None or max_ts is None:
            return None
        return (min_ts, max_ts)

    def purge_before(self, cutoff: float) -> int:
        """Delete all events with timestamp < *cutoff*.  Returns count.

        .. deprecated::
            Directly access the SQLite database for purge operations.
        """
        db = sqlite3.connect(self.db_path)
        try:
            c = db.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
            db.commit()
            return c.rowcount
        finally:
            db.close()

    def export_jsonl(self, path: str | Path):
        """Export all events to a JSONL file.

        .. deprecated::
            Read sessions via ``engine.read()`` and write manually.
        """
        with open(path, "w", encoding="utf-8") as f:
            for sid in self._engine.sessions():
                for event in self._engine.read(sid):
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
